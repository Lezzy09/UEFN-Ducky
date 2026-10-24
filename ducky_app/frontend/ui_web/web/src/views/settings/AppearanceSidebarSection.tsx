import type { ReactNode } from "react";
import { SettingsToggleRow } from "./SettingsToggleRow";
import { AppearanceAccordionSplit } from "./AppearanceAccordionSplit";
import { useDockSidePanelMode } from "../../hooks/useDockSidePanelMode";
import { useDockSidebarSettings } from "../../hooks/useDockSidebarSettings";
import { usePluginContributions } from "../../hooks/usePluginContributions";
import { resolvePluginHeaderIcon } from "../../hooks/pluginHeaderActions";
import { DOCK_PANEL_TAB_META, dockPanelTabMeta } from "../../workspace/dockPanelTabMeta";
import {
  panelsOnSide,
  sidebarPanelCatalog,
  type DockPanelId,
  type DockPanelMode,
  type DockSide,
} from "../../workspace/workspaceDockStorage";

const SIDE_NAME: Record<DockSide, string> = { left: "Left", right: "Right" };

function PanelSideLayoutControl({ side, disabled }: { side: DockSide; disabled: boolean }) {
  const { mode, setMode } = useDockSidePanelMode(side);
  const label = `${SIDE_NAME[side]} panel layout`;

  return (
    <div className={`appearance-layout-control${disabled ? " is-disabled" : ""}`}>
      <div
        className="content-search-mode-toggle appearance-layout-toggle"
        role="group"
        aria-label={label}
        title={disabled ? `The ${side} sidebar is off` : undefined}
      >
        {(["tabs", "stacked"] as DockPanelMode[]).map((next) => (
          <button
            key={next}
            type="button"
            className={`content-search-mode-btn${mode === next ? " is-active" : ""}`}
            aria-pressed={mode === next}
            disabled={disabled}
            onClick={() => {
              if (next !== mode) setMode(next);
            }}
          >
            {next === "tabs" ? "Tabs" : "Stacked panels"}
          </button>
        ))}
      </div>
    </div>
  );
}

