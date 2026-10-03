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
