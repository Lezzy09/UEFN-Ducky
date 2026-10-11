import { expect, it } from "vitest";
import { archivedInsideCount, buildArchiveTree } from "./DuckyArchiveDropdown";

const chats = [
  { id: "a", name: "NPC", projectName: "Roguelike" },
  { id: "g", name: "Group1", projectName: "Roguelike", isGroup: true },
  { id: "inner", name: "Inner", projectName: "Roguelike", isGroup: true, parentConvId: "g" },
  { id: "m1", name: "3D Modeler", projectName: "Roguelike", parentConvId: "g" },
  { id: "m2", name: "Verifier", projectName: "Roguelike", parentConvId: "inner" },
  { id: "c", name: "Builder", projectSlug: "other-island" },
  // A ducky whose group was not archived with it stays a row of its own.
  { id: "orphan", name: "Helper", projectName: "Roguelike", parentConvId: "still-active-group" },
];

it("groups archived duckies per project, each group with what was archived with it", () => {
  const sections = buildArchiveTree(chats);
  expect(sections.map((s) => s.project)).toEqual(["Roguelike", "other-island"]);
  const [rogue, other] = sections;
  expect(rogue.nodes.map((n) => n.chat.id)).toEqual(["a", "g", "orphan"]);
  const group = rogue.nodes[1];
  // Duckies first, nested groups after them, like the sidebar.
  expect(group.children.map((n) => n.chat.id)).toEqual(["m1", "inner"]);
  expect(group.children[1].children.map((n) => n.chat.id)).toEqual(["m2"]);
  expect(other.nodes.map((n) => n.chat.id)).toEqual(["c"]);
});

it("counts everything a group takes along", () => {
  expect(archivedInsideCount(chats, "g")).toBe(3);
  expect(archivedInsideCount(chats, "inner")).toBe(1);
  expect(archivedInsideCount(chats, "a")).toBe(0);
  expect(archivedInsideCount(chats, "missing")).toBe(0);
});

it("files no-island duckies under Global Agents, like the sidebar", () => {
  const [section] = buildArchiveTree([{ id: "x", name: "Lead", projectSlug: "_no_project", projectName: "No project" }]);
  expect(section.project).toBe("Global Agents");
});
