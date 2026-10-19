---
description: "Plugin data: api.data docs and files, Local or one shared space, team locks, conflicts and history, sensitive data, encryption, read-only and lost access"
metadata:
  order: 4
  label: "Plugins: data"
  default_enabled: false
  load_condition: "A plugin stores records, files or settings, or the user asks where a plugin's data lives or about sharing it"
---

# Plugin data

Every plugin stores its data through the host: `api.data` in the backend, `data.*` /
`files.*` in panels. Never a folder, file, SQLite database or `%LOCALAPPDATA%` path
you pick: the host keeps each plugin's data per signed-in account and per scope,
encrypted on disk, and syncs shared copies.

## Docs and files

| Backend (`api.data`) | Panel bridge | What |
|---|---|---|
| `get(key, default=None)` | `data.get {key}` → `{key, value}` | One JSON doc (`None` / `null` when missing) |
| `put(key, value)` | `data.put {key, value}` → `{ok, changed}` | Write one doc (≤ 1 MB) |
| `items(prefix)` | `data.list {prefix, values: true}` → `{items}` | All docs under a prefix in one read |
| `keys(prefix)` | `data.list {prefix}` → `{keys}` | Just the keys |
| `delete(key)` | `data.delete {key}` → `{ok, deleted}` | Remove one doc |
| `put_file(path, bytes)` | `files.put {path, b64}` | A file (≤ 100 MB) |
| `get_file(path)` → bytes or `None` | `files.get {path}` → `{ok, b64}` | Read it back; there is no file path to hand out |
| `has_file(path)`, `files(prefix)` | `files.list {prefix}` | Exists / list `[{path, size, sha256}]` |
| `delete_file(path)` | `files.delete {path}` | Remove one file |
| `scope()` | `scope.get` → `{scope}` | `{kind, label, spaceId, readOnly}`: whose copy this is (`kind` is `personal`, `shared` or `sandbox`) |

- **One doc per entity**: `card.pip`, `pack.starter`, `run.2026-10-08`. Never one
  big `db.json`: two people editing different cards must not overwrite each other.
  Within one doc the last write wins.
- Doc keys `[a-z0-9._-]` up to 128 characters; file paths `[a-z0-9._/-]` up to 256,
  no `..`, no leading dot. Sanitize ids that come from users before using them in keys.
- `put` returns `changed: false` when nothing changed, so it is cheap to call.

## Local or one shared space

- The **user** picks, per plugin, whether its data is **Local** (this account on this
  PC) or one **shared space** offered by an installed plugin: Plugins → the plugin →
  Data. A plugin never mixes the two and needs no code for either.
  With no shared spaces on offer, Local is the only choice and the Data page says so.
- A plugin whose data must never reach a team (browsing, personal tools) sets
  `"data_sharing": false` at the top of `plugin.json`: its data is always Local, it
  gets no scope bar and no Data picker, and switching it to a space is refused.
  `"data_sharing": true` offers a shared space before the plugin has stored anything.
  Any other value is refused by `ducky_plugin_validate`.
- `ducky_plugin_data_scope(id, scope="")`: empty `scope` tells you which copy a plugin
  uses; `"local"` or a space id switches it. Switch only when the user asks: it asks
  them first, nothing is copied, open panels are told, the new copy syncs, and the
  plugin restarts on it with its open panels reloaded.
- Panels get `plugin_scope_changed` with a `reason`. `"synced"`: a sync brought
  teammates' changes into the same copy; `keys` lists the doc keys and file paths that
  changed (absent: re-read everything). Merge them into what is on screen and keep the
  open item, selection and scroll: never close what the person has open. `"switched"`:
  whose data it is changed (account, Local or a space): start over. Bursts arrive as one
  push, and a hidden panel gets one when shown. The backend reads the scope fresh on
  every call.
- Items that belong to one PC (diagnostics, per-device state, a "last opened" note) go
  under a prefix listed in `"data_local": ["qa.", "device/"]` at the top of
  `plugin.json`: they stay in the Local copy whatever copy the plugin shows, never sync,
  and never show teammates as someone editing them. Without it, every write of such an
  item goes out to the whole team and lands in their open panels.
