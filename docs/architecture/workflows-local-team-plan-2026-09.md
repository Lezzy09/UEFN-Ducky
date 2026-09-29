# Workflows: one concept, Local or Team owned (plan, 2026-09-29)

**Status: implemented 2026-09-29, all phases (uncommitted at the time of writing).**
Owner decisions: old tool names are removed outright (no aliases); "Local" replaces
"Personal" on the plugin data bar too (display only, the scope id stays `personal`);
the 15-minute background round is in.

Owner ask: no more "Pipelines" vs "Automations". Everything is a **Workflow**. Each
workflow is **Local** (this PC only) or **Team** owned. Team workflows sync to every
member through the signed-in Ducky account. The list is split into folders by owner,
and it is always obvious which one you are looking at.

This is the desktop half of DuckyOS plan §14 ("Team workflows and automations",
`DuckyOS/duckyos/docs/plans/team-plans-private-plugins-sync.md`). **The server half is
already shipped.**

## 0. What already exists (verified in code)

| Piece | Where | State |
|---|---|---|
| Graph store, `kind` automation \| pipeline | `backend/automations/store.py`, `store/repos/automations.py` | One table, shared by every account on the PC, **not encrypted** (breaks §13) |
| Saved versions | `automations/versions.py`, `workflow_versions` table | Local, fine as is |
| Per-account, per-scope data service | `backend/uefn_plugins/scopes.py` (`PluginData`) + `store/repos/plugin_data.py` | Sealed per account (DPAPI+ADK). Scope is picked from the **project link**, one scope at a time |
| Team sync engine | `backend/uefn_plugins/team_sync.py` | Batched `team-data-sync` / `team-data-commit`, last write wins, stale push adopts the server copy, first pull before a plugin writes |
| Server rules | DuckyOS `plugin-uefn-ducky-store/src/team_data.rs` | Reserved ids `ducky.*`: pushes/deletes need **`manage_automations`**; pulls never do. Web storage table already names `ducky.automations` "Automations & workflows" |
| Permission flag | Hub returns `can.manage_automations` per team | Desktop `teams_snapshot()` **drops it** (its `perms` map has no `manage_automations`) |

Runtime gates that exist only because of `kind` (all go away in P1):

- `scheduler._tick` skips non-automation graphs (it already requires a `start.cron` node).
- `runner.emit_automation` skips pipelines (it already requires a matching trigger node).
- `runner.run_pipeline` refuses automations.
- `runner._prepare_run_ctx` sets the artifact dir and duckies group only for pipelines.
- `catalog.list_nodes(system=…)` and `templates.list_templates(system=…)` split the palette.

## 1. Decisions (recommended defaults, change any before we start)

1. **Label: "Local"**, as asked. Under the hood it is the account's Personal scope, which
   never leaves the PC. The plugin scope bar keeps saying "Personal" for now.
2. **Storage:** every workflow is one doc under the reserved host id
   `ducky.automations`, key = workflow id, in the owner's scope (Personal or a team).
   There is no new server flow, and encryption per account comes with it.
3. **Per-PC state never syncs.** This covers the run log, `last_run`, saved versions and
   "Run on this PC". It lives in a local runtime table.
4. **Team schedules and triggers run only where "Run on this PC" is on.** It is off by
   default and on for the creator. So a team cron never fires once per member.
5. **Sync load.** Rounds run while the Workflows view is open: on open, on focus and each
   minute, capped by the host at one per team per minute. That is the same rule as the
   plugin scope bar, after the 2026-09-16 outage. The only other traffic is a background
   round every 15 minutes, and only for teams where this PC has a "Run on this PC" schedule.
6. **Old tool names** (`*_pipeline`, `*_automation`) are removed outright (owner,
   2026-09-29). The plugin API (`api.emit_automation`, `register_pipeline_node`,
   manifest `automations.*`) keeps its names: published plugins use it.

## 2. Phases

### P0: icons, not emoji (DONE in this change)

- Toolbar: Undo, Redo, History (clock), Enabled (check or pause), Save, Test (play, or
  a spinner while busy), Duplicate, Delete.
- Canvas: the four controls were ambiguous (two "+" buttons next to each other). They are
  now Add node (plus), Zoom out and Zoom in (magnifiers), and Fit (frame corners).
- Sidebar "+" is now `Icons.Plus`. Node delete is `Icons.Trash`. The add-node menu uses
  CollapseAll, Arrange and Fit. The run log close button is `Icons.Close`.
- New icons in `icons/Icons.tsx`: `ZoomIn`, `ZoomOut`, `FitView`, `Arrange`.
- Still emoji, fixed in P1: the chat `/pipeline` chip (🔗 in `ChatRefChip.tsx` and
  `useChatReferenceCatalog.ts`).

### P1: one Workflow concept (no storage change, ships alone)

