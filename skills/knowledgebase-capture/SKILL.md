---
name: knowledgebase-capture
description: >
  Use whenever the user sends a URL, an article, a post, a repo, a PDF or pasted
  text: a bare link on its own counts ("save this", "add to KB", "תשמור", or
  just github.com/...). Extracts the facts, writes one correct row to the
  "Importent links" Google Sheet (tab = branch, Category = topic), avoids
  duplicates and private links, runs the sync so it reaches the site graph, and
  tells the user in Hebrew what was saved and where.
---

# Knowledge-base capture

The user's knowledge base is a Google Sheet that a sync job turns into a graph
website and an MCP server. **The sheet is the only thing you write.** The graph is
built from it automatically:

| Sheet | Becomes in the graph |
|---|---|
| a tab (e.g. `Tools`) | a **branch**: one cluster on the site |
| the row's `Category` | a **topic** inside that branch |
| the row (its `Link`) | a **resource**, de-duplicated by URL across all tabs |

So the quality of the graph equals the quality of three choices: the tab, the
Category, and a clean, unique Link. Get those right every time.

**Language:** talk to the user in **Hebrew** (status messages, questions and
the final report). Values written to the sheet follow the "Row format" rules
below: English Summary and Category, and Notes in Hebrew or English.

## Workflow (do these in order)

1. **Run the pre-flight check** on all the links at once (see "Pre-flight
   check"). It cleans each link, finds duplicates in every tab, flags privacy
   problems and lists each tab's topics. Don't read the whole sheet for this.
   - Duplicate found: don't add a row. Fill in any empty fields of the existing
     row if you have better data, and tell the user where it already lives.
   - A warning: handle it per "Privacy" before going on.
2. **Check it's reachable** and **extract** the facts for its type (see
   "Validation" and "Extraction by link type"). For GitHub repos use the
   GitHub API, not the web page.
3. **Pick the tab, then the Category** from the check's `topics_by_tab`
   (see "Choosing tab and Category").
4. **Write the rows**: all new rows in one write, each with all six columns
   (see "Row format").
5. **Start the sync and don't wait for it** (see "After writing").
6. **Reply** in Hebrew right away (see "Reply to the user").

Before step 1, send one short Hebrew line so the user knows you started, e.g.
`מוסיף את <name> לגיליון. קודם אבדוק מה הוא עושה.`

When the user sends several links, check them in one call, write them in one
batch, start one sync, and reply once with a block per link.

## Pre-flight check

From a fresh checkout of `Amitro123/knowledgeBase-Agent` (`git pull` first, so
the snapshot is current), run:

```
python scripts/check_link.py <url> [<url> ...]
```

It needs no credentials, writes nothing, and reads only the repo snapshot
(`data/resources.json` and `data/graph.json`), which is as fresh as the last
sync (`snapshot_generated_at`). It prints JSON:

- `results[].clean_url`: the link to write in the sheet (short link resolved,
  tracking parameters removed, GitHub repo root, arXiv abstract page).
- `results[].duplicate`: every existing row with the same link, as
  `{tab, category, title, date}`. Empty means new.
- `results[].warnings`: privacy or validity problems (`google-drive-link`,
  `secret-param`, `internal-host`, `personal-link`, `short-link` that didn't
  resolve).
- `results[].github_repo`: `owner/repo` when it's a GitHub repository.
- `topics_by_tab`: each tab's existing topics, most used first, including
  empty tabs.

Rows added since the last sync are not in the snapshot. If the sync ran more
than a few minutes ago, read the **Link and Category columns of the target tab
only** through the Sheets connector, save them as a JSON list of
`{"tab", "link", "category"}`, and add `--rows <file>`. Never read all the tabs.

## Row format

The header row of every tab is exactly:
`Date | Link | Name/Author | Function/Summary | Category | Review/Notes`.
Never rename, reorder or add columns.

| Column | Rule |
|---|---|
| **Date** | Always fill it, in `YYYY-MM-DD` (today's date, or the publication date if the user asks for that). An empty Date makes the site show a guessed "first seen" date instead. |
| **Link** | The cleaned canonical URL (see "Link rules"). One URL per row. |
| **Name/Author** | Never empty: an empty cell makes the site show the raw URL. Format: GitHub repo `Owner / repo`; article `Title — Author (Site)`; post `Author (LinkedIn)` or `Author (X)`; paper `Short title — First author et al.`; product `Product name`. |
| **Function/Summary** | One plain sentence, max ~25 words: what it is and what it's for. English. No marketing adjectives. |
| **Category** | The topic (see below). Never empty, never `tool`, never `other`, never the tab's own name. |
| **Review/Notes** | Key facts and why it's worth keeping (see per-type lists). Hebrew or English. No personal data, no secrets. |

## Choosing tab and Category

Use the check's `topics_by_tab` for the existing Category values; it is
current as of the last sync. The table below says what each tab is for.

1. **Tab:** put the link on the **single tab that best describes what it is
   about**. Add a second tab only if it clearly belongs to both. Never use 3 or
   more tabs.
2. **`Repos in github`** is for GitHub projects that fit **no** subject tab. If
   a subject tab fits (Skills, MCP, Memory, RAG, Security…), put it there and
   do **not** also copy it to `Repos in github`. The site detects GitHub repos
   from the URL on its own.
3. **Category:** reuse one of that tab's existing Category values whenever one
   fits, with the spelling `topics_by_tab` shows. Case doesn't matter (the
   graph lower-cases topics), but other variants become separate topics.
   Create a new Category only if none fits *and* the tab will likely get 2 or
   more links on it. Big tabs keep 3–7 broad topics; small and new tabs may
   start more specific.
