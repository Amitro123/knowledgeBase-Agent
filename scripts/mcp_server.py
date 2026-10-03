#!/usr/bin/env python3
"""
mcp_server.py — Read-only MCP server for the knowledgeBase-Agent.

Exposes data/resources.json (generated from Google Sheets) as MCP tools:
  - query_kb(question)         — keyword-search resources, return matches
                                 + full detail of the top hit
  - get_resource(resource_id)  — return full detail of one resource by id
  - search_tags(question, max_results)  — keyword-search the tag index
  - get_tag(tag)               — list every resource carrying a given tag

The server never writes to resources.json, the Sheet, or anything else.
A restart is always safe.

Run via stdio (default for Claude Code / Cursor):
    python scripts/mcp_server.py

Or set MCP_TRANSPORT=streamable-http to serve over HTTP.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = ROOT / "data" / "resources.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_resources() -> list[dict]:
    if not RESOURCES_FILE.exists():
        return []
    return json.loads(RESOURCES_FILE.read_text(encoding="utf-8"))


# Hebrew and English stop words — kept small and targeted, same idea as the
# reference server.  Hebrew prefixes (ב-, ל-, מ-, ו-, כ-, ש-, ה-) attach
# directly to a word, so bidirectional substring matching handles them;
# the stop list just removes standalone noise.
_STOP = {
    "the", "a", "an", "is", "in", "of", "and", "or", "how", "what",
    "does", "do", "i", "for", "to", "that", "this", "it", "be",
    "הוא", "היא", "הם", "האם", "מה", "מי", "מתי", "כמה",
    "איפה", "איזה", "איזו", "איך", "כיצד",
    "עם", "של", "על", "או", "גם", "רק", "כל", "יש", "אין",
}


def _search_resources(question: str, resources: list[dict],
                      max_results: int = 10) -> list[dict]:
    """Keyword-search resources with bidirectional substring matching.

    Bidirectional: for each keyword kw and each haystack word hw, a hit
    counts if kw is contained in hw OR hw is contained in kw.  This lets
    Hebrew-prefixed query words (e.g. "בצוואה") match a bare tag
    ("צוואה") and vice-versa.  Both sides must be >= 2 chars to avoid
    single-letter noise.
    """
    keywords = {w for w in re.findall(r"\w+", question.lower())
                if len(w) >= 2} - _STOP
    if not keywords:
        return []

    scored: list[tuple[int, dict]] = []
    for r in resources:
        tags_str = " ".join(r.get("tags", []) or [])
        haystack = (
            f"{r.get('title', '')} {r.get('summary', '')} "
            f"{r.get('notes', '')} {tags_str} "
            f"{r.get('category', '')} {r.get('url', '')}"
        ).lower()
        haystack_words = {w for w in re.findall(r"\w+", haystack)
                         if len(w) >= 2}
        hits = sum(
            1
            for kw in keywords
            if any(kw in hw or hw in kw for hw in haystack_words)
        )
        if hits > 0:
            scored.append((hits, r))

    scored.sort(key=lambda t: -t[0])
    return [r for _, r in scored[:max_results]]


def _format_resource_short(r: dict) -> str:
    tags = ", ".join(r.get("tags", []))
    return (
        f"- **id={r.get('id')}** — {r.get('title', '(no title)')} "
        f"| {r.get('summary', '')}"
        f"{f' | tags: {tags}' if tags else ''}"
    )


def _format_resource_full(r: dict) -> str:
    tags = ", ".join(r.get("tags", []))
    return (
        f"id: {r.get('id')}\n"
        f"title: {r.get('title', '')}\n"
        f"url: {r.get('url', '')}\n"
        f"category: {r.get('category', '')}\n"
        f"tags: {tags}\n"
        f"summary: {r.get('summary', '')}\n"
        f"notes: {r.get('notes', '') or '—'}\n"
        f"added_at: {r.get('added_at', '')}\n"
        f"created: {r.get('created', '')}"
    )


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = MCPServer(
    "knowledgebase-agent",
    version="1.0.0",
    instructions=(
        "This server exposes a read-only AI/ML knowledge base maintained via Google Sheets. "
        "Use query_kb to search by topic (English or Hebrew keywords). "
        "Use get_resource to fetch a specific resource by its numeric id. "
        "Use search_tags to discover which tags exist and how many resources each has. "
        "Use get_tag to list every resource carrying a specific tag. "
        "This server never writes to the knowledge base."
    ),
)


@mcp.tool(
    description=(
        "Search the knowledge base by question or topic. "
        "Returns a list of matching resources (id, title, summary) and the "
        "full detail of the top match. Accepts English or Hebrew keywords. "
        "Uses bidirectional substring matching so Hebrew prefixes still hit."
    )
)
def query_kb(question: str, max_results: int = 10) -> str:
    """Search the KB by question or topic."""
    question = question.strip()
    if not question:
        return "Error: 'question' cannot be empty."

    resources = _load_resources()
    matches = _search_resources(question, resources, max_results)

    if not matches:
        keywords = set(re.findall(r"\w+", question.lower()))
        if keywords.issubset(_STOP):
            return (
                f"All words in '{question}' are common stop words. "
                "Use topic-specific terms like 'RAG', 'agents', 'MCP', "
                "'vector database', 'כלים', 'מחקר'."
            )
        return (
            f"No resources found for: '{question}'.\n"
            "Try get_resource with a specific id, or broaden your keywords."
        )

    lines = ["## Matching resources\n"]
    for m in matches:
        lines.append(_format_resource_short(m))

    top = matches[0]
    lines.append(f"\n---\n### Top match (id={top.get('id')})\n")
    lines.append(_format_resource_full(top))

    return "\n".join(lines)


@mcp.tool(
    description=(
        "Retrieve the full detail of a specific resource by its numeric id. "
        "Use query_kb first if you don't know the exact id."
    )
)
def get_resource(resource_id: int) -> str:
    """Fetch one resource by id."""
    resources = _load_resources()
    for r in resources:
        if r.get("id") == resource_id:
            return _format_resource_full(r)

    candidates = [
        r["id"] for r in resources
        if abs(r.get("id", 0) - resource_id) <= 3
    ]
    hint = f"\nNearby ids: {candidates}" if candidates else ""
    return f"Resource not found: id={resource_id}.{hint}"


@mcp.tool(
    description=(
        "Search the tag index by keyword. Returns matching tags with their "
        "resource counts — useful for discovering what topics the knowledge "
        "base covers before drilling into specific resources with query_kb. "
        "Bidirectional substring matching supports Hebrew prefixes."
    )
)
def search_tags(question: str, max_results: int = 10) -> str:
    """Search the tag/category index by keyword."""
    question = question.strip()
    if not question:
        return "Error: 'question' cannot be empty."

    resources = _load_resources()
    tag_counts: dict[str, int] = {}
    for r in resources:
        for t in r.get("tags", []):
            tn = t.strip().lower()
            if tn:
                tag_counts[tn] = tag_counts.get(tn, 0) + 1

    if not tag_counts:
        return "No tags in knowledge base."

    keywords = {w for w in re.findall(r"\w+", question.lower())
                if len(w) >= 2} - _STOP
    if not keywords:
        return f"No usable keywords in '{question}'."

    scored: list[tuple[int, str, int]] = []
    for tag, count in tag_counts.items():
        tag_words = {w for w in re.findall(r"\w+", tag) if len(w) >= 2}
        hits = sum(
            1
            for kw in keywords
            if any(kw in tw or tw in kw for tw in tag_words)
        )
        if hits > 0:
            scored.append((hits, tag, count))

    scored.sort(key=lambda t: (-t[0], -t[2]))
    top = scored[:max_results]

    if not top:
        return (
            f"No tags found for: '{question}'. "
            "Try query_kb for a broader search."
        )

    lines = [f"Matching tags ({len(top)}):\n"]
    for _, tag, count in top:
        lines.append(f"- **{tag}** ({count} resource{'s' if count != 1 else ''})")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "List every resource carrying a specific tag. "
        "Use search_tags first if you don't know the exact tag name."
    )
)
def get_tag(tag: str) -> str:
    """List all resources with a given tag."""
    tag = tag.strip().lower()
    if not tag:
        return "Error: 'tag' cannot be empty."

    resources = _load_resources()
    matches = [r for r in resources
               if tag in [t.strip().lower() for t in r.get("tags", [])]]

    if not matches:
        all_tags = set()
        for r in resources:
            all_tags.update(t.strip().lower() for t in r.get("tags", []))
        candidates = [t for t in all_tags if tag in t or t in tag]
        hint = f"\nSimilar tags: {', '.join(sorted(candidates)[:10])}" if candidates else ""
        return f"No resources found with tag '{tag}'.{hint}"

    lines = [f"Resources tagged '{tag}' ({len(matches)}):\n"]
    for r in matches:
        lines.append(_format_resource_short(r))
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8765")),
        )
    else:
        mcp.run(transport="stdio")
