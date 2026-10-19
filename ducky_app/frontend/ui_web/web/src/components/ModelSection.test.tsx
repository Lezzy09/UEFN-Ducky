// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ModelSection, isSectionCollapsed } from "./ModelSection";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

/** A gateway's API and coding-agent lists fold, and the fold is remembered per gateway. */
describe("ModelSection", () => {
  it("folds on click and remembers it for that gateway and section", () => {
    const { unmount } = render(
      <ModelSection storageKey="openai:api" label="API" meta={<span>40</span>}>
        <div>whisper-1</div>
      </ModelSection>,
    );
    expect(screen.getByText("whisper-1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /API/ }));
    expect(screen.queryByText("whisper-1")).toBeNull();
    expect(screen.getByRole("button", { name: /API/ }).getAttribute("aria-expanded")).toBe("false");
    expect(isSectionCollapsed("openai:api")).toBe(true);
    expect(isSectionCollapsed("anthropic:api")).toBe(false);
    unmount();
    render(
      <ModelSection storageKey="openai:api" label="API">
        <div>whisper-1</div>
      </ModelSection>,
    );
    expect(screen.queryByText("whisper-1")).toBeNull(); // still folded after reopening the picker
  });

  it("stays open while searching", () => {
    window.localStorage.setItem("ducky.modelPicker.sections", JSON.stringify({ "openai:codex": true }));
    render(
      <ModelSection storageKey="openai:codex" label="Codex" forceOpen>
        <div>GPT-6.1-Sol</div>
      </ModelSection>,
    );
    expect(screen.getByText("GPT-6.1-Sol")).toBeTruthy();
  });

  it("folds even when it holds the picked model, and the folded header shows a check", () => {
    render(
      <ModelSection storageKey="anthropic:api" label="API" holdsPick>
        <div>Claude Opus 5.5</div>
      </ModelSection>,
    );
    expect(screen.queryByTitle("Your model is in here")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /API/ }));
    expect(screen.queryByText("Claude Opus 5.5")).toBeNull();
    expect(screen.getByTitle("Your model is in here")).toBeTruthy();
    expect(isSectionCollapsed("anthropic:api")).toBe(true);
  });
});
