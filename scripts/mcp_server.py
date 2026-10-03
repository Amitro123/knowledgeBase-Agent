#!/usr/bin/env python3
"""
mcp_server.py — MCP server for the knowledgeBase-Agent wiki.

Implements the Karpathy LLM Wiki pattern (ingest → query → write-back →
lint → index → log) over data/resources.json + wiki/ markdown articles.

Google Sheets remains the *source of truth* for resources.  The MCP exposes
read-only query over resources.json **plus** a read-write persistent wiki
layer (wiki/*.md) where an agent can synthesise answers, notes, and
curated articles that reference the underlying resources.

Ingesting a new resource writes it to data/resources.json **and** appends
a line to data/inbox.jsonl so a human can batch-sync new entries back to
the Google Sheet.

Run:
    python scripts/mcp_server.py          # stdio transport (default)
"""

import datetime
import json
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = REPO_ROOT / "data" / "resources.json"
INBOX_FILE = REPO_ROOT / "data" / "inbox.jsonl"
LOG_FILE = REPO_ROOT / "data" / "kb_log.jsonl"
WIKI_DIR = REPO_ROOT / "wiki"

mcp = MCPServer(
    "knowledgebase-agent",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_resources() -> list[dict]:
    if not RESOURCES_FILE.exists():
        return []
    with open(RESOURCES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_resources(resources: list[dict]) -> None:
    RESOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _log(action: str, detail: str = "") -> None:
    _append_jsonl(LOG_FILE, {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "action": action,
        "detail": detail,
    })


def _normalise_url(raw: str) -> str:
    from urllib.parse import urlsplit, urlunsplit
    raw = raw.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    path = parts.path.rstrip("/") or ""
    return urlunsplit((scheme, netloc, path, parts.query, ""))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def query(
    text: str = "",
    tag: str = "",
    category: str = "",
    limit: int = 20,
) -> str:
    """Search the knowledge base.

    Matches resources whose title, summary, notes, URL, or tags contain the
    search terms.  Filters can be combined (all must match).  Returns up to
    ``limit`` results formatted as readable text.
    """
    resources = _load_resources()
    hits: list[dict] = []
    q = text.lower()
    tag_q = tag.lower().strip()
    cat_q = category.lower().strip()

    for r in resources:
        if q and not any(
            q in (r.get(f) or "").lower()
            for f in ("title", "summary", "notes", "url")
        ) and not any(q in t.lower() for t in r.get("tags", [])):
            continue
        if tag_q and not any(tag_q in t.lower() for t in r.get("tags", [])):
            continue
        if cat_q and (r.get("category") or "").lower() != cat_q:
            continue
        hits.append(r)

    hits = hits[:limit]
    _log("query", f"text={text!r} tag={tag!r} category={category!r} → {len(hits)} hits")

    if not hits:
        return "No matching resources found."

    lines: list[str] = [f"Found {len(hits)} resource(s):\n"]
    for r in hits:
        tags_str = ", ".join(r.get("tags", []))
        lines.append(
            f"• [{r.get('title', '(no title)')}]({r.get('url', '')})\n"
            f"  Category: {r.get('category', '?')}  |  Tags: {tags_str}\n"
            f"  Summary: {r.get('summary', '')}\n"
            f"  Notes: {r.get('notes', '') or '—'}\n"
            f"  Added: {r.get('added_at', '?')}\n"
        )
    return "\n".join(lines)


@mcp.tool()
def ingest(
    url: str,
    title: str = "",
    summary: str = "",
    category: str = "other",
    tags: list[str] | None = None,
    notes: str = "",
) -> str:
    """Add a new resource to the knowledge base.

    Writes immediately to data/resources.json so the site picks it up, and
    also appends to data/inbox.jsonl so the entry can be synced back to the
    Google Sheet (which is the canonical source of truth).
    """
    norm = _normalise_url(url)
    if not norm:
        return "ERROR: url is required."

    resources = _load_resources()
    for r in resources:
        if _normalise_url(r.get("url", "")) == norm:
            return f"Already exists (id={r.get('id')}): {r.get('title', url)}"

    today = datetime.date.today().isoformat()
    new_id = max((r.get("id", 0) for r in resources), default=0) + 1
    entry = {
        "id": new_id,
        "url": url.strip(),
        "title": title.strip() or url.strip(),
        "summary": summary.strip(),
        "category": category.strip().lower() or "other",
        "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
        "source_file": "",
        "created": today,
        "added_at": today,
        "notes": notes.strip(),
    }

    resources.append(entry)
    _save_resources(resources)

    _append_jsonl(INBOX_FILE, {
        "ts": today,
        "action": "ingest",
        "entry": entry,
    })
    _log("ingest", f"id={new_id} url={url}")

    return (
        f"Ingested resource id={new_id}: {entry['title']}\n"
        f"Written to resources.json and queued in inbox.jsonl for Sheet sync."
    )


@mcp.tool()
def lint() -> str:
    """Validate the knowledge base and report quality issues.

    Checks for: missing titles, empty summaries, duplicate URLs, resources
    with no tags, and broken-looking URLs.
    """
    resources = _load_resources()
    issues: list[str] = []
    seen_urls: dict[str, int] = {}

    for r in resources:
        rid = r.get("id", "?")
        if not r.get("title") or r["title"] == r.get("url"):
            issues.append(f"id={rid}: missing or URL-only title")
        if not r.get("summary"):
            issues.append(f"id={rid}: empty summary")
        if not r.get("tags"):
            issues.append(f"id={rid}: no tags")

        norm = _normalise_url(r.get("url", ""))
        if norm in seen_urls:
            issues.append(
                f"id={rid}: duplicate URL (same as id={seen_urls[norm]})"
            )
        else:
            seen_urls[norm] = rid

        url = r.get("url", "")
        if url and not url.startswith(("http://", "https://")):
            issues.append(f"id={rid}: URL missing scheme: {url}")

    _log("lint", f"{len(issues)} issues in {len(resources)} resources")

    if not issues:
        return f"All {len(resources)} resources passed lint. No issues found."

    header = f"Found {len(issues)} issue(s) in {len(resources)} resources:\n"
    return header + "\n".join(f"  • {i}" for i in issues)


@mcp.tool()
def index() -> str:
    """Return a structured index of the knowledge base.

    Shows counts by category and top tags — useful for an agent to understand
    what the knowledge base covers before querying.
    """
    resources = _load_resources()
    if not resources:
        return "Knowledge base is empty."

    cat_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for r in resources:
        cat = r.get("category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for t in r.get("tags", []):
            tn = t.lower().strip()
            if tn:
                tag_counts[tn] = tag_counts.get(tn, 0) + 1

    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:25]

    lines = [
        f"Knowledge-base index — {len(resources)} resources\n",
        "Categories:",
    ]
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat}: {cnt}")

    lines.append(f"\nTop {len(top_tags)} tags:")
    for tag, cnt in top_tags:
        lines.append(f"  {tag}: {cnt}")

    dates = [r.get("added_at", "") for r in resources if r.get("added_at")]
    if dates:
        lines.append(f"\nDate range: {min(dates)} → {max(dates)}")

    _log("index", f"{len(resources)} resources indexed")
    return "\n".join(lines)


@mcp.tool()
def log(limit: int = 30) -> str:
    """Return recent activity log entries (newest first)."""
    if not LOG_FILE.exists():
        return "No activity log yet."

    entries: list[str] = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(line)

    entries = entries[-limit:]
    entries.reverse()

    if not entries:
        return "Activity log is empty."

    lines = [f"Last {len(entries)} log entries:\n"]
    for e in entries:
        try:
            rec = json.loads(e)
            lines.append(
                f"  [{rec.get('ts', '?')}] {rec.get('action', '?')}: "
                f"{rec.get('detail', '')}"
            )
        except json.JSONDecodeError:
            lines.append(f"  (unparseable) {e[:120]}")
    return "\n".join(lines)


@mcp.tool()
def read_article(slug: str) -> str:
    """Read a wiki article by slug.

    Articles live in wiki/<slug>.md.  Returns the markdown content or an
    error if the article does not exist.  Use ``list_articles`` to discover
    available articles.
    """
    safe = _safe_slug(slug)
    path = WIKI_DIR / f"{safe}.md"
    if not path.exists():
        return f"Article '{safe}' not found. Use list_articles to see available articles."
    _log("read_article", safe)
    return path.read_text(encoding="utf-8")


@mcp.tool()
def write_article(slug: str, content: str) -> str:
    """Create or overwrite a wiki article.

    Use this to persist synthesised knowledge: query answers, curated lists,
    topic overviews, or research notes.  The article is written to
    wiki/<slug>.md.

    Best practice: include a YAML-style front-matter block at the top with
    ``title``, ``created``/``updated``, and ``tags`` so the article is
    easy to find later.
    """
    safe = _safe_slug(slug)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    path = WIKI_DIR / f"{safe}.md"
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    action = "updated" if existed else "created"
    _log("write_article", f"{action} wiki/{safe}.md ({len(content)} chars)")
    return f"Article wiki/{safe}.md {action} ({len(content)} chars)."


@mcp.tool()
def list_articles() -> str:
    """List all wiki articles with their front-matter titles."""
    if not WIKI_DIR.exists():
        return "No wiki articles yet. Use write_article to create one."

    articles: list[str] = []
    for md in sorted(WIKI_DIR.glob("*.md")):
        if md.name.startswith("_"):
            continue
        first_lines = md.read_text(encoding="utf-8")[:500]
        title_match = re.search(r"^title:\s*(.+)", first_lines, re.MULTILINE)
        title = title_match.group(1).strip().strip('"\'') if title_match else md.stem
        size = md.stat().st_size
        articles.append(f"  • {md.stem} — {title} ({size} bytes)")

    if not articles:
        return "No wiki articles yet."

    _log("list_articles", f"{len(articles)} articles")
    return f"Wiki articles ({len(articles)}):\n" + "\n".join(articles)


def _safe_slug(raw: str) -> str:
    """Sanitise a slug to prevent path traversal."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9_\-]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "untitled"


@mcp.tool()
def get_resource(id: int | None = None, url: str = "") -> str:
    """Get a single resource by id or URL."""
    resources = _load_resources()
    for r in resources:
        if id is not None and r.get("id") == id:
            _log("get_resource", f"id={id}")
            return json.dumps(r, ensure_ascii=False, indent=2)
        if url and _normalise_url(r.get("url", "")) == _normalise_url(url):
            _log("get_resource", f"url={url}")
            return json.dumps(r, ensure_ascii=False, indent=2)
    return "Resource not found."


# ---------------------------------------------------------------------------
# MCP Resources (read-only context an agent can attach)
# ---------------------------------------------------------------------------

@mcp.resource("kb://index")
def resource_index() -> str:
    """Full knowledge-base index as a resource."""
    return index()


@mcp.resource("kb://stats")
def resource_stats() -> str:
    """Quick stats about the knowledge base."""
    resources = _load_resources()
    cats = set(r.get("category", "other") for r in resources)
    tags = set()
    for r in resources:
        tags.update(t.lower() for t in r.get("tags", []))
    return json.dumps({
        "total_resources": len(resources),
        "categories": len(cats),
        "unique_tags": len(tags),
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