Backend:
- Behaviour comes from the nodes, not from `kind`:
  - it runs on a schedule if it has a `start.cron` node;
  - it runs on an event if it has a trigger node;
  - it can be referenced from chat always (the "Chat input" node stays optional);
  - it gets the artifact dir and duckies group when a caller chat exists and it has
    `pipeline.agent` or `ducky.spawn`.
- Remove the `kind` checks listed in §0. `normalize_kind` stays only to read old rows.
- One node catalog and one template list. Plugin `systems` is ignored. The plugin manifest
  keys `automations_nodes` and `automations_triggers` keep their names (plugin API).
- Risk to test: `pipeline.agent` with **no caller**, for example on a cron. Today that path
  never runs, so group creation without a leader needs a test.
- MCP tools: `list_workflows`, `get_workflow`, `save_workflow`, `delete_workflow`,
  `run_workflow`, `list_workflow_nodes`, `list_workflow_templates`. Keep `emit_automation`
  internal. The old names become unlisted aliases (decision 6).
- `backend/agent/prompt.py`, `skill_packs/ducky/SKILL.md` and
  `references/ai_plugins.md` switch to "workflow" wording and the new tool names.

Frontend:
- `AutomationsView`: remove the `WorkflowKind` state, the per-kind sections, the catalog
  switch and the `isPipeline` copy.
- `graphActivity` / `ducky:focus-graph`: one key, no `kind`.
- Chat: `/workflow:<id>`. The parser still accepts `pipeline:<id>` so old messages keep
  working. The chip uses a workflow icon, not 🔗.
- Rename "pipeline" and "automation" in the UI: `Header`, `EditorTabs`, `EditorGroupPane`,
  `BackgroundActivityDropdown`, `ChatRefChip`, `openChatReference`, `useChatReferenceCatalog`,
  `types/panel.ts`.

### P2: ownership storage

- New module `backend/automations/owners.py`, a thin layer over `plugin_data` with an
  **explicit** scope. It does not use `active_scope()`, which follows the project link;
  workflows need Local and every team at the same time.
  - `list_all()`: Personal plus each available team → `[{…summary, owner: {kind, teamId, label, readOnly, canEdit}}]`
  - `get(id)`, `save(doc, owner)`, `delete(id)`, `copy_to(id, owner)`, `move_to(id, owner)`
  - Writes go through the same seal and dirty flag as `PluginData.put`, so they get the same
    1 MB limit and read-only rules (waiting, locked, paused, **no `manage_automations`**).
- `store.py` keeps its public functions (`list_automations`, `get_automation`, …) but backs
  them with `owners`. Runner, scheduler and tools don't change.
- A local runtime table, `workflow_local(account, scope, workflow_id, runs, last_run,
  run_here)`, is created by migration `00xx_workflow_owner.sql`. `append_run` writes here and
  never marks the doc dirty.
- **Migration** of existing rows in the `automations` table:
  - Rows are moved, never copied twice. The first **signed-in** account to open Workflows
    claims them into its Personal scope, the same rule as `plugin_kv._claim_legacy`.
  - While nobody is signed in they show under Local (`_local`).
  - Versions keep their `workflow_id` and stay attached.
  - `automations.kind` is dropped after the move.
- Signed-out workflows (`_local`): after sign-in, one prompt offers to bring the N
  workflows from this PC into the account. Nothing moves silently.
- `duckyos_account.teams_snapshot()` adds `perms.manage_automations`. `scope_choices()`
  saves it on the team's sync row (new `can_automate` column) so the list can show
  read-only without a network call.

### P3: folders UI and "which one is this"

Sidebar (`aw-list`):

```
(icons shown as [pc] [team] [lock] = Icons.Monitor / Users / Lock)
Workflows                    [+]
▾ [pc] Local                 3 [+]
    Image to island   Chat · on
    DT probe          Every 5m · on
▾ [team] Team · Alpha Studio   2 [+]   ● synced 1m ago
    Playtest a mechanic   Chat · on
    Nightly build   [lock] Schedule · Run here
  Sign in to share workflows with a team   (signed out only)
```

- Folders: **Local** (Monitor icon) first, then one folder per team (Users icon). Teams
  come from the saved team rows at once, and `scope_choices()` refreshes them when the
  view opens (one hub call, never on a timer).
- Each folder shows its count, a "+" that creates the workflow in that folder, and for
  teams a sync line built with `scopeBarText.syncText` (synced / N pending / offline /
  waiting / paused). The top "+" creates in Local.
- Each row shows the name, a trigger badge worked out from the starter nodes (Chat,
  Schedule, Event, Manual), and on/off. Read-only team rows get a lock. Team schedules
  show "Run here" when that is on.
