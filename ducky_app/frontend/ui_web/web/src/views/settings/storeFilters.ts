import type { DuckyOSStoreCatalog, DuckyOSStoreItemDto, DuckyOSStoreTeamInfo } from "../../types/panel";

/** Browse filter seeds (not install package types). Everything is a plugin — omit that bucket. */
export const CORE_STORE_CATEGORIES = ["gateways", "skills", "themes", "games"] as const;

/** Redundant browse slug — package kind already covers “plugin”; never show in the UI. */
export const HIDDEN_BROWSE_CATEGORIES = new Set(["plugins", "plugin"]);

/** Virtual category: items present on this PC (any state). */
export const INSTALLED_CATEGORY = "installed";

/** Virtual category: desktop plugins authored by duckies (`source=ai`). */
export const AI_MADE_CATEGORY = "ai-made";

/** Virtual category: items owned by the signed-in account's teams (public or private). */
export const TEAM_CATEGORY = "team";

const CATEGORY_LABELS: Record<string, string> = {
  skills: "Skills",
  themes: "Themes",
  gateways: "Gateways",
  games: "Games",
  mcps: "MCPs",
  "3d": "3D",
  trending: "Trending",
  team: "Team",
  installed: "Installed",
  "ai-made": "AI-made",
};

/** Nice Title Case (or acronym) label for a category slug. */
export function categoryLabel(raw: string): string {
  const key = String(raw || "")
    .trim()
    .toLowerCase();
  if (!key) return "";
  if (CATEGORY_LABELS[key]) return CATEGORY_LABELS[key]!;
  return key
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * Catalog items with the teams beta applied: unless the catalog says `teams: true`,
 * nothing is a team item (no Team category, rows or badges).
 */
export function catalogItems(catalog: DuckyOSStoreCatalog | null): DuckyOSStoreItemDto[] {
  const items = catalog?.items || [];
  if (catalog?.teams === true) return items;
  return items.map((item) => (item.my_team ? { ...item, my_team: false } : item));
}

/** Owned by one of the viewer's teams. The server only sets this for members. */
export function isTeamItem(item: DuckyOSStoreItemDto): boolean {
  return item.my_team === true;
}

export type TeamGroup = { key: string; team: string; items: DuckyOSStoreItemDto[]; note: string };

/** Same words as the web Store. */
export function pausedNote(hidden: number): string {
  return `Team Private paused: ${hidden} private plugin${hidden === 1 ? "" : "s"} hidden until the owner renews.`;
}

/**
 * Team items grouped per owning team (by id, labelled by name), teams sorted by
 * name. With `teamsInfo`, a team whose Team Private is paused gets its note, even
 * when every item it has is hidden.
 */
export function groupByTeam(items: DuckyOSStoreItemDto[], teamsInfo: DuckyOSStoreTeamInfo[] = []): TeamGroup[] {
  const groups = new Map<string, TeamGroup>();
  for (const item of items) {
    const team = (item.owner_team_name || "").trim();
    const key = item.owner_team_id || team;
    const group = groups.get(key);
    if (group) group.items.push(item);
    else groups.set(key, { key, team, items: [item], note: "" });
  }
  for (const info of teamsInfo) {
    const hidden = info.hiddenPrivate ?? 0;
    if (!info.teamId || hidden <= 0) continue;
    const group = groups.get(info.teamId) ?? { key: info.teamId, team: info.name, items: [], note: "" };
    group.note = pausedNote(hidden);
    groups.set(info.teamId, group);
  }
  return [...groups.values()].sort((a, b) => a.team.localeCompare(b.team));
}

/**
 * Present on this PC. ``state`` counts too — keying only on installed_version
 * made the Installed row depend on version formatting, so string-versioned
 * plugins dropped out of it on every local patch.
 */
export function isInstalledItem(item: DuckyOSStoreItemDto): boolean {
  return item.installed_version != null || item.state === "installed" || item.state === "update";
}

export function asLabelList(raw: string[] | undefined | null): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((x) => String(x || "").trim()).filter(Boolean);
}

/** Install package type (plugin zip vs skill pack) — not a browse filter. */
export function itemKind(item: DuckyOSStoreItemDto): "plugin" | "skill" | string {
  const kind = (item.kind || item.category || "skill").toLowerCase();
  if (kind === "plugin" || kind === "plugins" || kind === "feature" || kind === "features") {
    return "plugin";
  }
  if (kind === "skill" || kind === "skills" || kind === "") return "skill";
  return kind;
}

/** Browse categories (multi). Falls back to package bucket when empty. */
export function itemCategories(item: DuckyOSStoreItemDto): string[] {
  const cats = asLabelList(item.categories).map((c) => c.toLowerCase());
  if (cats.length) return cats;
  return itemKind(item) === "plugin" ? ["plugins"] : ["skills"];
}

export function filterStoreItems(
  items: DuckyOSStoreItemDto[],
  opts: { q?: string; category?: string },
): DuckyOSStoreItemDto[] {
  const q = (opts.q || "").trim().toLowerCase();
  const category = (opts.category || "").trim().toLowerCase();
  return items.filter((item) => {
    const cats = itemCategories(item);
    const tags = asLabelList(item.tags).map((t) => t.toLowerCase());
    if (category === INSTALLED_CATEGORY) {
      if (!isInstalledItem(item)) return false;
    } else if (category === AI_MADE_CATEGORY) {
      if ((item.source || "").toLowerCase() !== "ai") return false;
    } else if (category === TEAM_CATEGORY) {
      if (!isTeamItem(item)) return false;
    } else if (category && !cats.includes(category)) return false;
    if (!q) return true;
    const hay = [
      item.name,
      item.description,
      item.slug,
      ...cats,
      ...tags,
      ...(item.contributes_summary || []),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}
