#!/usr/bin/env python3
"""
check_link.py — Pre-flight check for saving a link to the knowledge-base sheet.

For each URL it returns, as JSON:
  - the cleaned canonical URL to write in the sheet (tracking parameters
    removed, GitHub repo root, arXiv abstract page, no fragment or trailing /),
  - every existing row with the same link (tab, category, title, date),
  - privacy / validity warnings,
and, once for the whole call, the existing topics of every tab.

Duplicates are matched the way the sync merges them (sync_sheets.normalise_url),
after the same cleaning, so "duplicate" here means "would collapse into the same
resource in the graph".

Data source: the repo snapshot (data/resources.json + data/graph.json), which
is as fresh as the last sync. Rows added to the sheet since then are invisible
to it; pass them with --rows (e.g. the target tab, read live through a Sheets
connector) to include them.

Usage:
    python scripts/check_link.py URL [URL ...]
    python scripts/check_link.py URL --rows live_rows.json
    python scripts/check_link.py URL --no-network      # don't resolve short links

--rows file: a JSON list of objects with keys
    tab, link, category (optional), name (optional), date (optional)

No credentials are needed and nothing is written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = REPO_ROOT / "data" / "resources.json"
GRAPH_FILE = REPO_ROOT / "data" / "graph.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # same normaliser the sync uses to merge rows
    from sync_sheets import normalise_url
except ImportError:  # sync_sheets needs the Google client libraries
    def normalise_url(raw: str) -> str:
        """Copy of sync_sheets.normalise_url (kept identical by a test)."""
        raw = raw.strip()
        if not raw:
            return ""
        parts = urlsplit(raw)
        scheme = (parts.scheme or "https").lower()
        netloc = (parts.netloc or "").lower()
        path = parts.path.rstrip("/") or ""
        return urlunsplit((scheme, netloc, path, parts.query, ""))

from build_graph import github_repo, slugify  # noqa: E402

# ── Cleaning ────────────────────────────────────────────────────────────────

TRACKING_PARAMS = {
    "ref", "ref_src", "ref_url", "source", "via", "fbclid", "gclid", "dclid",
    "msclkid", "mc_cid", "mc_eid", "si", "igshid", "trk", "trackingid",
    "_hsenc", "_hsmi", "mkt_tok", "spm", "share", "s",
}
SHORTENERS = {
    "lnkd.in", "t.co", "bit.ly", "goo.gl", "share.google", "buff.ly",
    "ow.ly", "tinyurl.com", "rebrand.ly", "dlvr.it", "youtu.be",
}


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in TRACKING_PARAMS


def resolve_short_link(url: str, timeout: float = 6.0) -> str | None:
    """Follow redirects of a shortener and return the final URL, or None."""
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0 (link-check)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (link-check)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.geturl()
        except Exception:
            return None


def clean_url(raw: str) -> str:
    """Canonical form to store in the sheet (no network)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = parts.path

    # GitHub: the repository root, unless it is a file/folder deep link
    # (a bare /tree/<branch> is just the root on another branch)
    repo = github_repo(raw)
    if repo and not re.match(r"^/[^/]+/[^/]+/(blob|tree)/[^/]+/.", path):
        host, path = "github.com", "/" + repo
    elif repo:
        host = "github.com"
    # arXiv: abstract page instead of the PDF
    m = re.match(r"^/pdf/(\d{4}\.\d{4,5})(v\d+)?(\.pdf)?$", path)
    if host.removeprefix("www.") == "arxiv.org" and m:
        path = f"/abs/{m.group(1)}"

    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _is_tracking(k)])
    return urlunsplit((scheme, host, path.rstrip("/"), query, ""))


# ── Warnings ────────────────────────────────────────────────────────────────

_PRIVATE_GOOGLE = re.compile(r"^(drive|docs)\.google\.com$|^share\.google$")
_SECRET_PARAMS = {"token", "key", "sig", "signature", "expires", "access_token",
                  "auth", "password", "x-amz-signature", "x-amz-credential"}
_INTERNAL_HOST = re.compile(r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)|\.(internal|local|lan|corp)$")
_PERSONAL_PATH = re.compile(r"/(l|r|ref|invite|referral|affiliate)/", re.I)


