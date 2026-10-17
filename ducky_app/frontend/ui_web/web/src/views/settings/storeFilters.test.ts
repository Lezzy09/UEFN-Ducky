import { describe, expect, it } from "vitest";
import {
  catalogItems,
  categoryLabel,
  filterStoreItems,
  groupByAudience,
  itemCategories,
  SHARED_CATEGORY,
} from "./storeFilters";
import type { DuckyOSStoreItemDto } from "../../types/panel";

const items: DuckyOSStoreItemDto[] = [
  {
    slug: "galaxy",
    kind: "plugin",
    category: "plugins",
    categories: ["themes"],
    tags: ["space", "hud"],
    name: "Galaxy Craft",
    description: "Terran HUD",
  },
  {
    slug: "verse-tips",
    kind: "skill",
    category: "skills",
    categories: ["skills"],
    tags: ["api"],
    name: "Verse Tips",
    description: "Digest helpers",
  },
  {
    slug: "discord",
    kind: "plugin",
    category: "plugins",
    categories: ["plugins"],
    tags: ["chat"],
    name: "Discord",
    description: "Bot bridge",
  },
  {
    slug: "theme-plugin",
    kind: "plugin",
    category: "plugins",
    categories: ["themes", "plugins"],
    tags: [],
    name: "Hybrid",
    description: "Theme with tools",
  },
];

describe("filterStoreItems", () => {
  it("filters by category plugins", () => {
    expect(filterStoreItems(items, { category: "plugins" }).map((i) => i.slug)).toEqual([
      "discord",
      "theme-plugin",
    ]);
  });

  it("filters by category themes", () => {
    expect(filterStoreItems(items, { category: "themes" }).map((i) => i.slug)).toEqual([
      "galaxy",
      "theme-plugin",
    ]);
  });

  it("filters by category skills", () => {
    expect(filterStoreItems(items, { category: "skills" }).map((i) => i.slug)).toEqual([
      "verse-tips",
    ]);
  });

  it("searches name description tags and categories", () => {
    expect(filterStoreItems(items, { q: "hud" }).map((i) => i.slug)).toEqual(["galaxy"]);
    expect(filterStoreItems(items, { q: "digest" }).map((i) => i.slug)).toEqual(["verse-tips"]);
    expect(filterStoreItems(items, { q: "chat" }).map((i) => i.slug)).toEqual(["discord"]);
  });

  it("combines category and search", () => {
    expect(
      filterStoreItems(items, { category: "plugins", q: "bot" }).map((i) => i.slug),
    ).toEqual(["discord"]);
  });

  it("filters by the virtual installed category", () => {
    const withInstalled = items.map((item) =>
      item.slug === "discord" ? { ...item, installed_version: 3 } : item,
    );
    expect(
      filterStoreItems(withInstalled, { category: "installed" }).map((i) => i.slug),
    ).toEqual(["discord"]);
    expect(
      filterStoreItems(withInstalled, { category: "installed", q: "galaxy" }),
    ).toEqual([]);
  });

  it("filters the virtual Shared category to items shared with me, grouped per audience", () => {
    const shared = (slug: string, id: string, label: string, visibility: "public" | "private") =>
      ({ slug, kind: "plugin", name: slug, mine: true, audience_id: id, audience_label: label, visibility }) as DuckyOSStoreItemDto;
    const withShared: DuckyOSStoreItemDto[] = [
      ...items,
      shared("zeta-tool", "s2", "Zeta", "public"),
      shared("alpha-cards", "s1", "Alpha Studio", "private"),
      shared("alpha-board", "s1", "Alpha Studio", "public"),
      // Someone else's public item: not mine, even with an audience on it.
      { slug: "their-tool", kind: "plugin", audience_id: "s9", audience_label: "Other", visibility: "public" },
    ];
    const on = catalogItems({ audiences: true, items: withShared });
    const mine = filterStoreItems(on, { category: SHARED_CATEGORY });
    expect(mine.map((i) => i.slug)).toEqual(["zeta-tool", "alpha-cards", "alpha-board"]);
    expect(groupByAudience(mine).map((g) => [g.label, g.items.map((i) => i.slug)])).toEqual([
      ["Alpha Studio", ["alpha-cards", "alpha-board"]],
      ["Zeta", ["zeta-tool"]],
    ]);
    // Audiences on but nothing shared: the category is empty (the tab shows the empty state).
    expect(filterStoreItems(items, { category: SHARED_CATEGORY })).toEqual([]);
    // Audiences off (false or missing): nothing is a shared item at all.
    for (const audiences of [false, undefined]) {
      const off = catalogItems({ audiences, items: withShared });
      expect(off.filter((i) => i.mine)).toEqual([]);
      expect(filterStoreItems(off, { category: SHARED_CATEGORY })).toEqual([]);
    }
  });

  it("puts each audience's note under it, even when every item is hidden", () => {
    const pip = { slug: "alpha-board", kind: "plugin", mine: true, audience_id: "s1", audience_label: "Alpha Studio" };
    const groups = groupByAudience([pip], [
      { id: "s1", label: "Alpha Studio", note: "3 private plugins hidden." },
      { id: "s2", label: "Beta Crew", note: "1 private plugin hidden." },
      { id: "s3", label: "Gamma", note: "" },
    ]);
    expect(groups.map((g) => [g.label, g.items.length, g.note])).toEqual([
      ["Alpha Studio", 1, "3 private plugins hidden."],
      ["Beta Crew", 0, "1 private plugin hidden."],
    ]);
    expect(groupByAudience([pip]).map((g) => g.note)).toEqual([""]); // no notes: nothing shown
  });

  it("falls back empty categories to package bucket", () => {
    expect(
      itemCategories({ slug: "x", kind: "plugin", categories: [] }),
    ).toEqual(["plugins"]);
    expect(
      itemCategories({ slug: "y", kind: "skill", categories: [] }),
    ).toEqual(["skills"]);
  });

  it("formats browse category labels", () => {
    expect(categoryLabel("skills")).toBe("Skills");
    expect(categoryLabel("3d")).toBe("3D");
    expect(categoryLabel("mcps")).toBe("MCPs");
    expect(categoryLabel("sound-packs")).toBe("Sound Packs");
  });
});
