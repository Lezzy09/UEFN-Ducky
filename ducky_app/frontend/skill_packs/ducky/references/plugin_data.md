---
description: "Plugin data: api.data docs and files, Local or one shared space, sensitive data, encryption, read-only and lost access"
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
  Data. A plugin never decides, never mixes the two, and needs no code for either.
  With no shared spaces on offer, Local is the only choice and the Data page says so.
- `ducky_plugin_data_scope(id, scope="")`: empty `scope` tells you which copy a plugin
  uses; `"local"` or a space id switches it. Switch only when the user asks: it asks
  them first, nothing is copied, open panels are told, the new copy syncs, and the
  plugin restarts on it with its open panels reloaded.
- Panels get `plugin_scope_changed` when the scope switches or a sync brings new data:
  re-read your docs. The backend reads the scope fresh on every call.
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
  stays locked long enough leaves this PC (never the server's).
- Whose data the user is looking at: the panel's scope bar shows it, and the host adds
  `scope` (`local` or the space's name) to every dict a tool of a data-using plugin
  returns. Say it in your reply when it matters.

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
