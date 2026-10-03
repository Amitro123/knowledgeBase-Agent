# Wiki

Persistent markdown articles maintained by agents querying the knowledge base.

Each `.md` file is a wiki article created via the MCP `write_article` tool.
Articles typically contain synthesised answers, curated topic overviews, or
research notes that reference resources from `data/resources.json`.

## Convention

Articles should include YAML-ish front-matter:

```
---
title: "Topic Overview"
created: 2026-01-01
updated: 2026-01-02
tags: [rag, vector-db]
---
```

This makes them discoverable via `list_articles`.
