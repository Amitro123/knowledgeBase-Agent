---
title: MCP server — Karpathy LLM Wiki pattern for knowledge base
date: 2026-10-03
---

## Task / problem summary

Add an MCP server to `knowledgeBase-Agent` that replicates the "Karpathy
LLM Wiki" pattern from a reference repo (`divorce-journey-agent`), adapted
for this project's Google Sheets → `resources.json` architecture.

## Root cause

The project had no agent-queryable surface. Resources lived only in
`resources.json` (rebuilt from Google Sheets) with a read-only frontend.
No programmatic query, ingest, write-back, or quality-check interface existed.

## What went well

- The MCP Python SDK v2.x (`MCPServer`) worked cleanly; one import rename
  from v1 (`FastMCP`) was the only migration needed.
- Tests were straightforward to write and all 23 passed on second attempt
  after fixing the fixture isolation issue.
- The tool surface maps well: `query`, `ingest`, `lint`, `index`, `log`,
  plus wiki CRUD for the write-back layer.

## What went poorly

- Reference repo `divorce-journey-agent` was inaccessible (404 / private).
  Had to rely on the task description's characterisation of the pattern
  and the `divorce-kb` MCP namespace metadata.
- First test run failed (11/23) because the test fixture set module globals
  *before* `exec_module`, which overwrote them. Fixed by setting after.

## How it was solved

Built a Python MCP server (`scripts/mcp_server.py`) with 9 tools and 2
resources. The key design decision was a two-layer architecture:
1. `resources.json` — structured data synced from the Sheet (read+append)
2. `wiki/*.md` — free-form articles where agents write synthesised knowledge

Ingest queues new entries in `data/inbox.jsonl` for later Sheet sync,
preserving the Sheet as canonical source of truth.

## Tradeoffs or alternatives considered

- **Direct Sheet write-back via API**: rejected because it requires
  write-scoped credentials and complicates the Sheet's role as sole editor
  interface. The inbox queue is simpler and safer.
- **Replacing vis-network graph**: explicitly forbidden by requirements.
- **Single-file wiki vs. directory of markdown files**: chose directory for
  better agent ergonomics (each article has a slug, front-matter, independent
  lifecycle).

## Tests added or updated

- `scripts/test_mcp_server.py`: 23 tests covering query, ingest, lint,
  index, get_resource, wiki CRUD, log, edge cases (dedup, empty KB, path
  traversal in slugs).

## Lessons learned

- When importing a module for testing via `importlib.util`, module-level
  constants derived from `__file__` must be overridden *after*
  `spec.loader.exec_module()`, not before.
- MCP v2.x renamed `FastMCP` → `MCPServer`; the error message helpfully
  includes the migration guide URL.

## Follow-up actions

- When the `divorce-journey-agent` repo becomes accessible, compare the
  actual MCP tool signatures and adjust if needed.
- Consider adding a GitHub Action that syncs `data/inbox.jsonl` entries
  back to the Google Sheet automatically.
- The `lint` tool could be extended to check URL reachability (HTTP HEAD).
