#!/usr/bin/env python3
"""
sync_sheets.py — Full-rebuild sync from Google Sheets → data/resources.json.

Google Sheets is the source of truth.  Each tab in the spreadsheet becomes a
tag on every resource that lives in that tab.  Deduplication is by normalised
URL; when the same URL appears on multiple tabs or rows the *earliest* Date
wins and tags are merged.

Each resource also records its `placements` — the (tab, Category text) pairs
it came from — and the run writes data/graph.json (see build_graph.py), the
branch/topic graph shared by the web viewer and the MCP server.

Required environment:
    GOOGLE_SERVICE_ACCOUNT_JSON — the raw JSON string of a Google Cloud
                                  service-account key that has Viewer access
                                  to the spreadsheet.

Optional environment:
    SPREADSHEET_ID — override the default spreadsheet id.
"""

import json
import os
import re
import sys
import datetime
from pathlib import Path
from urllib.parse import urldefrag, urlsplit, urlunsplit

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from build_graph import write_graph

# ── Config ──────────────────────────────────────────────────────────────────

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1wWktmD3QEHIlV9ct_NH_i0UQ5ceyxMrMTTidihBmoSU",
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = REPO_ROOT / "data" / "resources.json"

EXPECTED_HEADERS = ["Date", "Link", "Name/Author", "Function/Summary",
                    "Category", "Review/Notes"]

# ── URL normalisation ───────────────────────────────────────────────────────

def normalise_url(raw: str) -> str:
    """Lowercase scheme+host, strip fragment, trailing slash."""
    raw = raw.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    path = parts.path.rstrip("/") or ""
    return urlunsplit((scheme, netloc, path, parts.query, ""))


# ── Date helpers ────────────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})"
    r"|(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})"
)

def parse_date(raw: str) -> str:
    """Best-effort parse into YYYY-MM-DD.  Returns '' on failure."""
    raw = raw.strip()
    if not raw:
        return ""
    m = _DATE_RE.search(raw)
    if not m:
        return ""
    if m.group(1):  # YYYY-MM-DD
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # DD/MM/YYYY
    return f"{m.group(6)}-{int(m.group(5)):02d}-{int(m.group(4)):02d}"


def earlier(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    return a if a <= b else b


# ── Category mapping ────────────────────────────────────────────────────────

_CATEGORY_MAP = {
    "tool": "tool",
    "tools": "tool",
    "reference": "reference",
    "tutorial": "tutorial",
    "news": "news",
    "research": "research",
    "community": "community",
    "other": "other",
}

def normalise_category(raw: str) -> str:
    return _CATEGORY_MAP.get(raw.strip().lower(), "other")


# ── Tab-name → tag ──────────────────────────────────────────────────────────

def tab_to_tag(tab_name: str) -> str:
    """Convert a tab title into a lowercase tag slug."""
    return re.sub(r"[\s/]+", "-", tab_name.strip()).lower()


# ── Core sync logic ────────────────────────────────────────────────────────

def fetch_all_tabs(service) -> list[tuple[str, list[list[str]]]]:
    """Return [(tab_name, rows), ...] for every tab in the spreadsheet."""
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = meta.get("sheets", [])
    tab_names = [s["properties"]["title"] for s in sheets]

    result = []
    for name in tab_names:
        resp = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"'{name}'")
            .execute()
        )
        rows = resp.get("values", [])
        result.append((name, rows))
    return result


def rows_to_entries(tab_name: str, rows: list[list[str]]) -> list[dict]:
    """Convert sheet rows (with header) into intermediate entry dicts."""
    if len(rows) < 2:
        return []

    header = [h.strip() for h in rows[0]]
    col = {}
    for expected in EXPECTED_HEADERS:
        for i, h in enumerate(header):
            if h.lower() == expected.lower():
                col[expected] = i
                break

    entries = []
    tag = tab_to_tag(tab_name)
    for row in rows[1:]:
        def cell(name: str) -> str:
            idx = col.get(name)
            if idx is None or idx >= len(row):
                return ""
            return row[idx].strip()

        link = cell("Link")
        if not link:
            continue

        norm = normalise_url(link)
        if not norm:
            continue

        date_str = parse_date(cell("Date"))
        cat_raw = cell("Category")
        category = normalise_category(cat_raw) if cat_raw else "other"
        tags = [tag]
        if cat_raw and cat_raw.lower() not in ("", "other", tag):
            tags.append(cat_raw.strip().lower())

        entries.append({
            "url": link,
            "_norm": norm,
            "title": cell("Name/Author") or link,
            "summary": cell("Function/Summary"),
            "category": category,
            "tags": tags,
            "placements": [{"branch": tag, "topic": cat_raw or None}],
            "created": date_str,
            "notes": cell("Review/Notes"),
        })
    return entries


def merge_entries(all_entries: list[dict]) -> list[dict]:
    """Deduplicate by normalised URL.  Earliest date wins; tags merge."""
    by_url: dict[str, dict] = {}
    for e in all_entries:
        norm = e["_norm"]
        if norm in by_url:
            existing = by_url[norm]
            existing["tags"] = sorted(set(existing["tags"]) | set(e["tags"]))
            existing["placements"] = existing.get("placements", []) + [
                p for p in e.get("placements", [])
                if p not in existing.get("placements", [])
            ]
            existing["created"] = earlier(existing["created"], e["created"])
            if not existing["notes"] and e["notes"]:
                existing["notes"] = e["notes"]
            if not existing["summary"] and e["summary"]:
                existing["summary"] = e["summary"]
        else:
            by_url[norm] = dict(e)
    return list(by_url.values())


def build_resources(merged: list[dict]) -> list[dict]:
    """Shape into the final JSON schema."""
    today = datetime.date.today().isoformat()
    resources = []
    for idx, e in enumerate(merged, start=1):
        resources.append({
            "id": idx,
            "url": e["url"],
            "title": e["title"],
            "summary": e["summary"],
            "category": e["category"],
            "tags": e["tags"],
            "placements": e.get("placements", []),
            "source_file": "",
            "created": e["created"],
            "added_at": e["created"] or today,
            "notes": e["notes"],
        })
    return resources


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not set", file=sys.stderr)
        sys.exit(1)

    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)

    print(f"Fetching spreadsheet {SPREADSHEET_ID} …")
    tabs = fetch_all_tabs(service)
    print(f"Found {len(tabs)} tabs: {[t[0] for t in tabs]}")

    all_entries: list[dict] = []
    for tab_name, rows in tabs:
        entries = rows_to_entries(tab_name, rows)
        print(f"  {tab_name}: {len(rows)-1 if len(rows) > 1 else 0} data rows → {len(entries)} entries")
        all_entries.extend(entries)

    merged = merge_entries(all_entries)
    print(f"Total after dedup: {len(merged)}")

    resources = build_resources(merged)

    RESOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(resources)} entries to {RESOURCES_FILE}")

    graph = write_graph(resources, branch_labels={tab_to_tag(name): name for name, _ in tabs})
    print(f"Wrote graph.json: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")


if __name__ == "__main__":
    main()
