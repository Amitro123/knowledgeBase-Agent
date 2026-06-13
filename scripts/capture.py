#!/usr/bin/env python3
"""
capture.py — Reads Obsidian markdown notes from the inbox, enriches each URL
with Claude (via OpenRouter), and appends new entries to data/resources.json.

Dedup is URL-based: any URL already present in resources.json is skipped.
Notes are never modified or deleted — they remain as archive.

Environment variables required:
  OPENROUTER_API_KEY  — your OpenRouter API key
"""

import os
import re
import json
import glob
import sys
import datetime
from pathlib import Path

import requests
import yaml

# ── Config ──────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "anthropic/claude-3-haiku"          # fast & cheap; change if needed

REPO_ROOT = Path(__file__).parent.parent
RESOURCES_FILE = REPO_ROOT / "data" / "resources.json"

# INBOX_GLOB is injected via the workflow env; default for local dev
INBOX_GLOB = os.environ.get(
    "INBOX_GLOB",
    "vault/Shared/AmitRobot/*.md"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_resources() -> list[dict]:
    if RESOURCES_FILE.exists():
        with open(RESOURCES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_resources(resources: list[dict]) -> None:
    RESOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)


def existing_urls(resources: list[dict]) -> set[str]:
    return {r["url"] for r in resources if "url" in r}


def parse_note(path: Path) -> dict | None:
    """Parse a markdown note with YAML frontmatter. Returns None if no URL."""
    text = path.read_text(encoding="utf-8")

    # Extract YAML frontmatter
    fm: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                pass
            body = parts[2]

    # URL: prefer frontmatter "source"/"url", then first URL in body
    url = fm.get("source") or fm.get("url") or ""
    if not url:
        match = re.search(r"https?://[^\s\)\"'>]+", body)
        if match:
            url = match.group(0)

    if not url:
        print(f"  skip (no URL): {path.name}")
        return None

    return {
        "path": str(path),
        "url": url.strip(),
        "title": fm.get("title", path.stem),
        "tags": fm.get("tags", []),
        "body": body.strip(),
        "created": str(fm.get("created", "")),
        "source_file": path.name,
    }


def enrich_with_openrouter(note: dict) -> dict:
    """Call OpenRouter / Claude to generate a summary and extract tags."""
    if not OPENROUTER_API_KEY:
        print("  WARNING: OPENROUTER_API_KEY not set — skipping AI enrichment")
        return {
            "summary": note["title"],
            "ai_tags": [],
            "category": "uncategorised",
        }

    prompt = f"""You are a knowledge-base curator. Given the information below about a saved link, return a JSON object with exactly these fields:
- "summary": a 1-2 sentence description of what this resource is about (in English)
- "ai_tags": an array of 3-6 lowercase tag strings (topics, tools, concepts)
- "category": one of: tutorial | tool | research | news | reference | community | other

Title: {note['title']}
URL: {note['url']}
Body snippet: {note['body'][:800]}

Return ONLY the JSON object, no markdown fences."""

    try:
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://github.com/Amitro123/knowledgeBase-Agent",
                "X-Title": "KnowledgeBase Agent",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if model added them
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        enriched = json.loads(content)
        return enriched
    except Exception as exc:
        print(f"  WARNING: OpenRouter error — {exc}")
        return {
            "summary": note["title"],
            "ai_tags": [],
            "category": "other",
        }


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"=== capture.py  {datetime.datetime.utcnow().isoformat()}Z ===")
    print(f"INBOX_GLOB : {INBOX_GLOB}")
    print(f"RESOURCES  : {RESOURCES_FILE}")

    resources = load_resources()
    seen = existing_urls(resources)
    print(f"Existing entries: {len(resources)}")

    note_paths = sorted(glob.glob(INBOX_GLOB, recursive=True))
    print(f"Notes found: {len(note_paths)}")

    added = 0
    for path_str in note_paths:
        path = Path(path_str)
        print(f"\n→ {path.name}")
        note = parse_note(path)
        if note is None:
            continue
        if note["url"] in seen:
            print(f"  skip (already in resources): {note['url']}")
            continue

        print(f"  enriching: {note['url']}")
        enriched = enrich_with_openrouter(note)

        entry = {
            "id": len(resources) + 1,
            "url": note["url"],
            "title": note["title"],
            "summary": enriched.get("summary", ""),
            "category": enriched.get("category", "other"),
            "tags": list(set(
                (note["tags"] if isinstance(note["tags"], list) else [note["tags"]])
                + enriched.get("ai_tags", [])
            )),
            "source_file": note["source_file"],
            "created": note["created"],
            "added_at": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        }

        resources.append(entry)
        seen.add(note["url"])
        added += 1
        print(f"  ✓ added: {entry['title'][:60]}")

    save_resources(resources)
    print(f"\n=== Done: {added} new entries added. Total: {len(resources)} ===")


if __name__ == "__main__":
    main()
