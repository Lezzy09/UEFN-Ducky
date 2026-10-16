# ADR 0004: Skill and tool search index inside ducky.db

Status: Accepted (2026-10-16).

Builds on [ADR 0003](0003-one-local-sqlite-database.md) (one local SQLite database).

## Context

Agents found skills and tools by name. The prompt's skill index listed pack and
sub-skill ids with no descriptions, `skill_read_subskill` needed exact ids, and
`ducky_get_tools(pattern=…)` scored a tool 0 unless every word of the query was in
its name or description. On 2026-10-16 this PC had 123 skill packs (120 shipped
inside plugins), 545 skill files (243 without a description) and 1,257 tools (247
with a weak first line). Measured on the questions in `backend/search/eval/`,
today's lookup put the right skill file in the top 3 for 56% of agent-style
questions and the right tool for 33%.

The corpus is small: about 1.9 MB of skill text and a few thousand tools, enough
to hold every vector in memory in each process.

## Decision

1. **No separate vector server.** The index is four tables in `ducky.db`
   (migration `0016_search.sql`): `search_docs` (one row per pack, sub-skill,
   `##`/`###` section, tool and plugin record), the `search_fts` FTS5 table,
   `search_vecs` (one float32 vector per row) and `search_state` (what each source
   looked like when indexed). Every Ducky process already opens `ducky.db` with
   WAL and `busy_timeout`; the index needs no daemon, no second file and no second
   backup story. Rows are derived data: wiping them loses nothing.
2. **Static embeddings shipped in the app.** `minishlab/potion-base-8M` (model2vec,
   MIT, 256 dimensions) is fetched at build time at a pinned commit with SHA-256
   checks and shipped as float16 under `models/search` (~15 MB). Encoding is a
   tokenizer pass and a mean of matrix rows, done with numpy and `tokenizers`; no
   torch, onnxruntime or network at runtime. Parity with model2vec is tested.
3. **Hybrid ranking.** FTS5 bm25 (title ×3, heading path ×2, body ×1) and cosine
   similarity each give 50 candidates; reciprocal rank fusion (k = 60) merges them;
   an exact pack/sub-skill id or tool name is pinned first.
4. **Filter after ranking.** The index holds everything installed, including
   packs and tools of plugins that are switched off. Each search drops what the
   calling chat may not use (denied packs, the sub-skill allowlist, disabled
   plugins, tools outside the chat's live catalog), so switching a plugin on or off
   needs no reindex.
5. **Fresh by itself.** Sources carry a revision (pack file stamps, tool catalog
   hash, chunker version, model id). Plugin install / update / uninstall / enable,
   Skills studio saves, seeding and a new tool catalog request a background
   refresh; a search re-checks at most every 30 s. Only changed rows are
   re-embedded. Any process may index; rows are upserted by key.
6. **Plugins.** Plugin skills and tools are indexed with no plugin work.
   `api.search` lets a plugin index its own records, scoped to the plugin and its
   data scope. Validate requires a one-line `description:` on every skill file and
   warns on weak tool docstrings; `ducky_plugin_test` reports where each item ranks.

## Alternatives considered

- **A vector database server or embedded store (Chroma, LanceDB, Qdrant).** A second
  process or file format with its own locking, while the panel, IDE bridges and agent
  bridges all read concurrently; another thing to back up and restore; tens of MB more
  in the installer. Nothing at this corpus size needs it.
- **sqlite-vec.** Fits inside `ducky.db`, but it is pre-1.0, a native DLL loaded
  into every process (and checked for the build PC's CPU features), and brute force
  over a few thousand rows in numpy is already well under a millisecond.
- **A transformer embedding model via onnxruntime (bge-small and similar).** Better
  scores on benchmarks, but +50–70 MB and slower to index; the eval set showed the
  static model plus bm25 already clears the target.
- **Cloud embeddings.** Need a key and the network, and send the person's skills
  and queries off the PC.
- **Keyword search only (FTS5).** Most of the gain on agent-written queries, but it
  misses paraphrases ("night sky" vs "starfield") and the people-typed questions.

## Consequences

- Agents get `skill_search`, `skill_read_subskill(..., section=)` and a meaning-
  ranked `ducky_get_tools(pattern=)`. Each user turn carries the top skill sections
  for the request in its live context, never in the cached system prompt.
- The app grows by numpy (with OpenBLAS), `tokenizers` and the model; the build
  fails when any of them is missing.
- If the index reaches the hundreds of thousands of rows (chat or project-file
  search), brute-force cosine stops being cheap: move vectors to a vector
  extension then, not before.
