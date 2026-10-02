#!/usr/bin/env python3
"""Unit tests for sync_sheets.py mapping / dedup logic (no API calls)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sync_sheets import (
    normalise_url,
    parse_date,
    earlier,
    normalise_category,
    tab_to_tag,
    rows_to_entries,
    merge_entries,
    build_resources,
)


# ── normalise_url ───────────────────────────────────────────────────────────

def test_normalise_url_strips_fragment_and_trailing_slash():
    assert normalise_url("https://Example.COM/path/#frag") == "https://example.com/path"

def test_normalise_url_empty():
    assert normalise_url("") == ""
    assert normalise_url("   ") == ""

def test_normalise_url_preserves_query():
    assert normalise_url("https://x.com/p?q=1") == "https://x.com/p?q=1"


# ── parse_date ──────────────────────────────────────────────────────────────

def test_parse_date_iso():
    assert parse_date("2026-01-15") == "2026-01-15"

def test_parse_date_slash():
    assert parse_date("15/01/2026") == "2026-01-15"

def test_parse_date_empty():
    assert parse_date("") == ""

def test_parse_date_garbage():
    assert parse_date("no date here") == ""


# ── earlier ─────────────────────────────────────────────────────────────────

def test_earlier():
    assert earlier("2025-01-01", "2026-06-01") == "2025-01-01"
    assert earlier("", "2026-06-01") == "2026-06-01"
    assert earlier("2025-01-01", "") == "2025-01-01"


# ── normalise_category ─────────────────────────────────────────────────────

def test_normalise_category():
    assert normalise_category("Tool") == "tool"
    assert normalise_category("TOOLS") == "tool"
    assert normalise_category("tutorial") == "tutorial"
    assert normalise_category("bananas") == "other"


# ── tab_to_tag ──────────────────────────────────────────────────────────────

def test_tab_to_tag():
    assert tab_to_tag("AI Solutions-linkedin") == "ai-solutions-linkedin"
    assert tab_to_tag("Repos in github") == "repos-in-github"
    assert tab_to_tag("MCP") == "mcp"


# ── rows_to_entries ─────────────────────────────────────────────────────────

def test_rows_to_entries_basic():
    rows = [
        ["Date", "Link", "Name/Author", "Function/Summary", "Category", "Review/Notes"],
        ["2026-01-01", "https://example.com", "Example", "A summary", "tool", "Great resource"],
        ["", "https://other.com", "Other", "Another", "", ""],
    ]
    entries = rows_to_entries("Learning", rows)
    assert len(entries) == 2
    assert entries[0]["url"] == "https://example.com"
    assert entries[0]["title"] == "Example"
    assert entries[0]["summary"] == "A summary"
    assert entries[0]["category"] == "tool"
    assert entries[0]["notes"] == "Great resource"
    assert "learning" in entries[0]["tags"]
    assert entries[1]["category"] == "other"

def test_rows_to_entries_skips_empty_link():
    rows = [
        ["Date", "Link", "Name/Author", "Function/Summary", "Category", "Review/Notes"],
        ["2026-01-01", "", "No link", "Nothing", "tool", ""],
    ]
    entries = rows_to_entries("RAG", rows)
    assert len(entries) == 0

def test_rows_to_entries_empty_sheet():
    entries = rows_to_entries("Empty", [])
    assert entries == []

    entries2 = rows_to_entries("HeaderOnly", [["Date", "Link"]])
    assert entries2 == []


# ── merge_entries ───────────────────────────────────────────────────────────

def test_merge_dedup_by_url():
    entries = [
        {"url": "https://a.com/", "_norm": "https://a.com", "title": "A",
         "summary": "Sum", "category": "tool", "tags": ["learning"],
         "created": "2026-01-01", "notes": "Note A"},
        {"url": "https://A.COM", "_norm": "https://a.com", "title": "A dup",
         "summary": "", "category": "other", "tags": ["rag"],
         "created": "2025-06-01", "notes": ""},
    ]
    merged = merge_entries(entries)
    assert len(merged) == 1
    assert set(merged[0]["tags"]) == {"learning", "rag"}
    assert merged[0]["created"] == "2025-06-01"  # earlier wins
    assert merged[0]["notes"] == "Note A"


# ── build_resources ─────────────────────────────────────────────────────────

def test_build_resources_ids_and_shape():
    merged = [
        {"url": "https://a.com", "_norm": "https://a.com", "title": "A",
         "summary": "S", "category": "tool", "tags": ["t1"],
         "created": "2026-01-01", "notes": "N"},
    ]
    resources = build_resources(merged)
    assert len(resources) == 1
    r = resources[0]
    assert r["id"] == 1
    assert r["url"] == "https://a.com"
    assert r["notes"] == "N"
    assert "source_file" in r
    assert "_norm" not in r


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
