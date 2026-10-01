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
| `ducky_ui_show` | One thing: takes the user there, highlights it, popup above it with your title and body. Only its close button closes it; the chat keeps a **Show me** button that plays it again. Returns at once. |
| `ducky_walkthrough_run` | Several steps with Next / Back ("how do I set up…"). Blocks until they finish or skip. |
| `show_workflow` | Workflow nodes; with `title` (+ `body`) it is a Show me on those nodes. |
| `tour_workflow` | A whole workflow node by node; `auto=true` builds the tour from the graph. |
| `ducky_ui_list_targets(route, query, visible_only)` | Find target ids and the view's UI actions. |

Keep your chat reply to a line or two: the popup says the rest.

### `ducky_ui_show`

```
ducky_ui_show(target, title, body="", workflow_id="", navigate="", item_id="",
              action="", action_args=None, also=None, role="", within="", wait=false)
```

- **target**: an id (`settings.tab.audio`). For things with no id, give **role** and
  put the name in target: `role="button", target="Save", within="workflows.details"`;
  `role="text"` finds that text on screen. **also**: more ids shown as one highlight
  (a few nodes).
- **navigate** (+ **item_id**) opens the view first; **workflow_id** opens a workflow
  and selects `workflows.node.<id>` targets; **action** runs a UI action first
  (`action="workflows.add_menu", action_args={"query": "repeat"}`).
- Result `{ok, shown, missing}`. `missing: true` = not found on screen: check the id
  with `ducky_ui_list_targets` and try again. `deferred: true` = the user turned off
  "Let Ducky show me things"; the chat button is still there.

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

Something with no id (a button inside a panel):

```
ducky_ui_show(target="Run this node only", role="button", title="Run just this node", body="Re-runs it with what came in last time.")
```

### Rules

- One Show me per thing; a new one replaces the one on screen.
- Not while a `ducky_ask_user` question is open.
- `missing` → look the id up with `ducky_ui_list_targets(route, query)` before trying again.
- Never use a Show me to click for the user: they click; you show.
