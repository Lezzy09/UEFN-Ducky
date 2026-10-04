// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MobileTabSwitcher } from "./MobileTabSwitcher";
import type { EditorTab } from "../types/panel";

afterEach(cleanup);

const tabs = [
  { id: "chat:1", kind: "chat", name: "New ducky3", chatId: "1" },
  { id: "workflows:main", kind: "workflows", name: "Workflows" },
] as EditorTab[];

/** Phones: the editor's tabs are one dropdown in the header. */
describe("MobileTabSwitcher", () => {
  it("names the open tab and switches or closes tabs from its list", () => {
    const onActivate = vi.fn();
    const onClose = vi.fn();
    render(<MobileTabSwitcher tabs={tabs} activeTabId="workflows:main" onActivate={onActivate} onClose={onClose} />);
    const trigger = screen.getByRole("button", { name: "Tabs: Workflows (2 open)" });
    expect(trigger.textContent).toContain("Workflows");
    fireEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Workflows" }).getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByRole("menuitem", { name: "New ducky3" }));
    expect(onActivate).toHaveBeenCalledWith("chat:1");
    expect(screen.queryByRole("menu")).toBeNull();  // a pick closes it
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Close New ducky3" }));
    expect(onClose).toHaveBeenCalledWith("chat:1");
  });

  it("shows nothing without tabs", () => {
    const { container } = render(<MobileTabSwitcher tabs={[]} activeTabId={null} onActivate={() => undefined} onClose={() => undefined} />);
    expect(container.textContent).toBe("");
  });
});