function RailPreview({
  side,
  mode,
  enabled,
  labels,
}: {
  side: DockSide;
  mode: DockPanelMode;
  enabled: boolean;
  labels: string[];
}) {
  const [first = "Empty", second] = labels;
  const label = `${SIDE_NAME[side]} sidebar`;
  const disabledClass = enabled ? "" : " is-disabled";

  return (
    <div className="appearance-layout-preview-block">
      <span className="appearance-layout-preview-caption">{label}</span>
      <div
        className={`appearance-layout-preview-frame appearance-layout-preview-sidebar appearance-layout-preview-sidebar--${mode}${disabledClass}`}
      >
        {!enabled ? (
          <div className="appearance-layout-preview-panel-body">
            <span className="appearance-layout-preview-stack-label">Hidden</span>
          </div>
        ) : mode === "tabs" ? (
          <>
            <div className="appearance-layout-preview-panel-tabs">
              <span className="is-active">{first}</span>
              {second ? <span>{second}</span> : null}
            </div>
            <div className="appearance-layout-preview-panel-body">
              <span className="appearance-layout-preview-line" />
              <span className="appearance-layout-preview-line short" />
              <span className="appearance-layout-preview-line" />
            </div>
          </>
        ) : (
          <div className="appearance-layout-preview-stack">
            <div className="appearance-layout-preview-stack-pane">
              <span className="appearance-layout-preview-stack-label">{first}</span>
              <span className="appearance-layout-preview-line" />
              <span className="appearance-layout-preview-line short" />
            </div>
            {second ? (
              <>
                <div className="appearance-layout-preview-stack-divider" />
                <div className="appearance-layout-preview-stack-pane">
                  <span className="appearance-layout-preview-stack-label">{second}</span>
                  <span className="appearance-layout-preview-line" />
                </div>
              </>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function AppearanceSidebarPreview({
  catalog,
  titles,
}: {
  catalog: DockPanelId[];
  titles: Record<string, string>;
}) {
  const { snapshot, leftRailEnabled, rightRailEnabled } = useDockSidebarSettings();
  const { mode: leftMode } = useDockSidePanelMode("left");
  const { mode: rightMode } = useDockSidePanelMode("right");
  // The first two panels on a rail that exist here (a removed plugin's panel does not show), each named once.
  const labels = (side: DockSide) =>
    panelsOnSide(snapshot, side)
      .filter((id) => catalog.includes(id))
      .slice(0, 2)
      .map((id) => dockPanelTabMeta(id, titles[id]).headerTitle);

  return (
    <div className="appearance-live-preview">
      <div className="appearance-live-preview-label">Live preview</div>
      <RailPreview side="left" mode={leftMode} enabled={leftRailEnabled} labels={labels("left")} />
      <RailPreview side="right" mode={rightMode} enabled={rightRailEnabled} labels={labels("right")} />
    </div>
  );
}

/** A rail's on switch with its layout under it; the layout cannot change while the rail is off. */
function SidebarRailBlock({ side, catalog }: { side: DockSide; catalog: DockPanelId[] }) {
  const { snapshot, setRailEnabled, leftRailEnabled, rightRailEnabled } = useDockSidebarSettings();
  const enabled = side === "left" ? leftRailEnabled : rightRailEnabled;
  // On, but nothing to show (every panel Off or on the other side): its header button stays grey.
  const empty = enabled && !panelsOnSide(snapshot, side).some((id) => catalog.includes(id));

  return (
    <div className="appearance-sidebar-rail">
      <SettingsToggleRow
        id={`appearance-sidebar-enable-${side}`}
        label={`${SIDE_NAME[side]} sidebar`}
        description="When off, this rail and its panels are hidden, and so is its header button."
        checked={enabled}
        onChange={(on) => setRailEnabled(side, on)}
      />
      {empty ? (
        <p className="appearance-sidebar-rail-empty" role="note">
          Nothing is on this sidebar, so its header button is greyed out. Set a panel to {SIDE_NAME[side]} under
          Panels below.
        </p>
      ) : null}
      <PanelSideLayoutControl side={side} disabled={!enabled} />
    </div>
  );
}

const PLACEMENTS: Array<DockSide | null> = [null, "left", "right"];

/** Every panel once: its icon, its name, and where it shows (Off, Left or Right). */
function PanelPlacementList({
  catalog,
  titles,
  icons,
}: {
  catalog: DockPanelId[];
  titles: Record<string, string>;
  icons: Record<string, ReactNode>;
}) {
  const { placementOf, setPanelOnSide, leftRailEnabled, rightRailEnabled } = useDockSidebarSettings();
  const railOn = (side: DockSide) => (side === "left" ? leftRailEnabled : rightRailEnabled);

  return (
    <div className="general-tab-toggle-card appearance-sidebar-panel-list">
      {catalog.map((id) => {
        const meta = dockPanelTabMeta(id, titles[id]);
        const at = placementOf(id);
        const hiddenByRail = at !== null && !railOn(at);
        return (
          <div key={id} className="general-tab-toggle-row appearance-sidebar-panel-row">
            <span className="appearance-sidebar-panel-icon" aria-hidden>
              {icons[id] ?? meta.icon}
            </span>
            <div className="general-tab-toggle-row-text">
              <span className="general-tab-toggle-label">{meta.headerTitle}</span>
              {hiddenByRail ? (
                <p className="general-tab-toggle-desc">Hidden while the {at} sidebar is off.</p>
              ) : null}
            </div>
            <div
              className="content-search-mode-toggle appearance-sidebar-panel-sides"
              role="group"
              aria-label={`Where ${meta.headerTitle} shows`}
            >
              {PLACEMENTS.map((side) => {
                const active = at === side;
                const blocked = side !== null && !railOn(side) && !active;
                return (
                  <button
                    key={side ?? "off"}
                    type="button"
                    className={`content-search-mode-btn${active ? " is-active" : ""}`}
                    aria-pressed={active}
                    disabled={blocked}
                    title={blocked ? `The ${side} sidebar is off` : undefined}
                    onClick={() => {
                      if (!active) setPanelOnSide(id, side);
                    }}
                  >
                    {side ? SIDE_NAME[side] : "Off"}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function AppearanceSidebarSectionBlock() {
  const contrib = usePluginContributions();
  const catalog = sidebarPanelCatalog(contrib.dock_panels.map((panel) => panel.id));
  const titles = Object.fromEntries(
    contrib.dock_panels.map((panel) => [panel.id, panel.title || panel.id]),
  );
  // Plugin panels show their plugin's icon; built-in panels keep their own.
  const icons = Object.fromEntries(
    contrib.dock_panels
      .filter((panel) => panel.icon && !DOCK_PANEL_TAB_META[panel.id])
      .map((panel) => [panel.id, resolvePluginHeaderIcon(panel.icon)]),
  );

  return (
    <AppearanceAccordionSplit preview={<AppearanceSidebarPreview catalog={catalog} titles={titles} />}>
      <div className="appearance-layout-controls">
        <div className="appearance-sidebar-rails">
          <SidebarRailBlock side="left" catalog={catalog} />
          <SidebarRailBlock side="right" catalog={catalog} />
        </div>
        <div className="appearance-sidebar-panels">
          <h4 className="appearance-category-title">Panels</h4>
          <p className="appearance-layout-control-desc">
            Pick where each panel shows. Tabs show one panel of a sidebar at a time; stacked shows them all,
            split by dividers you can drag.
          </p>
          <PanelPlacementList catalog={catalog} titles={titles} icons={icons} />
        </div>
      </div>
    </AppearanceAccordionSplit>
  );
}
