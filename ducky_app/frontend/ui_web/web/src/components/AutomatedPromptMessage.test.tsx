// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { vi } from "vitest";

import type { AutomatedPrompt } from "../utils/automatedPrompt";
import { AutomatedPromptMessage } from "./AutomatedPromptMessage";

const titles = vi.hoisted(() => new Map<string, string>());
vi.mock("../hooks/agentBackgroundActivity", () => ({ chatTitleFor: (id: string) => titles.get(id) || "" }));

afterEach(() => { cleanup(); titles.clear(); });

function prompt(count: number): AutomatedPrompt {
  return {
    heading: "Reports you have not acted on",
    parts: Array.from({ length: count }, (_, i) => ({
      kind: "message" as const,
      from: `Builder ${i + 1}`,
      agent: "codex",
      tag: "Message",
      body: `Long report ${i + 1}\nwith a second line`,
    })),
  };
}

function rows(container: HTMLElement) {
  return [...container.querySelectorAll(".message-bubble-automated-part, .message-bubble-automated-more")];
}

it("collapses many messages to three one-line rows, the last one naming the rest", () => {
  const { container } = render(<AutomatedPromptMessage prompt={prompt(6)} />);
  const shown = rows(container);
  expect(shown).toHaveLength(3);
  expect(container.querySelectorAll(".message-bubble-automated-part.is-compact")).toHaveLength(2);
  expect(shown[2].textContent).toBe("+4 more from Builder 3, Builder 4, Builder 5, Builder 6");
  expect(container.querySelector(".message-bubble-automated-heading")).toBeNull();
  // The phone keeps only the first row and counts the other five on it.
  expect(container.querySelector(".message-bubble-automated-count")?.textContent).toBe("+5");
  expect(container.querySelectorAll(".is-extra")).toHaveLength(2);
});

it("shows up to three messages without a summary row", () => {
  const { container } = render(<AutomatedPromptMessage prompt={prompt(3)} />);
  expect(container.querySelectorAll(".message-bubble-automated-part.is-compact")).toHaveLength(3);
  expect(container.querySelector(".message-bubble-automated-more")).toBeNull();
});

it("expands to every message in full on click", () => {
  const { container } = render(<AutomatedPromptMessage prompt={prompt(6)} />);
  fireEvent.click(container.querySelector(".message-bubble-automated")!);
  expect(container.querySelectorAll(".message-bubble-automated-part")).toHaveLength(6);
  expect(container.querySelector(".is-compact, .message-bubble-automated-more, .message-bubble-automated-count")).toBeNull();
  expect(container.querySelector(".message-bubble-automated-heading")?.textContent).toBe("Reports you have not acted on");
});

it("names each hidden sender once", () => {
  const twice = prompt(5);
  twice.parts[3].from = "Builder 3";
  const { container } = render(<AutomatedPromptMessage prompt={twice} />);
  expect(container.querySelector(".message-bubble-automated-more")?.textContent).toBe("+3 more from Builder 3, Builder 5");
});

it("names the sender by its chat's current title, not the profile it was made from", () => {
  titles.set("lead-chat", "Video Plugin Lead");
  const named = prompt(1);
  named.parts[0] = { ...named.parts[0], from: "Verse Coder", fromConvId: "lead-chat" };
  const { container } = render(<AutomatedPromptMessage prompt={named} />);
  expect(container.querySelector(".message-bubble-automated-from")?.textContent).toBe("Video Plugin Lead");
});
