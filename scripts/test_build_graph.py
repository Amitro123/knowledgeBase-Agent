#!/usr/bin/env python3
"""Unit tests for build_graph.py (resources.json -> graph.json)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_graph import build_graph, normalise_topic, placements_of, slugify
from sync_sheets import build_resources, merge_entries, rows_to_entries

HEADER = ["Date", "Link", "Name/Author", "Function/Summary", "Category", "Review/Notes"]


def _ids(graph, kind):
    return {n["id"] for n in graph["nodes"] if n["type"] == kind}


def _edges(graph, kind):
    return {(e["source"], e["target"]) for e in graph["edges"] if e["type"] == kind}


# ── helpers ─────────────────────────────────────────────────────────────────

def test_slugify():
    assert slugify("Repos in github") == "repos-in-github"
    assert slugify("  ML / Tabular ") == "ml-tabular"


def test_normalise_topic_drops_empty_other_and_branch_echo():
    assert normalise_topic("", "tools") is None
    assert normalise_topic("Other", "tools") is None
    assert normalise_topic("Learning", "learning") is None
    assert normalise_topic("  Agent   Framework ", "tools") == "agent framework"


def test_placements_prefer_explicit_field():
    r = {"tags": ["zzz"], "placements": [{"branch": "Tools", "topic": "Web Framework"}]}
    assert placements_of(r) == [{"branch": "tools", "topic": "web framework"}]


def test_legacy_placements_use_known_branches():
    # merge_entries sorts tags, so the tab is not necessarily first
    r = {"tags": ["agent framework", "repos-in-github", "tools"]}
    got = placements_of(r, {"repos-in-github", "tools"})
    assert {"branch": "repos-in-github", "topic": "agent framework"} in got
    assert {"branch": "tools", "topic": None} in got


def test_legacy_placements_without_known_branches():
    assert placements_of({"tags": ["rag", "rag tutorial"]}) == [
        {"branch": "rag", "topic": "rag tutorial"}]
    assert placements_of({"tags": []}) == [{"branch": "unsorted", "topic": None}]


# ── graph shape ─────────────────────────────────────────────────────────────

def _resources():
    return [
        {"id": 1, "title": "A", "url": "https://a", "placements": [
            {"branch": "tools", "topic": "Agent Framework"}]},
        {"id": 2, "title": "B", "url": "https://b", "placements": [
            {"branch": "tools", "topic": "agent framework"},
            {"branch": "repos-in-github", "topic": "Agent Framework"}]},
        {"id": 3, "title": "C", "url": "https://c", "placements": [
            {"branch": "learning", "topic": "Learning"}]},
    ]


def test_branch_topic_resource_hierarchy():
    g = build_graph(_resources(), {"tools": "Tools", "repos-in-github": "Repos in github",
                                   "learning": "Learning", "observability": "Observability"})
    assert _ids(g, "branch") == {"branch:tools", "branch:repos-in-github",
                                 "branch:learning", "branch:observability"}
    # topics are scoped to their branch
    assert _ids(g, "topic") == {"topic:tools/agent-framework",
                                "topic:repos-in-github/agent-framework"}
    assert ("branch:tools", "topic:tools/agent-framework") in _edges(g, "HAS_TOPIC")
    assert ("topic:tools/agent-framework", "resource:2") in _edges(g, "HAS_RESOURCE")
    # topic equal to branch name -> resource hangs off the branch directly
    assert ("branch:learning", "resource:3") in _edges(g, "HAS_RESOURCE")
    # a resource on two tabs links both branches
    sources = {s for s, t in _edges(g, "HAS_RESOURCE") if t == "resource:2"}
    assert sources == {"topic:tools/agent-framework", "topic:repos-in-github/agent-framework"}


def test_counts_labels_and_empty_branches():
    g = build_graph(_resources(), {"tools": "Tools", "observability": "Observability"})
    nodes = {n["id"]: n for n in g["nodes"]}
    assert nodes["branch:tools"]["label"] == "Tools"
    assert nodes["branch:tools"]["count"] == 2
    assert nodes["branch:tools"]["topic_count"] == 1
    assert nodes["topic:tools/agent-framework"]["count"] == 2
    assert nodes["branch:observability"]["count"] == 0
    # unlabelled branch gets a readable fallback
    assert nodes["branch:repos-in-github"]["label"] == "Repos in github"
    assert nodes["resource:2"]["branches"] == ["repos-in-github", "tools"]


def test_no_duplicate_edges_and_valid_endpoints():
    res = _resources() + [{"id": 4, "title": "D", "url": "https://d", "placements": [
        {"branch": "tools", "topic": "agent framework"},
        {"branch": "tools", "topic": "Agent Framework"}]}]
    g = build_graph(res)
    keys = [(e["source"], e["target"], e["type"]) for e in g["edges"]]
    assert len(keys) == len(set(keys))
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


# ── sync integration ────────────────────────────────────────────────────────

def test_sync_records_placements_across_tabs():
    tools = rows_to_entries("Tools", [HEADER, ["", "https://x.dev", "X", "", "Agent Framework", ""]])
    repos = rows_to_entries("Repos in github", [HEADER, ["", "https://x.dev/", "X", "", "Data Parsing", ""]])
    resources = build_resources(merge_entries(tools + repos))
    assert len(resources) == 1
    assert resources[0]["placements"] == [
        {"branch": "tools", "topic": "Agent Framework"},
        {"branch": "repos-in-github", "topic": "Data Parsing"},
    ]
    g = build_graph(resources, {"tools": "Tools", "repos-in-github": "Repos in github"})
    assert _ids(g, "topic") == {"topic:tools/agent-framework", "topic:repos-in-github/data-parsing"}


def test_sync_does_not_repeat_tab_as_category_tag():
    entries = rows_to_entries("Learning", [HEADER, ["", "https://l.dev", "L", "", "Learning", ""]])
    assert entries[0]["tags"] == ["learning"]
