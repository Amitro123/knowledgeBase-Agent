#!/usr/bin/env python3
"""
mcp_server.py — Read-only MCP server for the knowledgeBase-Agent.

Exposes data/resources.json (generated from Google Sheets) as MCP tools:
  - query_kb(question)         — keyword-search resources, return matches
                                 + full detail of the top hit
  - get_resource(resource_id)  — return full detail of one resource by id
  - search_tags(question, max_results)  — keyword-search the tag index
  - get_tag(tag)               — list every resource carrying a given tag
  - list_branches()            — the branches (sheet tabs) with their topics
  - get_branch(branch)         — one branch: its topics and their resources
  - find_topic(name)           — a topic name across every branch
  - get_node(node_id)          — any graph node with its incoming/outgoing edges
  - list_github_repos(branch)  — every GitHub project (detected from the URL)

The branch tools read data/graph.json, the same graph the web viewer draws
(built by build_graph.py), so an agent and a person navigate one structure.

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
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = ROOT / "data" / "resources.json"
GRAPH_FILE = ROOT / "data" / "graph.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_graph import build_graph, github_repo, slugify  # noqa: E402

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_resources() -> list[dict]:
    if not RESOURCES_FILE.exists():
        return []
    return json.loads(RESOURCES_FILE.read_text(encoding="utf-8"))


def _load_graph() -> dict:
    """graph.json if present, else built on the fly from resources.json."""
    if GRAPH_FILE.exists():
        return json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    return build_graph(_load_resources())


class _Graph:
    """Index over graph.json for neighbour lookups."""

    def __init__(self, graph: dict):
        self.nodes = {n["id"]: n for n in graph.get("nodes", [])}
        self.out: dict[str, list[dict]] = {}
        self.inc: dict[str, list[dict]] = {}
        for e in graph.get("edges", []):
            self.out.setdefault(e["source"], []).append(e)
            self.inc.setdefault(e["target"], []).append(e)

    def children(self, node_id: str, rel: str) -> list[dict]:
        return [self.nodes[e["target"]] for e in self.out.get(node_id, [])
                if e["type"] == rel and e["target"] in self.nodes]

    def of_type(self, kind: str) -> list[dict]:
        return [n for n in self.nodes.values() if n["type"] == kind]

    def find_branch(self, query: str) -> dict | None:
        q = slugify(query)
        branches = self.of_type("branch")
        for b in branches:
            if q in (b.get("slug"), slugify(b["label"]), slugify(b["id"].split(":", 1)[-1])):
                return b
        partial = [b for b in branches if q and (q in b["slug"] or b["slug"] in q)]
        return partial[0] if len(partial) == 1 else None


def _node_line(n: dict) -> str:
    if n["type"] == "resource":
        summary = f" | {n['summary']}" if n.get("summary") else ""
        return f"- **{n['id']}** — {n['label']}{summary}"
    count = f" ({n.get('count', 0)} resources)" if "count" in n else ""
    return f"- **{n['id']}** — {n['label']}{count}"


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
        f"added_at: {r.get('added_at', '')}"
        f"{' (first seen by the sync; the sheet row has no Date)' if not r.get('created') else ''}\n"
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
        "The knowledge base is also a graph: branches (sheet tabs) contain topics, "
        "topics contain resources. Start with list_branches, drill in with "
        "get_branch, look a topic up across branches with find_topic, and walk "
        "edges from any node with get_node. list_github_repos lists every GitHub "
        "project, wherever it is filed. Resource node ids look like "
        "'resource:12'; the number is the id get_resource takes. "
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


@mcp.tool(
    description=(
        "List the knowledge base's branches (one per Google Sheet tab) with "
        "resource and topic counts and their largest topics. Start here to "
        "see how the knowledge base is organised."
    )
)
def list_branches() -> str:
    """Overview of all branches."""
    g = _Graph(_load_graph())
    branches = sorted(g.of_type("branch"), key=lambda b: (-b.get("count", 0), b["label"]))
    if not branches:
        return "No branches in knowledge base."
    lines = [f"Branches ({len(branches)}):\n"]
    for b in branches:
        topics = sorted(g.children(b["id"], "HAS_TOPIC"), key=lambda t: -t.get("count", 0))
        top = ", ".join(t["label"] for t in topics[:5])
        lines.append(
            f"- **{b['label']}** (`{b['slug']}`) — {b.get('count', 0)} resources, "
            f"{len(topics)} topics{f' — top: {top}' if top else ''}"
        )
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Show one branch: every topic in it with its resources, plus resources "
        "filed directly under the branch. Accepts the branch slug or tab title "
        "(e.g. 'repos-in-github' or 'Repos in github')."
    )
)
def get_branch(branch: str) -> str:
    """Topics and resources of one branch."""
    branch = branch.strip()
    if not branch:
        return "Error: 'branch' cannot be empty."
    g = _Graph(_load_graph())
    b = g.find_branch(branch)
    if not b:
        names = ", ".join(sorted(n["slug"] for n in g.of_type("branch")))
        return f"Branch not found: '{branch}'. Branches: {names}"

    lines = [f"## {b['label']} (`{b['id']}`) — {b.get('count', 0)} resources\n"]
    topics = sorted(g.children(b["id"], "HAS_TOPIC"), key=lambda t: (-t.get("count", 0), t["label"]))
    for t in topics:
        lines.append(f"### {t['label']} (`{t['id']}`)")
        lines.extend(_node_line(r) for r in g.children(t["id"], "HAS_RESOURCE"))
        lines.append("")
    direct = g.children(b["id"], "HAS_RESOURCE")
    if direct:
        lines.append("### (no topic)")
        lines.extend(_node_line(r) for r in direct)
    if not topics and not direct:
        lines.append("This branch has no resources yet.")
    return "\n".join(lines).rstrip()


@mcp.tool(
    description=(
        "Find a topic by name across all branches (substring match). The same "
        "topic name can exist in several branches, e.g. 'agent framework' "
        "under both Tools and Repos in github."
    )
)
def find_topic(name: str) -> str:
    """Topics matching a name, grouped by branch."""
    q = name.strip().lower()
    if not q:
        return "Error: 'name' cannot be empty."
    g = _Graph(_load_graph())
    hits = [t for t in g.of_type("topic") if q in t["label"] or t["label"] in q]
    if not hits:
        return f"No topic matching '{name}'. Try list_branches or query_kb."
    hits.sort(key=lambda t: (-t.get("count", 0), t["id"]))
    lines = [f"Topics matching '{name}' ({len(hits)}):\n"]
    for t in hits:
        branch = g.nodes.get(t.get("branch", ""), {}).get("label", "?")
        lines.append(f"- **{t['label']}** in {branch} (`{t['id']}`) — {t.get('count', 0)} resources")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Return one graph node (branch, topic or resource) with all its "
        "outgoing and incoming edges and the nodes on the other end. Use the "
        "ids returned by the other branch tools, e.g. 'branch:tools', "
        "'topic:tools/agent-framework' or 'resource:12'."
    )
)
def get_node(node_id: str) -> str:
    """A node and its neighbourhood."""
    node_id = node_id.strip()
    g = _Graph(_load_graph())
    n = g.nodes.get(node_id)
    if not n:
        return (f"Node not found: '{node_id}'. Ids look like 'branch:<slug>', "
                "'topic:<branch>/<topic>' or 'resource:<id>'.")

    fields = {k: v for k, v in n.items() if k not in ("id", "type") and v not in ("", [], None)}
    lines = [f"## {n['label']}", f"id: {n['id']}", f"type: {n['type']}"]
    lines += [f"{k}: {', '.join(v) if isinstance(v, list) else v}"
              for k, v in fields.items() if k != "label"]
    out = g.out.get(node_id, [])
    if out:
        lines.append(f"\n### Outgoing ({len(out)})")
        lines += [f"- -[{e['type']}]-> {_node_line(g.nodes[e['target']])[2:]}"
                  for e in out if e["target"] in g.nodes]
    inc = g.inc.get(node_id, [])
    if inc:
        lines.append(f"\n### Incoming ({len(inc)})")
        lines += [f"- <-[{e['type']}]- {_node_line(g.nodes[e['source']])[2:]}"
                  for e in inc if e["source"] in g.nodes]
    return "\n".join(lines)


@mcp.tool(
    description=(
        "List every GitHub repository in the knowledge base (owner/repo, title, "
        "and the branch › topic it is filed under). Detected from the link, so "
        "it covers repos on any tab, not only 'Repos in github'. Optionally "
        "narrow to one branch (slug or tab title)."
    )
)
def list_github_repos(branch: str = "") -> str:
    """GitHub projects, optionally within one branch."""
    g = _Graph(_load_graph())
    scope = None
    if branch.strip():
        b = g.find_branch(branch)
        if not b:
            names = ", ".join(sorted(n["slug"] for n in g.of_type("branch")))
            return f"Branch not found: '{branch}'. Branches: {names}"
        scope = b["id"]

    def placements(rid: str) -> list[str]:
        out = []
        for e in g.inc.get(rid, []):
            parent = g.nodes.get(e["source"])
            if not parent:
                continue
            if parent["type"] == "topic":
                bid = parent["branch"]
                text = f"{g.nodes[bid]['label']} › {parent['label']}"
            else:
                bid, text = parent["id"], parent["label"]
            if scope is None or bid == scope:
                out.append(text)
        return out

    repos = []
    for n in g.of_type("resource"):
        repo = n.get("github_repo") or github_repo(n.get("url", ""))
        where = placements(n["id"]) if repo else []
        if repo and where:
            repos.append((repo.lower(), repo, n, where))
    if not repos:
        return "No GitHub repositories" + (f" in '{branch}'." if scope else ".")
    repos.sort(key=lambda t: (t[0], t[2]["id"]))
    where_label = f" in {g.nodes[scope]['label']}" if scope else ""
    lines = [f"GitHub repositories ({len(repos)}){where_label}:\n"]
    for _, repo, n, where in repos:
        lines.append(f"- **{repo}** — {n['label']} (`{n['id']}`) — {'; '.join(sorted(set(where)))}")
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
