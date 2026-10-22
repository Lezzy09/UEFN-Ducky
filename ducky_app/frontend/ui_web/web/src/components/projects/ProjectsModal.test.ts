import { expect, it } from "vitest";
import { visibleProjects } from "./ProjectsModal";
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
