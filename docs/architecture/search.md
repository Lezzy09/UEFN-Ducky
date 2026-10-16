# Skill and tool search

How agents, the plugin creator and the app's search boxes find a skill section or a
tool from plain words. Decision record: [ADR 0004](../adr/0004-search-index-in-ducky-db.md).

## Where things live

| Piece | File |
|---|---|
| Tables (`search_docs`, `search_fts`, `search_vecs`, `search_state`) | `backend/store/migrations/0016_search.sql`, `0017_search_summary.sql` (summary column) |
| SQL (upserts, bm25 query, vectors) | `backend/store/repos/search.py` |
| Model loading and encoding | `backend/search/embedder.py` |
| Packs and tools → rows | `backend/search/chunker.py` |
| Sources, refresh triggers, background thread | `backend/search/indexer.py` |
| Ranking and per-chat filters | `backend/search/query.py` |
| Per-turn skill hints | `backend/search/hints.py` |
| `api.search` for plugins | `backend/search/records.py` |
| Questions and runner for measuring it | `backend/search/eval/`, `scripts/search_eval.py` |
| Model fetch (build time) | `build/fetch_search_model.py` → `build/search-model/` → `models/search` in the app |

## Rows

- **pack** — `skill:<pack>`: label, description, keywords and the list of its files.
- **subskill** — `skill:<pack>/<id>` (SKILL.md is `core`): label, description,
  load condition, keywords and the file's intro (or the list of its section headings),
  so a specific question lands on the section row that holds the details.
- **section** — `skill:<pack>/<id>#<heading-slug>`: one `##`/`###` section, at most
  1,200 characters (longer ones split on paragraphs; a code block stays whole up to
  2,400).
- **tool** — `tool:<name>`: the name as words, description, aliases and parameter
  names; `path` is who provides it (core, a plugin, a nested MCP server). The first
  line of the description sits in its own `summary` column instead of the body (see
  Ranking); skill and record rows leave `summary` empty.