def warnings_for(url: str) -> list[str]:
    out = []
    parts = urlsplit(url)
    host = parts.netloc.lower().split(":")[0]
    if _PRIVATE_GOOGLE.search(host):
        out.append("google-drive-link: may expose a private file; check sharing before saving")
    if _INTERNAL_HOST.search(host):
        out.append("internal-host: not reachable from the public site")
    if any(k.lower() in _SECRET_PARAMS for k, _ in parse_qsl(parts.query)):
        out.append("secret-param: URL carries a token/signature; don't save it")
    if _PERSONAL_PATH.search(parts.path):
        out.append("personal-link: looks like a referral/invite/funnel link; check for personal identifiers")
    if host.removeprefix("www.") in SHORTENERS:
        out.append("short-link: could not resolve; resolve it before saving")
    return out


# ── Index of existing rows ──────────────────────────────────────────────────

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def build_index(resources: list[dict], graph: dict, live_rows: list[dict] | None = None):
    """Return (key -> [row], topics_by_tab, snapshot_generated_at)."""
    labels = {n.get("slug"): n["label"] for n in graph.get("nodes", []) if n.get("type") == "branch"}
    index: dict[str, list[dict]] = defaultdict(list)
    topic_counts: dict[str, Counter] = defaultdict(Counter)
    for label in labels.values():
        topic_counts[label]  # every tab, including empty ones

    def add(tab, link, category, title, date, source):
        key = normalise_url(clean_url(link))
        if not key:
            return
        row = {"tab": tab, "category": category or "", "title": title or "",
               "date": date or "", "source": source}
        if row not in index[key]:
            index[key].append(row)
        if category and category.strip().lower() not in ("", "other"):
            topic_counts[tab][category.strip()] += 1

    for r in resources:
        placements = r.get("placements") or [{"branch": t, "topic": None} for t in r.get("tags", [])[:1]]
        for p in placements:
            tab = labels.get(p.get("branch"), p.get("branch") or "")
            add(tab, r.get("url", ""), p.get("topic"), r.get("title"), r.get("added_at"), "snapshot")
    for row in live_rows or []:
        add(row.get("tab", ""), row.get("link", ""), row.get("category"),
            row.get("name"), row.get("date"), "live")

    # one spelling per topic (the most used one), grouped case-insensitively
    topics_by_tab = {}
    for tab, counts in topic_counts.items():
        merged: dict[str, Counter] = defaultdict(Counter)
        for spelling, n in counts.items():
            merged[slugify(spelling)][spelling] += n
        topics_by_tab[tab] = sorted(
            ({"topic": c.most_common(1)[0][0], "count": sum(c.values())} for c in merged.values()),
            key=lambda t: (-t["count"], t["topic"].lower()))
    return index, topics_by_tab, graph.get("generated_at", "")


def check(urls: list[str], resources: list[dict], graph: dict,
          live_rows: list[dict] | None = None, network: bool = True) -> dict:
    index, topics_by_tab, generated_at = build_index(resources, graph, live_rows)
    results = []
    for raw in urls:
        resolved = None
        host = urlsplit(raw if "://" in raw else "https://" + raw).netloc.lower().removeprefix("www.")
        if network and host in SHORTENERS:
            resolved = resolve_short_link(raw if "://" in raw else "https://" + raw)
        cleaned = clean_url(resolved or raw)
        results.append({
            "input": raw,
            "clean_url": cleaned,
            "changed": cleaned != raw.strip(),
            "resolved_from_short_link": bool(resolved),
            "github_repo": github_repo(cleaned),
            "duplicate": index.get(normalise_url(cleaned), []),
            "warnings": warnings_for(cleaned),
        })
    return {
        "source": "snapshot+live" if live_rows else "snapshot",
        "snapshot_generated_at": generated_at,
        "results": results,
        "topics_by_tab": topics_by_tab,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--rows", help="JSON file with live rows read from the sheet")
    ap.add_argument("--no-network", action="store_true", help="don't resolve short links")
    ap.add_argument("--no-topics", action="store_true", help="omit topics_by_tab from the output")
    args = ap.parse_args(argv)

    live = None
    if args.rows:
        live = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    report = check(args.urls, _load_json(RESOURCES_FILE, []), _load_json(GRAPH_FILE, {}),
                   live, network=not args.no_network)
    if args.no_topics:
        report.pop("topics_by_tab")
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
