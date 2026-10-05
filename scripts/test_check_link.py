#!/usr/bin/env python3
"""Unit tests for check_link.py (pre-flight duplicate / cleaning check)."""

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_link
from check_link import build_index, check, clean_url, warnings_for
from sync_sheets import normalise_url

GRAPH = {
    "generated_at": "2026-10-04T10:00:00Z",
    "nodes": [
        {"id": "branch:mcp", "type": "branch", "slug": "mcp", "label": "MCP"},
        {"id": "branch:memory", "type": "branch", "slug": "memory", "label": "Memory"},
        {"id": "branch:observability", "type": "branch", "slug": "observability",
         "label": "Observability"},
    ],
}
RESOURCES = [
    {"id": 1, "title": "getzep / graphiti", "url": "https://github.com/getzep/graphiti",
     "added_at": "2026-05-01", "placements": [
         {"branch": "mcp", "topic": "MCP Servers"},
         {"branch": "memory", "topic": "Agent Memory"}]},
    {"id": 2, "title": "Mem article", "url": "https://blog.dev/mem?id=7",
     "added_at": "2026-06-01", "placements": [{"branch": "memory", "topic": "agent memory"}]},
    {"id": 3, "title": "Ref", "url": "https://ref.dev",
     "placements": [{"branch": "memory", "topic": "Reference"}]},
]


# ── cleaning ────────────────────────────────────────────────────────────────

def test_github_collapses_to_repo_root():
    for raw in ("https://github.com/getzep/graphiti/",
                "github.com/getzep/graphiti.git",
                "https://www.github.com/getzep/graphiti#readme",
                "https://github.com/getzep/graphiti/tree/main?utm_source=x",
                "https://github.com/getzep/graphiti/issues/12"):
        assert clean_url(raw) == "https://github.com/getzep/graphiti", raw


def test_github_file_and_folder_deep_links_are_kept():
    assert clean_url("https://github.com/o/r/tree/main/docs/") == "https://github.com/o/r/tree/main/docs"
    assert clean_url("https://github.com/o/r/blob/main/README.md#x") == \
        "https://github.com/o/r/blob/main/README.md"


def test_arxiv_pdf_becomes_abstract():
    assert clean_url("https://arxiv.org/pdf/2501.01234v2.pdf") == "https://arxiv.org/abs/2501.01234"
    assert clean_url("arxiv.org/pdf/2501.01234") == "https://arxiv.org/abs/2501.01234"


def test_tracking_params_removed_content_params_kept():
    got = clean_url("https://YouTube.com/watch?v=abc&utm_medium=s&si=zz&t=30#c")
    assert got == "https://youtube.com/watch?v=abc&t=30"
    assert clean_url("https://x.dev/p/?ref=hn&fbclid=1") == "https://x.dev/p"


def test_clean_url_empty():
    assert clean_url("") == "" and clean_url("   ") == ""


def test_fallback_normaliser_matches_sync():
    src = inspect.getsource(check_link)
    assert "def normalise_url" in src  # fallback exists
    ns = {}
    start = src.index("    def normalise_url")
    end = src.index("from build_graph")
    exec("from urllib.parse import urlsplit, urlunsplit\n"
         + inspect.cleandoc("\n" + src[start:end]), ns)
    for url in ("https://A.dev/x/?q=1#f", "http://b.dev", "", "  https://c.dev/  "):
        assert ns["normalise_url"](url) == normalise_url(url)


# ── warnings ────────────────────────────────────────────────────────────────

def test_warnings():
    def kinds(u):
        return {w.split(":")[0] for w in warnings_for(u)}
    assert kinds("https://drive.google.com/file/d/1") == {"google-drive-link"}
    assert kinds("https://share.google/abc") == {"google-drive-link", "short-link"}
    assert kinds("http://localhost:8080/x") == {"internal-host"}
    assert kinds("https://s3.dev/f?X-Amz-Signature=1") == {"secret-param"}
    assert kinds("https://app.dev/invite/abc") == {"personal-link"}
    assert kinds("https://github.com/o/r") == set()


# ── duplicates and topics ───────────────────────────────────────────────────

def test_duplicate_found_in_every_tab_after_cleaning():
    out = check(["https://github.com/getzep/graphiti/tree/main?utm_source=x#readme"],
                RESOURCES, GRAPH, network=False)
    r = out["results"][0]
    assert r["clean_url"] == "https://github.com/getzep/graphiti"
    assert r["changed"] and r["github_repo"] == "getzep/graphiti"
    assert {(d["tab"], d["category"]) for d in r["duplicate"]} == {
        ("MCP", "MCP Servers"), ("Memory", "Agent Memory")}
    assert out["source"] == "snapshot"
    assert out["snapshot_generated_at"] == "2026-10-04T10:00:00Z"


def test_query_selecting_content_is_not_a_duplicate():
    out = check(["https://blog.dev/mem?id=8", "https://blog.dev/mem/?id=7&utm_x=1"],
                RESOURCES, GRAPH, network=False)
    assert out["results"][0]["duplicate"] == []
    assert out["results"][1]["duplicate"][0]["title"] == "Mem article"


def test_live_rows_are_merged():
    live = [{"tab": "Observability", "link": "https://langfuse.com/", "category": "Tracing",
             "name": "Langfuse", "date": "2026-10-04"}]
    out = check(["langfuse.com"], RESOURCES, GRAPH, live, network=False)
    assert out["source"] == "snapshot+live"
    assert out["results"][0]["duplicate"] == [{
        "tab": "Observability", "category": "Tracing", "title": "Langfuse",
        "date": "2026-10-04", "source": "live"}]
    assert out["topics_by_tab"]["Observability"] == [{"topic": "Tracing", "count": 1}]


def test_topics_by_tab_merges_spellings_and_lists_empty_tabs():
    _, topics, _ = build_index(RESOURCES, GRAPH)
    assert topics["Observability"] == []
    assert topics["Memory"] == [{"topic": "Agent Memory", "count": 2},
                                {"topic": "Reference", "count": 1}]
    assert topics["MCP"] == [{"topic": "MCP Servers", "count": 1}]


def test_short_link_resolution_is_used(monkeypatch):
    monkeypatch.setattr(check_link, "resolve_short_link",
                        lambda u: "https://github.com/getzep/graphiti?utm_source=li")
    r = check(["https://lnkd.in/abc"], RESOURCES, GRAPH)["results"][0]
    assert r["resolved_from_short_link"]
    assert r["clean_url"] == "https://github.com/getzep/graphiti"
    assert r["warnings"] == [] and len(r["duplicate"]) == 2


def test_cli_with_rows_file(tmp_path, capsys, monkeypatch):
    res, graph = tmp_path / "resources.json", tmp_path / "graph.json"
    res.write_text(json.dumps(RESOURCES))
    graph.write_text(json.dumps(GRAPH))
    monkeypatch.setattr(check_link, "RESOURCES_FILE", res)
    monkeypatch.setattr(check_link, "GRAPH_FILE", graph)
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"tab": "MCP", "link": "https://new.dev"}]))
    assert check_link.main(["https://new.dev/", "--rows", str(rows), "--no-network", "--no-topics"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "topics_by_tab" not in out
    assert out["results"][0]["duplicate"][0]["tab"] == "MCP"
