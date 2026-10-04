#!/usr/bin/env python3
"""
build_graph.py — Turn data/resources.json into a typed graph, data/graph.json.

The graph is the shared model for the web viewer (index.html) and the MCP
server, so a person browsing the page and an agent calling tools navigate the
same structure.

Model (mirrors how the Google Sheet is organised):

    (Branch)   one per sheet tab                      e.g. "Repos in GitHub"
    (Topic)    the row's Category text, scoped to its branch
    (Resource) one per URL

    (Branch)-[:HAS_TOPIC]->(Topic)
    (Topic)-[:HAS_RESOURCE]->(Resource)
    (Branch)-[:HAS_RESOURCE]->(Resource)   rows with no Category

A resource that sits on several tabs gets one edge per placement, which is
what links branches to each other.  Topics are scoped to their branch on
purpose: generic Category values ("tool") appear on many tabs, and joining
them would tie every branch to every other one.

Resources written by sync_sheets.py carry exact `placements`
([{"branch": slug, "topic": text|null}, ...]).  Older files (and rows added
by capture.py) only have `tags`; for those, tags matching a known tab are
branches and the rest are topics of the first branch.  Without a tab list the
first tag is taken as the branch.

Usage:
    python scripts/build_graph.py            # resources.json -> graph.json
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_FILE = REPO_ROOT / "data" / "resources.json"
GRAPH_FILE = REPO_ROOT / "data" / "graph.json"

SCHEMA_VERSION = 1

# Category values that carry no topic information
_EMPTY_TOPICS = {"", "other", "misc", "-", "n/a"}


def slugify(text: str) -> str:
    """Lowercase slug with runs of whitespace, '/' and '_' collapsed to '-'."""
    return re.sub(r"[\s/_]+", "-", text.strip().lower()).strip("-")


def normalise_topic(raw: str | None, branch: str) -> str | None:
    """Clean a Category cell into a topic label, or None if it adds nothing.

    A topic equal to its own branch (tab "Learning", Category "learning")
    is dropped: it would only repeat the branch.
    """
    if not raw:
        return None
    topic = re.sub(r"\s+", " ", raw.strip().lower())
    if topic in _EMPTY_TOPICS or slugify(topic) == slugify(branch):
        return None
    return topic


def humanise(slug: str) -> str:
    """Fallback display label for a branch slug: 'repos-in-github' -> 'Repos in github'."""
    text = slug.replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else slug


def placements_of(resource: dict, known_branches: set[str] | None = None) -> list[dict]:
    """Return [{"branch": slug, "topic": str|None}, ...] for a resource."""
    if resource.get("placements"):
        out = []
        for p in resource["placements"]:
            branch = slugify(p.get("branch") or "")
            if branch:
                out.append({"branch": branch,
                            "topic": normalise_topic(p.get("topic"), branch)})
        if out:
            return out

    # Legacy fallback: tags = tab slugs + Category texts, possibly sorted
    tags = [str(t) for t in (resource.get("tags") or []) if str(t).strip()]
    if not tags:
        return [{"branch": "unsorted", "topic": None}]
    if known_branches:
        branches = [slugify(t) for t in tags if slugify(t) in known_branches]
        rest = [t for t in tags if slugify(t) not in known_branches]
    else:
        branches, rest = [], tags
    if not branches:
        branches, rest = [slugify(rest[0])], rest[1:]
    topics = []
    for t in rest:
        topic = normalise_topic(t, branches[0])
        if topic and topic not in topics:
            topics.append(topic)
    out = [{"branch": branches[0], "topic": t} for t in topics] or [{"branch": branches[0], "topic": None}]
    out += [{"branch": b, "topic": None} for b in branches[1:]]
    return out


def _dedupe(placements: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in placements:
        key = (p["branch"], p["topic"])
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def build_graph(resources: list[dict],
                branch_labels: dict[str, str] | None = None,
                generated_at: str | None = None) -> dict:
    """Build the graph dict.  `branch_labels` maps branch slug -> tab title."""
    branch_labels = {slugify(k): v for k, v in (branch_labels or {}).items()}
    known = set(branch_labels) or None

    nodes: dict[str, dict] = {}

    def add_branch(slug: str) -> str:
        bid = f"branch:{slug}"
        if bid not in nodes:
            nodes[bid] = {
                "id": bid,
                "type": "branch",
                "label": branch_labels.get(slug) or humanise(slug),
                "slug": slug,
            }
        return bid

    # Every tab is a branch, including ones with no rows yet
    for slug in branch_labels:
        add_branch(slug)
    edges: list[dict] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, rel: str) -> None:
        key = (source, target, rel)
        if key not in edge_keys:
            edge_keys.add(key)
            edges.append({"source": source, "target": target, "type": rel})

    for r in resources:
        rid = f"resource:{r.get('id')}"
        placements = _dedupe(placements_of(r, known))
        nodes[rid] = {
            "id": rid,
            "type": "resource",
            "label": r.get("title") or r.get("url") or rid,
            "url": r.get("url", ""),
            "summary": r.get("summary", ""),
            "notes": r.get("notes", ""),
            "added_at": r.get("added_at", ""),
            "branches": sorted({p["branch"] for p in placements}),
            "topics": sorted({p["topic"] for p in placements if p["topic"]}),
        }

        for p in placements:
            bid = add_branch(p["branch"])
            if p["topic"]:
                tid = f"topic:{p['branch']}/{slugify(p['topic'])}"
                if tid not in nodes:
                    nodes[tid] = {
                        "id": tid,
                        "type": "topic",
                        "label": p["topic"],
                        "branch": bid,
                    }
                add_edge(bid, tid, "HAS_TOPIC")
                add_edge(tid, rid, "HAS_RESOURCE")
            else:
                add_edge(bid, rid, "HAS_RESOURCE")

    # Resource counts: distinct resources reachable under each hub
    under: dict[str, set[str]] = {}
    for e in edges:
        if e["type"] == "HAS_RESOURCE":
            under.setdefault(e["source"], set()).add(e["target"])
    for n in nodes.values():
        if n["type"] == "topic":
            n["count"] = len(under.get(n["id"], ()))
    for n in nodes.values():
        if n["type"] == "branch":
            res = set(under.get(n["id"], ()))
            topics = [e["target"] for e in edges
                      if e["source"] == n["id"] and e["type"] == "HAS_TOPIC"]
            for t in topics:
                res |= under.get(t, set())
            n["count"] = len(res)
            n["topic_count"] = len(topics)

    order = {"branch": 0, "topic": 1, "resource": 2}
    node_list = sorted(nodes.values(),
                       key=lambda n: (order[n["type"]], -n.get("count", 0), n["id"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.datetime.now(datetime.timezone.utc)
                                         .isoformat(timespec="seconds"),
        "node_types": ["branch", "topic", "resource"],
        "edge_types": ["HAS_TOPIC", "HAS_RESOURCE"],
        "nodes": node_list,
        "edges": edges,
    }


def write_graph(resources: list[dict], path: Path = GRAPH_FILE,
                branch_labels: dict[str, str] | None = None) -> dict:
    graph = build_graph(resources, branch_labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    return graph


def main() -> None:
    if not RESOURCES_FILE.exists():
        print(f"ERROR: {RESOURCES_FILE} not found", file=sys.stderr)
        sys.exit(1)
    resources = json.loads(RESOURCES_FILE.read_text(encoding="utf-8"))
    # Offline rebuilds have no access to the Sheet; keep the tab list and
    # titles from the last sync so branches stay recognisable.
    labels = {}
    if GRAPH_FILE.exists():
        previous = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        labels = {n["slug"]: n["label"] for n in previous.get("nodes", [])
                  if n.get("type") == "branch" and n.get("slug")}
    graph = write_graph(resources, branch_labels=labels)
    counts = {t: sum(1 for n in graph["nodes"] if n["type"] == t) for t in graph["node_types"]}
    print(f"Wrote {GRAPH_FILE}: {counts}, {len(graph['edges'])} edges")


if __name__ == "__main__":
    main()
