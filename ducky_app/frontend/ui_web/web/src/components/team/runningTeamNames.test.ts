import { expect, it } from "vitest";

import type { FolderItem } from "../../types/panel";
import { runningTeamNames } from "./teamRoster";

const folder = (id: string, chats: FolderItem["chats"], children: FolderItem[] = []): FolderItem =>
  ({ id, name: id, parentId: "", sortOrder: 0, expanded: true, groupHubId: `${id}-hub`, chats, children });

it("names the running agents in a leader's group and its nested groups", () => {
  const tree = [
    folder("team", [{ id: "lead", name: "Lead", isLeader: true }, { id: "a", name: "A" }, { id: "b", name: "B" }], [
      folder("ui", [{ id: "c", name: "C", isLeader: true }]),
    ]),
  ];
  const running = new Set(["a", "c", "lead"]);
  expect(runningTeamNames("lead", tree, running)).toEqual(["A", "C"]);
  // A nested group's leader waits only on its own group; a plain member waits on nobody.
  expect(runningTeamNames("c", tree, new Set(["a"]))).toEqual([]);
  expect(runningTeamNames("a", tree, running)).toEqual([]);
});
