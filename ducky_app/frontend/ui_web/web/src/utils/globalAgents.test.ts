import { expect, it } from "vitest";
import { pickAgentChatForProfile, pickChatForGlobalAgent, type GlobalAgentChat } from "./globalAgents";

const level: GlobalAgentChat = {
  id: "here",
  name: "Level Designer",
  profileId: "level-designer",
  projectSlug: "island",
  updated: 2,
};

it("opens this island's chat that still uses the agent name", () => {
  const renamed: GlobalAgentChat = {
    id: "renamed",
    name: "General Helper",
    profileId: "level-designer",
    projectSlug: "island",
    updated: 9,
  };
  const otherIsland: GlobalAgentChat = {
    ...level,
    id: "elsewhere",
    projectSlug: "other",
    updated: 99,
  };
  expect(
    pickChatForGlobalAgent([renamed, otherIsland, level], { id: "level-designer", name: "Level Designer" }, "island"),
  ).toEqual({ id: "here", name: "Level Designer" });
});

it("opens the agent chat for a profile, including one on another island", () => {
  expect(
    pickAgentChatForProfile(
      [
        { id: "profile-tab-not-this", title: "Verse Coder", profile_id: "verse-coder", project_slug: "other", updated: 4 },
        { id: "here", title: "Verse Coder", profile_id: "verse-coder", project_slug: "island", updated: 1 },
      ],
      "verse-coder",
      "Verse Coder",
      "island",
    ),
  ).toEqual({ id: "here", name: "Verse Coder" });
  expect(
    pickAgentChatForProfile(
      [{ id: "away", title: "Verse Coder", profile_id: "verse-coder", project_slug: "other", updated: 3 }],
      "verse-coder",
      "Verse Coder",
      "island",
    )?.id,
  ).toBe("away");
});

it("skips groups and a different profile", () => {
  const group: GlobalAgentChat = { ...level, id: "hub", isGroup: true, updated: 50 };
  const other: GlobalAgentChat = { ...level, id: "verse", profileId: "verse-coder", name: "Verse Coder" };
  expect(pickChatForGlobalAgent([group, other], { id: "level-designer", name: "Level Designer" }, "island")).toBeNull();
});