4. A link on two tabs gets **each tab's own Category** and the same Date,
   Name/Author, Summary and Notes in both rows.

Snapshot of tabs and topics, refreshed 2026-10-05 (resources per topic in brackets):

| Tab | What goes there | Current topics |
|---|---|---|
| Repos in github | GitHub projects with no better subject tab | Agent Frameworks (15), Data & RAG (10), LLM Infrastructure (7), Dev Utilities (5), Memory & Context (5), Learning Material (4), Classic ML (3) |
| Tools | Products, apps and tools that aren't mainly a GitHub repo | AI Apps & Agents (7), Developer Tools (7), Data & Knowledge (6), MLOps & Evaluation (6), Tutorials (3) |
| Learning | Articles, guides, courses, books, explainers | Agents & Context (6), LLMs & Training (5), RAG & Retrieval (4), Productivity (2) |
| Skills | Agent skills: libraries, evaluation, security, workflows | Skill Libraries (4), Skill Quality (3), Workflows & Apps (2) |
| Memory | Agent memory and context management | Agent Memory (4), Agent Harness (1), reference (1) |
| Claude | Claude / Claude Code specific | Claude Code (3), Cost & Models (2) |
| MCP | MCP servers, clients, apps, setup | MCP Apps & Clients (2), MCP Servers (2), Setup & Config (1) |
| RAG | Retrieval-augmented generation | Frameworks & Tools (2), Guides (2), Vector Databases (1) |
| Automation flow | Workflow and browser automation, lead-gen flows | Automation (2), Browser Automation (1), Lead Generation / Automation (1) |
| Harness | Agent harnesses and coding-agent runtimes | Agent Harness (1), Agent Workflow (1), Skill Optimization (1), tutorial (1) |
| Jev | The Jev model and its ecosystem | Agent Harness (1), Code Search (1), Postgres Extension (1), news (1) |
| AI Solutions-linkedin | Solution ideas from LinkedIn posts | AI Agents / Context (1), Evaluation (1), LLM Architecture (1) |
| Security | AI / agent security | AI Security / IAM (1), Skill Security (1), reference (1) |
| Trends | News and research that's about where the field is going | news (1), research (1) |
| FinOps | Cost of running AI | Code Search (1) |
| Observability | Tracing, monitoring, logging for LLM apps (empty, ready to use) | — |
| Infrastructure | Hosting, serving, GPUs, deployment (empty, ready to use) | — |

If nothing fits, use the closest tab and say so in the reply. Don't create a new
tab unless the user asks.

## Link rules

The sync de-duplicates on the URL with only light normalisation: lower-case
scheme and host, no `#fragment`, no trailing `/`. **The query string is kept**,
so the same article with different tracking parameters becomes a duplicate.
Clean the link before saving:

`check_link.py` applies these rules; use its `clean_url`. They are here so you
can fix a link by hand when the script can't (e.g. a short link it couldn't
resolve).

- **Resolve short links** to their final URL: `lnkd.in`, `t.co`, `bit.ly`,
  `share.google`, `goo.gl`, `buff.ly` and similar.
- **Remove tracking parameters:** `utm_*`, `ref`, `ref_src`, `source`, `via`,
  `fbclid`, `gclid`, `mc_cid`, `mc_eid`, `si`, `igshid`, `trk`, `trackingId`.
  Keep parameters that select content (e.g. `v=` on YouTube, `id=`).
- **GitHub:** save the repo root `https://github.com/<owner>/<repo>`. Drop
  `/tree/…`, `/blob/…`, `#readme` and `.git`, unless the user clearly means one
  file or folder (then keep that path and say why in Notes).
- **arXiv:** save the abstract page `https://arxiv.org/abs/<id>`, not the PDF.
- **Remove the trailing slash and `#fragment`.**

## Validation

- Open the link. A **404/410, or a domain that doesn't resolve**, is broken:
  don't add it. Tell the user, and suggest an archive.org copy if one exists.
