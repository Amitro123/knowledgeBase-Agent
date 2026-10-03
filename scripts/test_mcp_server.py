#!/usr/bin/env python3
"""Tests for the MCP knowledge-base server (scripts/mcp_server.py)."""

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture: load the module with paths pointed at a temp dir
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
    (tmp_path / "wiki").mkdir()
    seed = [
        {
            "id": 1,
            "url": "https://example.com/alpha",
            "title": "Alpha Resource",
            "summary": "First resource about RAG",
            "category": "tool",
            "tags": ["rag", "vector-db"],
            "source_file": "",
            "created": "2026-01-01",
            "added_at": "2026-01-01",
            "notes": "Good overview",
        },
        {
            "id": 2,
            "url": "https://example.com/beta",
            "title": "Beta Resource",
            "summary": "Second resource about agents",
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
            "title": "",
            "summary": "",
            "category": "other",
            "tags": [],
            "source_file": "",
            "created": "",
            "added_at": "2026-03-01",
            "notes": "",
        },
    ]
    (tmp_path / "data" / "resources.json").write_text(
        json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mod.REPO_ROOT = tmp_path
    mod.RESOURCES_FILE = tmp_path / "data" / "resources.json"
    mod.INBOX_FILE = tmp_path / "data" / "inbox.jsonl"
    mod.LOG_FILE = tmp_path / "data" / "kb_log.jsonl"
    mod.WIKI_DIR = tmp_path / "wiki"

    return mod


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

class TestQuery:
    def test_text_search(self, kb):
        result = kb.query(text="RAG")
        assert "Alpha Resource" in result
        assert "Beta Resource" not in result

    def test_tag_filter(self, kb):
        result = kb.query(tag="agents")
        assert "Beta Resource" in result
        assert "Alpha Resource" not in result

    def test_category_filter(self, kb):
        result = kb.query(category="tool")
        assert "Alpha Resource" in result
        assert "Beta Resource" not in result

    def test_no_results(self, kb):
        result = kb.query(text="nonexistent-xyz")
        assert "No matching" in result

    def test_combined_filters(self, kb):
        result = kb.query(text="resource", category="research")
        assert "Beta Resource" in result
        assert "Alpha Resource" not in result


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_new_resource(self, kb):
        result = kb.ingest(
            url="https://example.com/new",
            title="New Thing",
            summary="A new resource",
            tags=["test"],
        )
        assert "Ingested" in result
        assert "id=4" in result
        resources = json.loads(kb.RESOURCES_FILE.read_text())
        assert any(r["url"] == "https://example.com/new" for r in resources)

    def test_duplicate_rejected(self, kb):
        result = kb.ingest(url="https://example.com/alpha")
        assert "Already exists" in result

    def test_empty_url_rejected(self, kb):
        result = kb.ingest(url="")
        assert "ERROR" in result

    def test_inbox_written(self, kb):
        kb.ingest(url="https://example.com/inbox-test", title="Inbox Test")
        assert kb.INBOX_FILE.exists()
        lines = kb.INBOX_FILE.read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["action"] == "ingest"
        assert record["entry"]["url"] == "https://example.com/inbox-test"


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

class TestLint:
    def test_finds_issues(self, kb):
        result = kb.lint()
        assert "issue" in result.lower()
        assert "id=3" in result

    def test_clean_kb(self, kb):
        clean = [
            {
                "id": 1,
                "url": "https://example.com/clean",
                "title": "Clean Resource",
                "summary": "Has everything",
                "category": "tool",
                "tags": ["test"],
                "source_file": "",
                "created": "2026-01-01",
                "added_at": "2026-01-01",
                "notes": "",
            }
        ]
        kb.RESOURCES_FILE.write_text(json.dumps(clean), encoding="utf-8")
        result = kb.lint()
        assert "No issues" in result


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

class TestIndex:
    def test_index_output(self, kb):
        result = kb.index()
        assert "3 resources" in result
        assert "tool" in result
        assert "rag" in result

    def test_empty_kb(self, kb):
        kb.RESOURCES_FILE.write_text("[]", encoding="utf-8")
        result = kb.index()
        assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# get_resource
# ---------------------------------------------------------------------------

class TestGetResource:
    def test_by_id(self, kb):
        result = kb.get_resource(id=1)
        data = json.loads(result)
        assert data["title"] == "Alpha Resource"

    def test_by_url(self, kb):
        result = kb.get_resource(url="https://example.com/beta")
        data = json.loads(result)
        assert data["id"] == 2

    def test_not_found(self, kb):
        result = kb.get_resource(id=999)
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# wiki articles
# ---------------------------------------------------------------------------

class TestWiki:
    def test_write_and_read(self, kb):
        kb.write_article("test-article", "# Test\nHello world")
        result = kb.read_article("test-article")
        assert "Hello world" in result

    def test_read_nonexistent(self, kb):
        result = kb.read_article("does-not-exist")
        assert "not found" in result.lower()

    def test_list_articles(self, kb):
        kb.write_article("first", "---\ntitle: First\n---\nContent")
        kb.write_article("second", "---\ntitle: Second\n---\nMore")
        result = kb.list_articles()
        assert "first" in result
        assert "second" in result

    def test_overwrite(self, kb):
        kb.write_article("ow", "version 1")
        kb.write_article("ow", "version 2")
        result = kb.read_article("ow")
        assert "version 2" in result
        assert "version 1" not in result

    def test_slug_sanitisation(self, kb):
        result = kb.write_article("../../etc/passwd", "nope")
        assert "etc-passwd" in result


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

class TestLog:
    def test_log_after_actions(self, kb):
        kb.query(text="x")
        kb.index()
        result = kb.log()
        assert "query" in result
        assert "index" in result

    def test_empty_log(self, kb):
        result = kb.log()
        assert "No activity" in result or "empty" in result.lower()
