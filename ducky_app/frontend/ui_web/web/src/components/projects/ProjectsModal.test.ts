import { expect, it } from "vitest";
import { openedLabel, visibleProjects } from "./ProjectsModal";
import type { KnownProject } from "../../types/panel";

const row = (name: string, source: string, last_opened = 0): KnownProject => ({
  name,
  path: `C:/${name}`,
  slug: name,
  source,
  last_opened,
  active: false,
});

const rows = [row("Tycoony", "uefn", 30), row("CardGame", "uefn"), row("Roguelike", "uefn", 50), row("DuckyOS", "other", 10)];

it("keeps each tab to its own projects", () => {
  expect(visibleProjects(rows, "uefn", "", "name").map((r) => r.name)).toEqual(["CardGame", "Roguelike", "Tycoony"]);
  expect(visibleProjects(rows, "other", "", "name").map((r) => r.name)).toEqual(["DuckyOS"]);
});

it("puts opened projects first, newest first, then never-opened ones by name", () => {
  expect(visibleProjects(rows, "uefn", "", "recent").map((r) => r.name)).toEqual(["Roguelike", "Tycoony", "CardGame"]);
});

it("searches names and paths", () => {
  expect(visibleProjects(rows, "uefn", "card", "recent").map((r) => r.name)).toEqual(["CardGame"]);
  expect(visibleProjects(rows, "uefn", "zzz", "recent")).toEqual([]);
});

it("says when a project was opened like a launcher does", () => {
  const now = Date.UTC(2026, 9, 22, 12);
  const ago = (hours: number) => (now - hours * 3_600_000) / 1000;
  expect(openedLabel(0, now)).toBe("Never opened in Ducky");
  expect(openedLabel(ago(2), now)).toBe("Opened 2 hours ago");
  expect(openedLabel(ago(24 * 4), now)).toBe("Opened 4 days ago");
  expect(openedLabel(ago(24 * 8), now)).toBe("Opened last week");
  expect(openedLabel(ago(24 * 21), now)).toBe("Opened 3 weeks ago");
  expect(openedLabel(ago(24 * 40), now)).toBe("Opened last month");
});
