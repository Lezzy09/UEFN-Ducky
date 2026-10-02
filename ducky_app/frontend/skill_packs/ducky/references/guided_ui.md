---
description: "Show the user any part of the app: Show me (highlight + popup + chat button), tours, workflow tours"
metadata:
  order: 3
  label: "Show me and tours"
  default_enabled: false
  load_condition: "User asks where something is in the app, how to find or open a setting / plugin / button, or wants to be shown around"
---

## Show me and tours

When the user asks **where** something is, **how to find or open** it, or you tell
them **what to click**, show it instead of only describing it.

| Tool | Use it for |
| --- | --- |
| `ducky_ui_show` | One thing, or several in order (`steps`): takes the user there, highlights it, popup above it with your title and body (Back / Next for steps). Only its close button closes it; the chat keeps a **Show me** button that plays it again. Returns at once. |
| `ducky_walkthrough_run` | A tutorial tour (Skip, required clicks) that blocks until they finish or skip. Prefer `ducky_ui_show(steps=…)` for "where / how do I". |
| `show_workflow` | Workflow nodes; with `title` (+ `body`) it is a Show me on those nodes. |
| `tour_workflow` | A whole workflow node by node; `auto=true` builds the tour from the graph. |
| `ducky_ui_list_targets(route, query, visible_only)` | Find target ids and the view's UI actions. |

Keep your chat reply to a line or two: the popup says the rest.

### `ducky_ui_show`

```
ducky_ui_show(target, title, body="", workflow_id="", navigate="", item_id="",
              action="", action_args=None, also=None, role="", within="",
              steps=None, wait=false)
```

- **target**: an id (`settings.tab.audio`). For things with no id, give **role** and
  put the name in target: `role="button", target="Save", within="workflows.details"`;
  `role="text"` finds that text on screen. **also**: more ids shown as one highlight
  (a few nodes).
- **navigate** (+ **item_id**) opens the view first; **workflow_id** opens a workflow
  and selects `workflows.node.<id>` targets; **action** runs a UI action first
  (`action="workflows.add_menu", action_args={"query": "repeat"}`).
- **steps**: several things in order, one popup with **Back / Next** and a counter
  ("2 / 4"); the last step has **Close**. Each step takes the same fields as the call
  (`target`, `title`, `body`, `navigate`, `item_id`, `workflow_id`, `action`,
  `action_args`, `also`, `role`, `within`) plus `click: true` = move on when the user
  clicks the highlighted thing. Leave the top-level `target` empty when you pass steps.
  Up to 12 steps.
- Result `{ok, shown, missing, steps}`. `missing: true` = not found on screen: check the id
  with `ducky_ui_list_targets` and try again. `deferred: true` = the user turned off
  "Let Ducky show me things"; the chat button is still there.

### Spotlight in UEFN or another program

Same tool. Pass `window` and `box` instead of a panel target. It darkens every
monitor, leaves a hole on that control, and blocks every other click until they
press it, press Close, or press Esc.

```
ducky_ui_show(window="uefn", box={"x": 0.02, "y": 0.01, "w": 0.12, "h": 0.04},
  title="Compile", body="Builds your Verse.", click=true)
```

1. Open the tab first. `open_asset_in_uefn` for a Blueprint, Widget or material.
   `uefn_window_click` for a menu or a tab that is not an asset.
2. `uefn_window_capture` and look at the image.
3. `box` is `{x, y, w, h}` as fractions of that image (0 to 1), the same units as
   `uefn_window_click`. `window` is `"uefn"`, a title pattern (`"Blender"`), or an hwnd.
4. The result image has the box drawn on it. If it missed, call again with a better box.
5. `click: true` hides Next. The step moves on only when they click the hole, and
   that click reaches the real control. `steps` works the same way (all window steps,
   or all in-app steps, not a mix). `wait: true` returns `reason` (`done`, `close`,
   `esc`) and `step`.

The hole follows the window onto another monitor. Resizing keeps the box pinned to
the nearest corner. Plugins call `api.spotlight(...)` with the same fields. Workflows
use the **Spotlight** node (`ui.spotlight`), and can start from **Spotlight step**
(`spotlight.step`) or **Spotlight closed** (`spotlight.closed`).

### Where things are (routes and targets)