- Toolbar ownership chip, left of the name: `LOCAL` or `TEAM · Alpha Studio`, using the same
  colours as `plugin-scope-bar--personal` / `--team`. Hovering it explains who can see the
  workflow.
- Toolbar "Move / Copy to…" menu (Local ↔ any team you can edit). Moving from a team to
  Local asks first: "Members of Alpha Studio will lose this workflow."
- Read-only (no `manage_automations`, paused, or waiting): editing controls are disabled
  with the reason in their tooltip. Test/Run and Duplicate-to-Local still work.
- "Run on this PC" is a toggle in the toolbar. It is shown only for team workflows that
  have a schedule or trigger.
- Tests: the existing `AutomationsView.test.tsx` suites keep their names and are ported;
  new tests cover folders, the chip, read-only, copy/move and the signed-out hint.

### P4: team sync and runtime gates

- Workflows view: `team_sync.sync_team(account, team)` for each visible team, on open, on
  focus and every 60 s while the view is open. It reuses `setVisibleInterval`, and the
  host rate cap applies. `plugin_scope_changed` with `ducky.automations` in `plugins`
  refreshes the list.
- Scheduler and `emit_automation` run team workflows only where
  `workflow_local.run_here` is set. Local workflows run as they do today.
- There is a background round every 15 minutes, only for teams where this PC has a
  run-here schedule (decision 5).
- Stale push adopted from the server: before `_adopt` replaces a `ducky.automations`
  doc, the local copy is archived as a saved version named "Your copy before sync", so
  a lost edit can be restored from History.
- Removed from a team: `purge_team` already deletes the scope. The folder disappears
  and the `workflow_local` rows for that team are deleted too.

### P5: cleanup (next release)

- Delete the old tool aliases, the `automations.kind` reader and `pipeline:` chat parsing
  if no stored messages use it (count them first).
- Update `docs/architecture/store.md` (new doc id + runtime table).

## 3. Checks before calling it done

Matches DuckyOS §14 checks, plus the desktop ones:

1. Team workflow created by A appears for B after one round. B without `manage_automations` can
   run but not edit, and a forced push from B is refused by the server.
2. A third team never sees it. Two accounts on one Windows user never see each other's
   Local workflows, even when reading `ducky.db` directly (sealed).
3. "Run on this PC" gates cron and trigger runs. Two members with the same team cron:
   exactly one run.
4. The migration moves existing graphs once, with their versions, and a second start moves
   nothing.
5. `pipeline.agent` on a cron with no caller works.
6. Old `/pipeline:<id>` chat chips still open the workflow.
7. Offline: Local edits work, team edits queue (pending N) and push on reconnect.
8. vitest + pytest green. This includes `test_panel_api_methods.py` (method list) and
   the `test_panel_automations.py` tool tests.

## 4. Files touched (by phase)

- P1: `backend/automations/{runner,scheduler,catalog,templates,store}.py`,
  `backend/tools/panel/panel_automations.py`, `frontend/ui_web/panel_api_automations.py`,
  `backend/agent/prompt.py`, `frontend/skill_packs/ducky/**`, web `automations/*`,
  `hooks/graphActivity.ts`, `components/{Header,EditorTabs,EditorGroupPane,ChatRefChip,BackgroundActivityDropdown,useChatReferenceCatalog}.tsx`,
  `navigation/openChatReference.ts`, `types/panel.ts`.
- P2: new `backend/automations/owners.py`, `store/migrations/00xx_workflow_owner.sql`,
  `store/repos/{automations,plugin_data}.py`, `frontend/duckyos_account.py`,
  `backend/uefn_plugins/team_sync.py` (`scope_choices` saves `can_automate`).
- P3: web `automations/AutomationsView.tsx` (split out `WorkflowList.tsx` +
  `OwnerChip.tsx`), `theme/styles/automations.css`, `plugin-ui/scopeBarText.ts` (reuse).
- P4: `team_sync.py` (`_adopt` hook), `automations/{scheduler,runner}.py`.

## 5. Follow-up (2026-09-29): per-plugin data sharing, history, web views

Owner follow-up, specified as DuckyOS plan §15
(`DuckyOS/duckyos/docs/plans/team-plans-private-plugins-sync.md`):

- **App (this repo):** where a plugin's data lives is picked per plugin (Local or one
  team), no longer per project: `plugin_scopes` (migration 0013 carries old project
  links over, then drops `project_scopes`). Plugins page → a plugin → **Data** shows
  the choice, Local and team sizes, a one-way "Copy Local data into {team}", and "View
  on the web". Team workflow folders link to the web team's Workflows tab.
- **Server (DuckyOS Store plugin):** history instead of overwrite (20 changes kept per
  item), revert, and browse/list/item/history/delete events for the web.
- **Web + Ducky Account plugin:** team view gets a Shared data browser under Plugins
  and a Workflows tab, the same in both places.
