import { expect, it } from "vitest";
import { viewForHistory } from "./NavigationHistoryContext";

it("keeps a project on the chat workspace", () => {
  expect(viewForHistory("settings", true)).toBe("chat");
  expect(viewForHistory("chat", true)).toBe("chat");
});

it("still opens the welcome settings page when no project is open", () => {
  expect(viewForHistory("settings", false)).toBe("settings");
  expect(viewForHistory("chat", false)).toBe("chat");
});
