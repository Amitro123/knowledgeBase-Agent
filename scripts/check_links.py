#!/usr/bin/env python3
"""
check_links.py — Verify that every URL in data/resources.json still resolves.

Designed to run after the sheet-sync step in the same GitHub Actions workflow.
It never blocks the sync: exit-code 0 even when dead links are found.
Dead links are reported in $GITHUB_STEP_SUMMARY (if available) and on stdout.

A link is "dead" when:
  • HTTP status is 404 or 410, OR
  • Google Drive / Docs returns 200 but the HTML says the file was deleted.

Timeouts, rate-limits (429), auth walls (401/403), and server errors (5xx)
are NOT treated as dead — they are listed separately as "skipped".
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = REPO_ROOT / "data" / "resources.json"

REQUEST_TIMEOUT = 20          # seconds per request
CONCURRENCY_DELAY = 0.25      # polite pause between requests
MAX_REDIRECTS = 5

_SESSION: requests.Session | None = None

# ---------------------------------------------------------------------------
# Response classification
# ---------------------------------------------------------------------------

_DRIVE_GONE_PATTERNS = [
    re.compile(r"sorry,?\s+the\s+file\s+you\s+have\s+requested\s+does\s+not\s+exist", re.I),
    re.compile(r"<title>\s*Page\s*Not\s*Found\s*</title>", re.I),
    re.compile(r"the\s+file\s+is\s+(?:no\s+longer|not)\s+available", re.I),
    re.compile(r"this\s+file\s+has\s+been\s+(?:removed|trashed|deleted)", re.I),
]

_GOOGLE_DRIVE_HOSTS = {"drive.google.com", "docs.google.com"}


def is_google_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in _GOOGLE_DRIVE_HOSTS


def _body_says_gone(body: str) -> bool:
    """True when the HTML body contains a known 'file is gone' marker."""
    return any(pat.search(body) for pat in _DRIVE_GONE_PATTERNS)


def classify_response(url: str, status_code: int, body: str) -> str:
    """Return 'dead', 'alive', or 'skip'.

    >>> classify_response("https://x.com", 404, "")
    'dead'
    >>> classify_response("https://x.com", 200, "<html>OK</html>")
    'alive'
    """
    if status_code in (404, 410):
        return "dead"

    if status_code == 200 and is_google_url(url) and _body_says_gone(body):
        return "dead"

    if status_code in (401, 403, 429) or status_code >= 500:
        return "skip"

    if 200 <= status_code < 400:
        return "alive"

    return "skip"


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; catalog-link-checker/1.0; "
                "+https://github.com)"
            ),
        })
        _SESSION.max_redirects = MAX_REDIRECTS
    return _SESSION


def check_url(url: str) -> tuple[str, int | None, str]:
    """Fetch *url* and return (verdict, status_code, reason).

    verdict is one of 'dead', 'alive', 'skip'.
    reason is a human-readable note (e.g. '404 Not Found').
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "skip", None, f"non-HTTP scheme: {parsed.scheme}"

    sess = _get_session()

    need_body = is_google_url(url)

    try:
        if need_body:
            resp = sess.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            body = resp.text
        else:
            resp = sess.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            body = ""
            if resp.status_code in (404, 410, 405):
                resp = sess.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                body = resp.text

        verdict = classify_response(url, resp.status_code, body)
        reason = f"HTTP {resp.status_code}"
        if verdict == "dead" and is_google_url(url) and resp.status_code == 200:
            reason = "HTTP 200 but page says file is gone"
        return verdict, resp.status_code, reason

    except requests.exceptions.Timeout:
        return "skip", None, "timeout"
    except requests.exceptions.TooManyRedirects:
        return "skip", None, "too many redirects"
    except requests.exceptions.ConnectionError as exc:
        return "skip", None, f"connection error: {exc}"
    except requests.exceptions.RequestException as exc:
        return "skip", None, f"request error: {exc}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_resources(path: Path | None = None) -> list[dict]:
    path = path or RESOURCES_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def check_all(resources: list[dict], *, delay: float = CONCURRENCY_DELAY) -> dict:
    """Check every resource URL.  Returns a results dict."""
    dead: list[dict] = []
    alive: list[dict] = []
    skipped: list[dict] = []

    for r in resources:
        url = r.get("url", "")
        if not url:
            continue

        verdict, status, reason = check_url(url)
        entry = {"id": r.get("id"), "url": url, "title": r.get("title", ""),
                 "status": status, "reason": reason}

        if verdict == "dead":
            dead.append(entry)
        elif verdict == "alive":
            alive.append(entry)
        else:
            skipped.append(entry)

        if delay > 0:
            time.sleep(delay)

    return {"dead": dead, "alive": alive, "skipped": skipped}


def format_summary(results: dict) -> str:
    """Markdown summary suitable for $GITHUB_STEP_SUMMARY."""
    lines: list[str] = []
    dead = results["dead"]
    skipped = results["skipped"]
    alive = results["alive"]
    total = len(dead) + len(alive) + len(skipped)

    if dead:
        lines.append(f"## Dead links found ({len(dead)})\n")
        lines.append("| # | Title | URL | Reason |")
        lines.append("|---|-------|-----|--------|")
        for d in dead:
            safe_title = d["title"].replace("|", "\\|")
            lines.append(f"| {d['id']} | {safe_title} | {d['url']} | {d['reason']} |")
        lines.append("")
    else:
        lines.append("## All links are alive\n")

    lines.append(f"Checked **{total}** links: "
                 f"**{len(alive)}** alive, **{len(dead)}** dead, "
                 f"**{len(skipped)}** skipped (timeout / auth / error).\n")

    if skipped:
        lines.append("<details><summary>Skipped links</summary>\n")
        for s in skipped:
            lines.append(f"- [{s['title']}]({s['url']}) — {s['reason']}")
        lines.append("\n</details>\n")

    return "\n".join(lines)


def main() -> None:
    if not RESOURCES_FILE.exists():
        print(f"WARNING: {RESOURCES_FILE} not found — skipping link check.")
        return

    resources = load_resources()
    print(f"Checking {len(resources)} catalog links …")

    results = check_all(resources)
    summary = format_summary(results)

    print(summary)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(summary)

    dead = results["dead"]
    if dead:
        print(f"\n::warning::Found {len(dead)} dead link(s) in the catalog.")
        for d in dead:
            print(f"::warning file=data/resources.json::"
                  f"Dead link (id {d['id']}): {d['url']} — {d['reason']}")


if __name__ == "__main__":
    main()
