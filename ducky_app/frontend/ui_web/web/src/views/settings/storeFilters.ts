import type { DuckyOSStoreAudienceNote, DuckyOSStoreCatalog, DuckyOSStoreItemDto } from "../../types/panel";

/** Browse filter seeds (not install package types). Everything is a plugin — omit that bucket. */
export const CORE_STORE_CATEGORIES = ["gateways", "skills", "themes", "games"] as const;

/** Redundant browse slug — package kind already covers “plugin”; never show in the UI. */
export const HIDDEN_BROWSE_CATEGORIES = new Set(["plugins", "plugin"]);

/** Virtual category: items present on this PC (any state). */
export const INSTALLED_CATEGORY = "installed";

/** Virtual category: desktop plugins authored by duckies (`source=ai`). */
export const AI_MADE_CATEGORY = "ai-made";

/** Virtual category: items shared with the signed-in account (public or private). */
export const SHARED_CATEGORY = "shared";

const CATEGORY_LABELS: Record<string, string> = {
  skills: "Skills",
  themes: "Themes",
  gateways: "Gateways",
  games: "Games",
  mcps: "MCPs",
  "3d": "3D",
  trending: "Trending",
  shared: "Shared",
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
 * Catalog items with audiences applied: unless the catalog says `audiences: true`,
 * nothing is a shared item (no Shared category, rows or badges).
 */
export function catalogItems(catalog: DuckyOSStoreCatalog | null): DuckyOSStoreItemDto[] {
  const items = catalog?.items || [];
  if (catalog?.audiences === true) return items;
  return items.map((item) => (item.mine ? { ...item, mine: false } : item));
}

/** Shared with the viewer. The server only sets this for the item's audience. */
export function isSharedItem(item: DuckyOSStoreItemDto): boolean {
  return item.mine === true;
}

export type AudienceGroup = { key: string; label: string; items: DuckyOSStoreItemDto[]; note: string };

/**
 * Shared items grouped per audience (by id, labelled by name), sorted by name. With
 * `notes`, an audience gets its note, even when every item it has is hidden.
 */
export function groupByAudience(items: DuckyOSStoreItemDto[], notes: DuckyOSStoreAudienceNote[] = []): AudienceGroup[] {
  const groups = new Map<string, AudienceGroup>();
  for (const item of items) {
    const label = (item.audience_label || "").trim();
    const key = item.audience_id || label;
    const group = groups.get(key);
    if (group) group.items.push(item);
    else groups.set(key, { key, label, items: [item], note: "" });
  }
  for (const info of notes) {
    if (!info.id || !info.note) continue;
    const group = groups.get(info.id) ?? { key: info.id, label: info.label, items: [], note: "" };
    group.note = info.note;
    groups.set(info.id, group);
  }
  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label));
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
    } else if (category === SHARED_CATEGORY) {
      if (!isSharedItem(item)) return false;
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