| The user asks about | navigate | item_id | target |
| --- | --- | --- | --- |
| Audio (mic, speakers, spoken replies) | `settings.audio` | | `settings.tab.audio` |
| Appearance, theme, sidebars | `settings.appearance` | | `settings.tab.appearance` |
| General, project files, Add to UEFN | `settings.general` | | `settings.general.project_files`, `settings.general.add_to_uefn` |
| LLM providers, API keys | `settings.llms` | provider id (`anthropic`) | `settings.llms.provider.<id>`, `settings.llms.provider.key` |
| MCP servers | `settings.mcp` | | `settings.mcp.list`, `settings.mcp.add` |
| Skill packs | `settings.skills` | | `settings.skills.row.<pack>` |
| Duckies (profiles) | `settings.duckies` | | `settings.duckies.row.<profile id>` |
| Plans | `settings.plans` | | `settings.tab.plans` |
| Languages (translation) | `settings.languages` | | `settings.languages.list` |
| A plugin in the Store (install, update, turn on/off) | `settings.store` | its slug (`meshy`) | `settings.store.detail`, `settings.store.detail.actions` |
| The Store catalog | `settings.store` | | `settings.store.catalog`, `settings.store.item.<slug>` |
| A plugin's own Settings tab | `settings.tab` | tab name (`Meshy`) | `settings.tab.<name>` (lowercase, words joined by `-`) |
| Workflows editor | `workflows` | | `workflows.list`, `workflows.canvas`, `workflows.add`, `workflows.toolbar.run` (Test), `workflows.toolbar.save`, `workflows.toolbar.onoff`, `workflows.toolbar.history`, `workflows.log`, `workflows.details`, `workflows.help` |
| A workflow node / pin / wire | (use `workflow_id`) | | `workflows.node.<id>`, `workflows.pin.<node>.<in or out>.<pin>`, `workflows.wire.<from>><to>:<route>` (data: `<from>.<pin>><to>.<pin>`), `workflows.details.field.<setting id>`, `workflows.log.step.<node>` |
| New workflow, templates | `workflows` | | `workflows.list.new`, action `workflows.templates {shelf}`, then `workflows.template.<id>`, `workflows.templates.create` |
| Add-node menu | `workflows` | | action `workflows.add_menu {query}`, then `workflows.palette.<node type>` |
| Ledger of changes | `changes` | | `header.changes` |
| Chat box | | | `chat.composer`, `chat.composer.model`, `chat.composer.mic`, `chat.composer.send` |

Workflow UI actions: `workflows.open {id}`, `workflows.select {node_ids | group_id, id}`,
`workflows.add_menu {query}`, `workflows.templates {shelf}`, `workflows.log`,
`workflows.close_overlays`.

### Examples

"Where are the audio settings?"

```
ducky_ui_show(target="settings.tab.audio", navigate="settings.audio",
  title="Audio settings", body="Pick your **microphone** and **speakers**, and how loud spoken replies are.")
```

"How do I turn on the Meshy plugin?"

```
ducky_ui_show(target="settings.store.detail.actions", navigate="settings.store", item_id="meshy",
  title="Meshy", body="Press **Install** (or the switch to turn it on). It adds text and image to 3D, rigging and animations.")
```

"What does this node do?" in a workflow:

```
ducky_ui_show(target="workflows.node.servers", workflow_id="<id>",
  title="Fortnite servers up?", body="Checks Epic's status page and waits while Fortnite is down.")
```

"How do I install Meshy and set my API key?" (several steps):

```
ducky_ui_show(steps=[
  {"target": "settings.store.detail.actions", "navigate": "settings.store", "item_id": "meshy",
   "title": "1. Install Meshy", "body": "Press **Install**.", "click": true},
  {"target": "settings.tab.meshy", "navigate": "settings.tab", "item_id": "Meshy",
   "title": "2. Its settings", "body": "Meshy's own tab appears here once it's installed."},
  {"target": "API key", "role": "text", "within": "settings.tab.meshy",
   "title": "3. Paste your key", "body": "From meshy.ai → API. It stays on this PC."}
])
```

Something with no id (a button inside a panel):

```
ducky_ui_show(target="Run this node only", role="button", title="Run just this node", body="Re-runs it with what came in last time.")
```

### Rules

- One Show me call per answer: several things go in `steps`, not several calls (a new
  one replaces the one on screen).
- Not while a `ducky_ask_user` question is open.
- `missing` → look the id up with `ducky_ui_list_targets(route, query)` before trying again.
- Never use a Show me to click for the user: they click; you show.
