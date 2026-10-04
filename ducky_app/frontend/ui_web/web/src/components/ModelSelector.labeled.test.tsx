// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ModelSelector } from "./ModelSelector";

afterEach(cleanup);

/** Workflow node details: the model field names the model in words, not just a logo. */
describe("ModelSelector labeled", () => {
  it("says what to do when nothing is picked", () => {
    render(<ModelSelector selectedModel="" setSelectedModel={() => undefined} labeled placeholder="The app's default model" />);
    const button = screen.getByRole("button", { name: /^Model:/ });
    expect(button.textContent).toContain("The app's default model");
    expect(button.textContent).toContain("Click to pick a model");
  });

  it("names the picked model", () => {
    render(<ModelSelector selectedModel="composer-2.5" setSelectedModel={() => undefined} labeled preserveSelection />);
    expect(screen.getByRole("button", { name: /^Model:/ }).textContent).toContain("composer-2.5");
  });

  it("stays a logo button in the chat composer", () => {
    render(<ModelSelector selectedModel="" setSelectedModel={() => undefined} />);
    expect(screen.queryByRole("button", { name: /^Model:/ })).toBeNull();
  });
});
