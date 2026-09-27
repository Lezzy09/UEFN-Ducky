import { expect, it } from "vitest";
import { groupArchiveByProject } from "./DuckyArchiveDropdown";

it("groups archived duckies under the project they came from", () => {
  const groups = groupArchiveByProject([
    { id: "a", name: "NPC", projectName: "Roguelike" },
    { id: "b", name: "Group1", projectName: "Roguelike", isGroup: true },
    { id: "c", name: "Builder", projectSlug: "other-island" },
  ]);
  expect(groups.map((g) => g.project)).toEqual(["Roguelike", "other-island"]);
  expect(groups[0].chats.map((c) => c.id)).toEqual(["a", "b"]);
  expect(groups[1].chats.map((c) => c.id)).toEqual(["c"]);
});
