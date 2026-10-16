# Skill and tool search

How agents, the plugin creator and the app's search boxes find a skill section or a
tool from plain words. Decision record: [ADR 0004](../adr/0004-search-index-in-ducky-db.md).

## Where things live

| Piece | File |
|---|---|
| Tables (`search_docs`, `search_fts`, `search_vecs`, `search_state`) | `backend/store/migrations/0016_search.sql` |
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
  load condition, keywords and the opening of the file.
- **section** — `skill:<pack>/<id>#<heading-slug>`: one `##`/`###` section, at most
  1,200 characters (longer ones split on paragraphs; a code block stays whole up to
  2,400).
- **tool** — `tool:<name>`: the name as words, description, aliases and parameter
  names; `path` is who provides it (core, a plugin, a nested MCP server).
- **record** — `record:<plugin>:<scope>:<id>`: a plugin's own row through `api.search`.

The vector of a row is computed from its heading path ("pack > file > section")
plus its text, so a short section still says what it belongs to.

## Sources and freshness

| Source | `source_key` | Revision |
|---|---|---|
| One skill pack (shipped, user, Store or plugin; disabled plugins too) | `pack:<id>` | chunker version, model, folder, origin, owner plugin, file stamps |
| The MCP tool catalog (unfiltered) | `tools` | chunker version, model, catalog hash |
| A plugin's records in one scope | `record:<plugin>:<scope>` | written directly by `api.search` |

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

1. Keywords: FTS5 bm25 over title, path and body, top 50. The query is tokenized,
   stopwords dropped, each token quoted (no FTS syntax from the person's words), the
   last one used as a prefix.
2. Meaning: cosine with every vector of the current model, top 50 (per-process
   matrix, cached until the index changes).
3. Reciprocal rank fusion, weights (keyword, meaning) = (1, 1) for skills and
   (1, 0.5) for tools, tuned on the eval set. An exact `pack/sub-skill`, pack id or
   tool name in the query is pinned first, and so is a tool whose name the query
   spells in plain words ("run a workflow" pins `run_workflow`; skipped when more
   than three tools share the words).
4. Filters for the calling chat, applied after ranking: packs denied for the ducky,
   its sub-skill allowlist (always-on and `core` stay), disabled plugins, tools not in
   the chat's live catalog, records of other plugins or scopes.
5. At most two rows per sub-skill.

Every hit carries `read`: the exact `skill_read_subskill(..., section=...)` or
`ducky_get_tools(name=...)` call that opens it.

## Fallbacks

No model folder or a load error → keyword search only (logged once). An index
error → callers keep their previous behaviour (`ducky_get_tools` still merges the
old all-words matches). An empty index on the first search in a process waits up to
2 s for the first refresh.

## Measuring

`python scripts/search_eval.py --engine all --misses` builds a throwaway index in a
temp folder from the skills installed on the PC and the running app's tool catalog,
and prints hit@1, hit@3 and MRR for today's lookup, keywords only and hybrid. The
person's `ducky.db` is never opened.
