#!/usr/bin/env python3
"""Tests for the read-only MCP knowledge-base server (scripts/mcp_server.py)."""

import importlib.util
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture: load the module with RESOURCES_FILE pointed at a temp dir
# ---------------------------------------------------------------------------

@pytest.fixture()
def kb(tmp_path):
    """Return the mcp_server module wired to a disposable temp directory."""
    spec = importlib.util.spec_from_file_location(
        f"mcp_server_{id(tmp_path)}",
        str(Path(__file__).resolve().parent / "mcp_server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_path / "data").mkdir()
    seed = [
        {
            "id": 1,
            "url": "https://example.com/alpha",
            "title": "Alpha Resource about RAG",
            "summary": "First resource about retrieval augmented generation",
            "category": "tool",
            "tags": ["rag", "vector-db"],
            "source_file": "",
            "created": "2026-01-01",
            "added_at": "2026-01-01",
            "notes": "Good overview of RAG techniques",
        },
        {
            "id": 2,
            "url": "https://example.com/beta",
            "title": "Beta Agent Framework",
            "summary": "Second resource about building agents",
            "category": "research",
            "tags": ["agents", "llm"],
            "source_file": "",
            "created": "2026-02-15",
            "added_at": "2026-02-15",
            "notes": "",
        },
        {
            "id": 3,
            "url": "https://example.com/gamma",
            "title": "Gamma MCP Guide",
            "summary": "Model Context Protocol tutorial in Hebrew",
            "category": "tutorial",
            "tags": ["mcp", "agents"],
            "source_file": "",
            "created": "2026-03-01",
            "added_at": "2026-03-01",
            "notes": "מדריך מקיף בעברית",
        },
        {
            "id": 4,
            "url": "https://example.com/delta",
            "title": "Delta Vector DB",
            "summary": "Vector database comparison",
            "category": "tool",
            "tags": ["vector-db", "rag"],
            "source_file": "",
            "created": "2026-04-01",
            "added_at": "2026-04-01",
            "notes": "",
        },
    ]
    (tmp_path / "data" / "resources.json").write_text(
        json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mod.ROOT = tmp_path
    mod.RESOURCES_FILE = tmp_path / "data" / "resources.json"
    mod.GRAPH_FILE = tmp_path / "data" / "graph.json"

    return mod


# ---------------------------------------------------------------------------
# query_kb
# ---------------------------------------------------------------------------

class TestQueryKb:
    def test_text_search(self, kb):
        result = kb.query_kb(question="RAG")
        assert "Alpha Resource" in result
        assert "id=1" in result

    def test_hebrew_search(self, kb):
        result = kb.query_kb(question="עברית")
        assert "Gamma" in result

    def test_no_results(self, kb):
        result = kb.query_kb(question="nonexistent-xyz-topic")
        assert "No resources found" in result

    def test_empty_question(self, kb):
        result = kb.query_kb(question="")
        assert "Error" in result

    def test_stop_words_only(self, kb):
        result = kb.query_kb(question="the is of")
        assert "stop words" in result

    def test_top_match_full_detail(self, kb):
        result = kb.query_kb(question="RAG retrieval")
        assert "Top match" in result
        assert "url:" in result
        assert "category:" in result

    def test_bidirectional_match(self, kb):
        """A query keyword containing a tag word (or vice-versa) should match."""
        result = kb.query_kb(question="vector-databases")
        assert "vector-db" in result or "Vector" in result

    def test_max_results(self, kb):
        result = kb.query_kb(question="resource", max_results=2)
        assert result.count("**id=") <= 2


# ---------------------------------------------------------------------------
# get_resource
# ---------------------------------------------------------------------------

class TestGetResource:
    def test_by_id(self, kb):
        result = kb.get_resource(resource_id=1)
        assert "Alpha Resource" in result
        assert "url: https://example.com/alpha" in result

    def test_not_found(self, kb):
        result = kb.get_resource(resource_id=999)
        assert "not found" in result.lower()

    def test_nearby_hint(self, kb):
        result = kb.get_resource(resource_id=5)
        assert "Nearby" in result or "not found" in result.lower()

    def test_full_detail_fields(self, kb):
        result = kb.get_resource(resource_id=1)
        assert "title:" in result
        assert "url:" in result
        assert "category:" in result
        assert "tags:" in result
        assert "summary:" in result


# ---------------------------------------------------------------------------
# search_tags
# ---------------------------------------------------------------------------

class TestSearchTags:
    def test_search_hit(self, kb):
        result = kb.search_tags(question="rag")
        assert "rag" in result.lower()

    def test_resource_count(self, kb):
        result = kb.search_tags(question="agents")
        assert "2 resources" in result

    def test_no_match(self, kb):
        result = kb.search_tags(question="nonexistent-xyz")
        assert "No tags found" in result

    def test_empty_question(self, kb):
        result = kb.search_tags(question="")
        assert "Error" in result

    def test_bidirectional(self, kb):
        """'vector' should match tag 'vector-db' via substring."""
        result = kb.search_tags(question="vector")
        assert "vector-db" in result


# ---------------------------------------------------------------------------
# get_tag
# ---------------------------------------------------------------------------

class TestGetTag:
    def test_exact_tag(self, kb):
        result = kb.get_tag(tag="rag")
        assert "Alpha Resource" in result
        assert "Delta Vector" in result

    def test_tag_not_found(self, kb):
        result = kb.get_tag(tag="nonexistent")
        assert "No resources found" in result

    def test_similar_hint(self, kb):
        result = kb.get_tag(tag="agent")
        assert "Similar tags" in result or "agents" in result.lower()

    def test_empty_tag(self, kb):
        result = kb.get_tag(tag="")
        assert "Error" in result

    def test_case_insensitive(self, kb):
        result = kb.get_tag(tag="RAG")
        assert "Alpha Resource" in result


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_no_write_methods(self, kb):
        """The server should not expose any mutation tools."""
        tool_names = {name for name in dir(kb) if not name.startswith("_")}
        for forbidden in ["ingest", "write_article", "lint", "log",
                          "read_article", "list_articles"]:
            assert forbidden not in tool_names, (
                f"Write tool '{forbidden}' should not exist"
            )

    def test_resources_unchanged_after_query(self, kb):
        """Querying must never modify resources.json."""
        before = kb.RESOURCES_FILE.read_text()
        kb.query_kb(question="RAG")
        kb.get_resource(resource_id=1)
        kb.search_tags(question="agents")
        kb.get_tag(tag="rag")
        after = kb.RESOURCES_FILE.read_text()
        assert before == after


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_kb(self, kb):
        kb.RESOURCES_FILE.write_text("[]", encoding="utf-8")
        result = kb.query_kb(question="anything")
        assert "No resources found" in result

    def test_empty_kb_tags(self, kb):
        kb.RESOURCES_FILE.write_text("[]", encoding="utf-8")
        result = kb.search_tags(question="anything")
        assert "No tags" in result

    def test_missing_file(self, kb):
        kb.RESOURCES_FILE.unlink()
        result = kb.query_kb(question="anything")
        assert "No resources found" in result


# ---------------------------------------------------------------------------
# Graph tools (branches / topics / nodes)
# ---------------------------------------------------------------------------

@pytest.fixture()
def kb_graph(kb):
    """kb with a graph.json written from explicit placements."""
    resources = json.loads(kb.RESOURCES_FILE.read_text(encoding="utf-8"))
    placements = {
        1: [{"branch": "rag", "topic": "RAG Tutorial"}],
        2: [{"branch": "tools", "topic": "Agent Framework"},
            {"branch": "repos-in-github", "topic": "Agent Framework"}],
        3: [{"branch": "mcp", "topic": None}],
        4: [{"branch": "rag", "topic": "Vector Database"}],
    }
    for r in resources:
        r["placements"] = placements[r["id"]]
    graph = kb.build_graph(resources, {"rag": "RAG", "tools": "Tools", "mcp": "MCP",
                                       "repos-in-github": "Repos in github",
                                       "observability": "Observability"})
    kb.GRAPH_FILE.write_text(json.dumps(graph), encoding="utf-8")
    return kb


class TestGraphTools:
    def test_list_branches(self, kb_graph):
        result = kb_graph.list_branches()
        assert "Branches (5)" in result
        assert "**RAG** (`rag`) — 2 resources, 2 topics" in result
        assert "Observability" in result

    def test_get_branch_by_title_or_slug(self, kb_graph):
        for query in ("Repos in github", "repos-in-github"):
            result = kb_graph.get_branch(branch=query)
            assert "## Repos in github" in result
            assert "Beta Agent Framework" in result

    def test_get_branch_lists_topics_and_direct_resources(self, kb_graph):
        assert "### rag tutorial" in kb_graph.get_branch(branch="rag")
        mcp = kb_graph.get_branch(branch="mcp")
        assert "### (no topic)" in mcp and "Gamma MCP Guide" in mcp

    def test_get_branch_empty_and_unknown(self, kb_graph):
        assert "no resources yet" in kb_graph.get_branch(branch="observability")
        result = kb_graph.get_branch(branch="nope")
        assert "Branch not found" in result and "tools" in result
        assert "Error" in kb_graph.get_branch(branch=" ")

    def test_find_topic_across_branches(self, kb_graph):
        result = kb_graph.find_topic(name="agent framework")
        assert "(2)" in result
        assert "in Tools" in result and "in Repos in github" in result
        assert "No topic" in kb_graph.find_topic(name="zzz")

    def test_get_node_walks_edges(self, kb_graph):
        result = kb_graph.get_node(node_id="resource:2")
        assert "Incoming (2)" in result
        assert "topic:tools/agent-framework" in result
        branch = kb_graph.get_node(node_id="branch:rag")
        assert "-[HAS_TOPIC]->" in branch
        assert "Node not found" in kb_graph.get_node(node_id="resource:999")

    def test_builds_graph_when_graph_json_missing(self, kb):
        assert not kb.GRAPH_FILE.exists()
        assert "Branches" in kb.list_branches()

    def test_list_github_repos(self, kb):
        resources = json.loads(kb.RESOURCES_FILE.read_text(encoding="utf-8"))
        resources[0]["url"] = "https://github.com/acme/alpha"
        resources[1]["url"] = "https://github.com/acme/beta/tree/main"
        for r in resources:
            r["placements"] = [{"branch": "tools" if r["id"] == 1 else "rag", "topic": "Agent Framework" if r["id"] == 1 else None}]
        kb.GRAPH_FILE.write_text(json.dumps(kb.build_graph(resources, {"tools": "Tools", "rag": "RAG"})), encoding="utf-8")
        result = kb.list_github_repos()
        assert "GitHub repositories (2)" in result
        assert "acme/alpha" in result and "Tools › agent framework" in result
        assert "acme/beta" in result
        assert "example.com" not in result
        scoped = kb.list_github_repos(branch="RAG")
        assert "(1) in RAG" in scoped and "acme/beta" in scoped and "acme/alpha" not in scoped
        assert "Branch not found" in kb.list_github_repos(branch="nope")

    def test_graph_tools_do_not_write(self, kb_graph):
        before = (kb_graph.RESOURCES_FILE.read_text(), kb_graph.GRAPH_FILE.read_text())
        kb_graph.list_branches()
        kb_graph.get_branch(branch="rag")
        kb_graph.find_topic(name="rag")
        kb_graph.get_node(node_id="branch:rag")
        kb_graph.list_github_repos()
        assert before == (kb_graph.RESOURCES_FILE.read_text(), kb_graph.GRAPH_FILE.read_text())
