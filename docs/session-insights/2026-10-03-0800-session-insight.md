---
title: MCP server — read-only knowledge-base server for agents
date: 2026-10-03
---

## Task / problem summary

Add an MCP server to `knowledgeBase-Agent` that replicates the read-only
knowledge-base MCP from `divorce-journey-agent`, adapted for this project's
Google Sheets → `resources.json` architecture.

## Root cause

The project had no agent-queryable surface. Resources lived only in
`resources.json` (rebuilt from Google Sheets) with a read-only frontend.
No programmatic query interface existed for agents.

## What went well

- The MCP Python SDK v2.x (`MCPServer`) worked cleanly; one import rename
  from v1 (`FastMCP`) was the only migration needed.
- The reference server's bidirectional substring matching for Hebrew
  translated directly — same algorithm, different data shape.
- The tag-search pair (`search_tags` / `get_tag`) maps naturally to the
  reference's `search_claims` / `get_claim` pattern.

## What went poorly

- First pass (before seeing the actual reference code) built a read-write
  server with ingest, wiki, lint, log — all wrong. The reference server
  is strictly read-only with no mutation tools.
- Reference repo was inaccessible (private, 404). Had to be corrected
  by the user uploading the actual `kb_server.py` and README.

## How it was solved

Rewrote the MCP server as a read-only 4-tool server matching the reference
architecture:

| Reference tool       | This repo tool  | Notes                           |
|---------------------|-----------------|---------------------------------|
| `query_kb(question)`| `query_kb(question)` | Same pattern; searches resources instead of wiki pages |
| `get_page(slug)`    | `get_resource(resource_id)` | Numeric id instead of file slug |
| `search_claims(question)` | `search_tags(question)` | Tags/categories instead of legal claims |
| `get_claim(claim_id)` | `get_tag(tag)` | List resources by tag |

## Tradeoffs or alternatives considered

- **Kept search_tags/get_tag** (analogous to search_claims/get_claim):
  useful because the KB has 30+ distinct tags and an agent benefits from
  discovering the tag taxonomy before drilling into resources.
- **Dropped write-back wiki**: the reference never writes. The Sheet is
  the only place new content enters.
- **Dropped ingest/lint/log/index**: not in the reference. The server
  reads the generated artifact (`resources.json`) exactly as the reference
  reads its generated `knowledge-graph.json`.

## Tests added or updated

- `scripts/test_mcp_server.py`: 27 tests covering query_kb, get_resource,
  search_tags, get_tag, bidirectional matching, Hebrew search, read-only
  invariant verification, and edge cases (empty KB, missing file, stop words).

## Lessons learned

- "Karpathy LLM Wiki pattern" does not imply write-back. The actual
  reference implementation is read-only — the wiki/graph grows via
  separate scripts, and the MCP only reads the generated artifacts.
- Always verify against actual code, not descriptions of code.

## Follow-up actions

- None blocking. The server is feature-complete relative to the reference.