- A backend that caches docs in memory registers `api.data.on_change(callback)` once in
  `register(api)`. After a sync changed this plugin's data, `callback(keys)` gets the doc
  keys and file paths that changed: drop those from the cache. It runs in every process
  that loaded the plugin (in the agents' bridge just before the plugin's next tool call),
  so never assume it runs on a particular thread, and keep it quick. An exception in it is
  logged and ignored.
- `prefs.*` and `cache.*` follow the scope too: a shared copy has its own prefs and
  cache on this PC (never synced), locked and unlocked with it.

## Shared copies

- Synced with everyone in the space; each space keeps its own copy and spaces never
  see each other's data. The plugin that offers the space syncs it; its skill says how.
- A shared copy can be **read-only** (paused by whoever runs the space). Writes then
  raise `PermissionError` with a message for the user. Catch it in tools and return
  `{"ok": False, "error": str(exc)}`.
- **Losing access** to the space locks its copy on this PC: reads come back empty and
  writes fail until access returns, then everything unlocks as it was. A copy that
  stays locked long enough leaves this PC (never the server's); changes made here that
  never went out wait until the person saves them to Local or lets them go (the bar's
  Details offers it).
- Whose data the user is looking at: the panel's scope bar shows it, and the host adds
  `scope` (`local` or the space's name) to every dict a tool of a data-using plugin
  returns. Say it in your reply when it matters.

## Team copies: changes, locks, conflicts, history

A team's shared copy keeps every change, like source control. The plugin needs no
code for it; these rules decide how well it works for people editing together.

- **One call is one change.** Everything one tool call or one panel RPC writes goes out
  together, named after the call and marked as the person's or their ducky's. Teammates
  get all of it or none of it. Write related docs in one call.
- **Locks.** Anyone can lock an item (a doc or a file) from the bar's Details, and a
  ducky can with `ducky_team_lock(plugin, unit, "acquire")` before a long edit (release
  it after). While someone else holds an item, a write to it raises `PermissionError`
  ("card.pip is locked by Ana since 3:02 PM. Your change wasn't saved."). Catch it in
  tools and return `{"ok": False, "error": str(exc)}`, as for read-only copies.
- A plugin whose items must be held while one person edits them declares
  `"data_locks": {"<key prefix>": "auto" | "required"}` in `plugin.json` (the start of
  a doc key or file path; the longest match wins; `""` is every item):
  - `auto`: the first change takes the lock for this PC; the write goes ahead either
    way. It is released 5 minutes after the last change went out.
  - `required`: the write waits up to 3 s for the lock and is refused without it.
  Leave it out for data that merges well (most plugins).
- **Conflicts.** Docs edited on two PCs at once merge field by field. Arrays of objects
  that all have an `id` merge by `id`; other arrays are replaced whole. When both sides
  changed the same field, the team's version stays and this PC's is kept as a conflict
  for the person (Keep mine, Keep theirs, Compare in the bar's Details). Files are never
  merged: the team's version stays and this PC's is kept beside it. So keep fields that
  people edit separately in separate keys or `id`'d objects, and big blobs in files.
- **History.** Every change is kept with who made it and when. The bar's Details shows
  it; restoring an item, or the whole plugin to an earlier change, is a new change that
  everyone gets, never a rewrite.
- `ducky_team_status(plugin)` says who is in the copy and what they do, what is locked,
  what waits to go out or come in, and the conflicts. `ducky_plugin_data_scope` gives
  the same for a shared copy.

## Sensitive data

`api.data.put(key, value, sensitive=True)` keeps a doc on this PC in the account's
own scope and **never syncs it**, whatever scope the plugin uses. Use it for
personal tokens, private notes, anything that must not leave this PC.

- Read it with `get(key, sensitive=True)`. `keys()` and `items()` never list it.
- Delete it with `api.data.personal().delete(key)` (plain `delete` acts on the
  active scope).
- API keys are not data: declare a `secret` setting (`secret_keys` +
  `settings.sections`) and read it with `get_key`; see `plugin_examples_tools`.

## Don't

- Don't write files with `open()`, `Path.write_*`, `sqlite3` or a folder of your own.
  The one exception: files a workflow node or image generator makes go in the
  `artifact_dir` / `output_dir` Ducky passes in. Project files go through
  `api.call_tool("workspace_write_file", …)`.
- Don't keep records in `prefs` (small UI choices only) or in page memory (panels
  reload when moved to a floating window).
- Don't read another plugin's data; call its MCP tools instead (`api.call_tool`).