- **record** — `record:<plugin>:<account>~<scope>:<id>`: a plugin's own row through
  `api.search`. The signed-in account is part of the key (every account's Local scope
  is `personal`), so one person never reads or clears another's records on a shared PC.
  Records have no other source: a rebuild keeps them and re-embeds them. They go with
  an uninstall (and the plugin's later writes are refused until it is installed again),
  with a purged team copy, and with a plugin-test sandbox (when the test ends, or six
  hours later if the app closed first).

The vector of a row is computed from its heading path ("pack > file > section")
plus its text, so a short section still says what it belongs to. A tool's vector is
its name and the first line of its description only: a long docstring of usage notes
averaged into one vector drowned what the tool does. `CHUNKER_VERSION` is part of
every row's content hash, so changing how rows or vectors are built re-embeds them.

Results never list the same read call twice (a pack and its `core` sub-skill both
open with `skill_read_subskill(pack_id=pack, subskill_id="core")`).

## Sources and freshness

| Source | `source_key` | Revision |
|---|---|---|
| One skill pack (shipped, user, Store or plugin; disabled plugins too) | `pack:<id>` | chunker version, model, folder, origin, owner plugin, file stamps |
| The MCP tool catalog (unfiltered) | `tools` | chunker version, model, catalog hash |
| A plugin's records in one account's scope | `record:<plugin>:<account>~<scope>` | written directly by `api.search` |

A refresh skips a source whose revision matches `search_state`; inside a changed
source it re-embeds only rows whose content hash changed or that lack a vector for
the current model. Triggers: plugins finished loading in the app, plugin install /
update / uninstall / enable (`invalidate_plugin_skill_caches`), Skills studio
saves and seeding (`skills/store.py: _skills_changed`), a new catalog revision seen
by `ducky_get_tools`, the Database tab's Clear / Rebuild, and a search when the last
check is over 30 s old. Periodic checks never list the tool catalog (that can wake
nested MCP servers); explicit triggers do. Under the strict privacy policy the tool
catalog is not re-indexed.

## Ranking

1. Keywords: FTS5 bm25 over title, path, body and summary with column weights 3, 2,
   1 and 2.5, top 50. The query is tokenized, stopwords dropped, each token quoted (no
   FTS syntax from the person's words), the last one used as a prefix. The summary
   weight is for tools: in a body holding the whole docstring and parameter names, the
   line that says what the tool does counted no more than a usage note, so
   `spawn_actor` ("Place an actor …") fell out of the keyword top 10 for "place an
   actor in the level" (10th after fusion).
   The line is moved out of the body, not copied, because FTS5 bm25 measures length
   over all columns: a copy lengthens tool rows and the average row, which moved skill
   rankings too. Indexing only the first paragraph was tried and lost tools whose key
   words sit further down ("undo the changes an agent made" → `changeset_revert`).
2. Meaning: cosine with every vector of the current model, top 50 (per-process
   matrix, cached until the index changes; see Concurrency).
3. Reciprocal rank fusion, weights (keyword, meaning) = (1, 1) for skills and
   (1, 0.75) for tools, tuned on the eval set. An exact `pack/sub-skill`, pack id or
   tool name in the query is pinned first, and so is a tool whose name the query
   spells in plain words ("run a workflow" pins `run_workflow`; skipped when more
   than three tools share the words).
4. Filters for the calling chat, applied after ranking: packs denied for the ducky,
   its sub-skill allowlist (always-on and `core` stay), disabled plugins, tools not in
   the chat's live catalog. A plugin's record query is limited to its own source
   *before* the top-50 cut, so other plugins' records can never crowd its rows out.
5. At most two rows per sub-skill.

Every hit carries `read`: the exact `skill_read_subskill(pack_id=..., subskill_id=...,
section=...)` or `ducky_get_tools(name=...)` call that opens it, with named arguments
as an MCP call takes them (from the positional form agents guessed `pack=`, which the
tool now also accepts beside `skill=`).

## Per-turn hints

Each user turn gets at most three sections, in the live-context tail for Ducky's own
agent and in front of the prompt for coding agents, never in the cached system
prompt. The search runs on the first sentence with three or more content words (the
task); later sentences are usually about the reply ("answer in four lines", "don't
change any files") and pulled the hint toward UEFN Ducky's own how-to sections. The
whole message is searched only when that sentence finds nothing. A hit counts when
its meaning score is at least 0.42, or at least 0.28 with a keyword rank in the top
10, so chit-chat ("continue", "did you finish?") gets no hint.

## Concurrency

Several processes use one `ducky.db`: the app and every IDE or agent bridge, each with
its own background "search-index" thread and many request threads.

- **First open.** A process's first open of the file (a staged restore, the switch to
  WAL, migrations and the pre-migrate snapshot) runs under `ducky.db.open-lock`, an OS
  file lock (`store/db.py`). The WAL switch also retries: SQLite never waits on that
  read-to-write lock upgrade, so two processes opening a new file failed at once with
  "database is locked". `open_checked` never treats a lock as damage, so it never
  restores a snapshot over live data because another process held the file.
- **Cache token.** Triggers count every insert, update and delete of `search_docs` and
  `search_vecs` in `search_meta` (migration 0018), whoever writes them. That counter
  keys each process's vector-matrix cache; one thread loads a new revision while
  concurrent searches wait for it.
- **One snapshot per search.** The keyword ids, vector ids, pins and the rows they name
  are read in one read transaction (one WAL snapshot), so a rebuild in between cannot
  hand a search unrelated rows under re-used ids.
- **Writes check inside the transaction.** A vector fill stores a vector only if the row
  still holds the text it was made from. A record write checks the per-plugin cap and
  the plugin's uninstall mark inside its own write transaction. An unchanged record is
  not re-embedded or rewritten.
- **Triggers that re-list tools.** A plugin that finishes registering after boot
  (enable, reload, repair, late register) requests a refresh. A plugin that is enabled
  but not loaded in this process keeps its tool rows. `ducky_get_tools` remembers the
  catalog revision per chat filter, so chats with different plugin selections in one
  process are not mistaken for a catalog change.
- **WAL size.** `journal_size_limit` caps `ducky.db-wal` at 64 MiB after each reset; one
  large write used to leave it at its high-water mark while any process kept the file
  open.

## Token cost

`skill_search` returns 5 hits by default, each only where it is, a snippet and the
`read` call (scores, match details and the ids inside `read` were a third of every hit);
the app's own search boxes keep the full rows. `ducky_get_tools(pattern=)` returns 10
schemas per page by default (each about 210 tokens).

Measured on the installed skills (123 packs) and a 1,257-tool catalog, tokens estimated
as characters / 4, counting everything an agent reads until it reaches the right file or
tool (at most three reads):

| | Before | Search | Per-turn hint |
|---|---|---|---|
| Skills: right file reached | 51% | 94% | 100% (on the 40% of questions that get a hint) |
| Skills: tokens per right answer | 5,185 | 1,947 | 1,404 |
| Tools: right tool reached | 31% | 97% (`skill_search(kind="tools")` + one schema) | |
| Tools: tokens per right answer | 1,617 | 596 | |

Before, the agent picked whole files by their ids and tools by all-words matching (which
usually returned nothing). The skill index in Ducky's own system prompt grew by about
1,400 tokens (pack descriptions and the `skill_search` lines); it is part of the cached
prompt prefix. Coding agents (Codex, Claude Code, Cursor) do not get that index.

## Fallbacks

No model folder or a load error → keyword search only (logged once). An index
error → callers keep their previous behaviour (`ducky_get_tools` still merges the
old all-words matches). An empty index on the first search in a process waits up to
2 s for the first refresh.

## Measuring

`python scripts/search_eval.py --engine all --misses` builds a throwaway index in a
temp folder from the skills installed on the PC and the running app's tool catalog,
and prints hit@1, hit@3 and MRR for today's lookup, keywords only and hybrid. The
person's `ducky.db` is never opened. `--tools-json` scores a saved
`get_mcp_tools_catalog` result instead; save one while Ducky's own editor tools are
listed, or the questions about them are skipped.

The summary column (summary weight 2.5 vs. 1, which equals the old ranking) on 35
tool questions against a full 1,257-tool catalog: hybrid hit@1 0.714 → 0.771, hit@3
0.914 → 0.971, MRR 0.818 → 0.867. Keywords alone (the no-model fallback) lose one
question, hit@3 0.886 → 0.857, MRR 0.792 → 0.779: `set_actor_properties` and
`set_verse_editable` have first lines without "change" or "device", so other rows
whose first lines have them pass them for "change a property on a placed device".
Skills are unchanged. The first lines of `set_actor_properties`, `spawn_actor`,
`search_assets`, `add_niagara_emitter`, `ducky_ask_user` and `changeset_revert` were
then reworded to say what each tool does in the words people use.