- **Login walls or blocks** (LinkedIn often returns 999; X, paywalls): add the
  row, but extract only what is visible and write `Unverified: login required`
  in Notes. Ask the user to paste the text if the summary would be a guess.
- **Never invent** stars, licenses, versions, dates or authors. Unknown means
  you leave it out.

## Privacy (the site and its data files are public)

Everything in the sheet ends up on a public website. **Don't add, and warn the
user about:**

- Google Drive / Docs / Sheets / `share.google` links to the user's own files,
  or anything shared "Anyone with the link". Publishing the link publishes the
  file.
- Links that carry personal identifiers: referral or affiliate links, lead-gen
  funnels with a person's name or id, invite links.
- URLs with tokens or signatures (`token=`, `key=`, `sig=`, `X-Amz-…`,
  `expires=`), internal or local hosts (`localhost`, `10.*`, `192.168.*`,
  `*.internal`, intranet domains).
- Personal information in Notes: e-mail addresses, phone numbers, names of
  private projects, client or employer names, anything about the user's private
  life.

If the user insists, add it only after they confirm that it may be public.

## Extraction by link type

| Type | Get | Notes column (keep it short) |
|---|---|---|
| **GitHub repo** | README first paragraph, description, topics | stars (rounded, e.g. `~2.1k stars`), license, main language, install command, last commit month; "archived" if it is |
| **Article / blog** | title, author, site, publication date, the main point | 2–3 key takeaways; publication date if different from Date |
| **Paper (arXiv etc.)** | title, first author, year, abstract gist | the contribution in one line; code link if there is one |
| **LinkedIn / X post** | author, the post's claim | the core idea; `Unverified: login required` if you couldn't read it |
| **YouTube / video** | title, channel, length | what you learn and at which minute, if the user gave one |
| **Product / SaaS** | name, what it does, pricing model (free / paid / OSS) | pricing, notable limits |
| **PDF / docs page** | title, publisher | what section matters |
| **Pasted text, no link** | ask for the source URL; if there is none, don't add a row | — |

## After writing

1. **Start the sync and don't wait for it.** GitHub often delays the 30-minute
   schedule by hours. If you have GitHub access, trigger the workflow
   "Sync Google Sheets → resources.json + graph.json" in
   `Amitro123/knowledgeBase-Agent` (workflow_dispatch on `main`), then reply to
   the user straight away. The sync takes a few minutes and the row is already
   saved. If you can't trigger it, say it will appear after the next scheduled
   sync.
2. **Verify only if asked**, or before the next capture: `git pull` and run
   `check_link.py` on the same link. Its `duplicate` should list the tab and
   Category you wrote. With the graph MCP connected, `get_branch("<tab>")`
   shows the same. Don't use `query_kb` (another knowledge base) or `get_node`
   with a URL (it takes node ids like `resource:12`).

## Reply to the user (in Hebrew)

Explain in plain Hebrew **what you saved and where**, in 2–4 sentences per
link: the tab and topic, what the thing is (a Hebrew paraphrase of the
Summary), and the sync status. Keep English names, tab and topic names as they
are. Example:

> engraphis נוסף ללשונית **Memory**, בנושא **Agent Memory**.
> זה זיכרון מקומי לסוכני קוד, שמממש גרף MCP שרץ אצלך.
> הפעלתי את הסנכרון, והוא יופיע בגרף בעוד כמה דקות.

Add a line only when it matters:

- **Duplicate:** `הקישור כבר קיים ב-<Tab>, בנושא <Category> (מ-<Date>). עדכנתי: <fields>` or `לא היה מה לעדכן`.
- **New topic:** `פתחתי נושא חדש, <Category>, ב-<Tab>, כי אף נושא קיים לא התאים.`
- **Two tabs:** `נשמר גם ב-<Tab2>, בנושא <Category2>.`
- **Unverified:** `לא הצלחתי לקרוא את התוכן (נדרשת התחברות). אם תדביק את הטקסט, אעדכן את הסיכום.`
- **Privacy:** `לא הוספתי: הקישור נראה פרטי (<reason>). להוסיף בכל זאת?`
- **Broken:** `לא הוספתי: הקישור מחזיר 404.`
- **Sync not run:** `הסנכרון לא רץ (<reason>). הקישור יופיע אחרי הסנכרון הבא.`

Don't paste the full row back. Show the link itself only if you changed it,
e.g. after removing tracking parameters or resolving a short link.

## Don'ts

- Don't add a row without Name/Author, Date or Category.
- Don't use `tool`, `other`, an empty value or the tab name as Category.
- Don't put one link on 3 or more tabs, or copy it into `Repos in github` when
  a subject tab fits.
- Don't save tracking parameters or short links.
- Don't rename tabs, columns or other people's Categories as a side effect.
  Suggest the change instead.
- Don't edit the repository's code, workflows or data files. The sheet is the
  only input.
