import { describe, expect, it } from "vitest";
import {
  catalogItems,
  categoryLabel,
  filterStoreItems,
  groupByTeam,
  itemCategories,
  TEAM_CATEGORY,
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

  it("filters the virtual team category to my teams' items, grouped per team", () => {
    const team = (slug: string, id: string, name: string, visibility: "public" | "private") =>
      ({ slug, kind: "plugin", name: slug, my_team: true, owner_team_id: id, owner_team_name: name, visibility }) as DuckyOSStoreItemDto;
    const withTeams: DuckyOSStoreItemDto[] = [
      ...items,
      team("zeta-tool", "t2", "Zeta", "public"),
      team("alpha-cards", "t1", "Alpha Studio", "private"),
      team("alpha-board", "t1", "Alpha Studio", "public"),
      // Another team's public item: not mine, even with a team name on it.
      { slug: "their-tool", kind: "plugin", owner_team_id: "t9", owner_team_name: "Other", visibility: "public" },
    ];
    const beta = catalogItems({ teams: true, items: withTeams });
    const mine = filterStoreItems(beta, { category: TEAM_CATEGORY });
    expect(mine.map((i) => i.slug)).toEqual(["zeta-tool", "alpha-cards", "alpha-board"]);
    expect(groupByTeam(mine).map((g) => [g.team, g.items.map((i) => i.slug)])).toEqual([
      ["Alpha Studio", ["alpha-cards", "alpha-board"]],
      ["Zeta", ["zeta-tool"]],
    ]);
    // In the beta but no team: the category is empty (the tab shows the join-a-team state).
    expect(filterStoreItems(items, { category: TEAM_CATEGORY })).toEqual([]);
    // Teams beta off (teams false or missing): nothing is a team item at all.
    for (const teams of [false, undefined]) {
      const off = catalogItems({ teams, items: withTeams });
      expect(off.filter((i) => i.my_team)).toEqual([]);
      expect(filterStoreItems(off, { category: TEAM_CATEGORY })).toEqual([]);
    }
  });

  it("notes paused Team Private under its team, even when every item is hidden", () => {
    const pip = { slug: "alpha-board", kind: "plugin", my_team: true, owner_team_id: "t1", owner_team_name: "Alpha Studio" };
    const groups = groupByTeam([pip], [
      { teamId: "t1", name: "Alpha Studio", privateActive: false, hiddenPrivate: 3 },
      { teamId: "t2", name: "Beta Crew", privateActive: false, hiddenPrivate: 1 },
      { teamId: "t3", name: "Gamma", privateActive: true, hiddenPrivate: 0 },
    ]);
    expect(groups.map((g) => [g.team, g.items.length, g.note])).toEqual([
      ["Alpha Studio", 1, "Team Private paused: 3 private plugins hidden until the owner renews."],
      ["Beta Crew", 0, "Team Private paused: 1 private plugin hidden until the owner renews."],
    ]);
    expect(groupByTeam([pip]).map((g) => g.note)).toEqual([""]); // no teamsInfo: nothing shown
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
