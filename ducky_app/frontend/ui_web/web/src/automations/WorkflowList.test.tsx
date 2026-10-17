// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WorkflowList } from "./WorkflowList";
import type { AutomationSummaryDto, WorkflowOwnerDto } from "../types/panel";

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => ({}) }));

const LOCAL: WorkflowOwnerDto = { id: "local", kind: "local", label: "Local", readOnly: false };
const ALPHA: WorkflowOwnerDto = { id: "spaceA", kind: "shared", label: "Alpha", readOnly: false };
const BETA: WorkflowOwnerDto = { id: "spaceB", kind: "shared", label: "Beta", readOnly: true, reason: "No permission" };

const row = (id: string, folder: string, owner = LOCAL): AutomationSummaryDto =>
  ({ id, name: id, enabled: true, folder, owner, trigger: { kind: "manual", label: "Manual" } }) as AutomationSummaryDto;

function renderList(onCopyFolder = vi.fn(), rows = [row("Main", "Kit"), row("Helper", "Kit/Lib"), row("Loose", "")]) {
  render(
    <WorkflowList listId="list" listRef={{ current: null }} owners={{ owners: [LOCAL, ALPHA, BETA] }} rows={rows} activeId=""
      collapsed={false} nowMs={0} emptyFolders={{ local: ["Kit/Lib/Later", "Kit/Art"] }} onToggleCollapsed={() => {}} onOpen={() => {}}
      onCreate={() => {}} onImportLocal={() => {}} onAddFolder={() => {}} onMoveWorkflow={() => {}} onMoveFolder={() => {}}
      onCopyFolder={onCopyFolder} />,
  );
  return onCopyFolder;
}
const items = () => [...screen.getByRole("menu").querySelectorAll('[role^="menuitem"]')].map((el) => el.textContent?.trim());

afterEach(cleanup);

describe("folder menu: copy or move a whole folder to another owner", () => {
  it("offers every other owner it can write to, and says how much goes along", () => {
    const onCopy = renderList();
    fireEvent.contextMenu(screen.getByRole("button", { name: "Folder Kit" }));
    expect(items()).toEqual(["New workflow here", "New folder inside", "Rename", "Copy folder to Space · Alpha", "Move folder to Space · Alpha",
      "Remove folder (keeps its workflows)"]);  // Beta is read-only here
    fireEvent.click(screen.getByRole("menuitem", { name: "Move folder to Space · Alpha" }));
    // Main and Helper; Lib, Lib/Later (empty) and Art (empty).
    expect(onCopy).toHaveBeenCalledWith("local", "Kit", "spaceA", true, { workflows: 2, folders: 3 });
  });

  it("copies out of a read-only space but never moves", () => {
    const onCopy = renderList(vi.fn(), [row("Daily", "Ops", BETA)]);
    fireEvent.contextMenu(screen.getByRole("button", { name: "Folder Ops" }));
    expect(items()).toEqual(["Read-only", "Copy folder to Local", "Copy folder to Space · Alpha"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy folder to Local" }));
    expect(onCopy).toHaveBeenCalledWith("spaceB", "Ops", "local", false, { workflows: 1, folders: 0 });
  });

  it("has no copy items without the handler", () => {
    render(
      <WorkflowList listId="list" listRef={{ current: null }} owners={{ owners: [LOCAL, ALPHA] }} rows={[row("Main", "Kit")]} activeId=""
        collapsed={false} nowMs={0} onToggleCollapsed={() => {}} onOpen={() => {}} onCreate={() => {}} onImportLocal={() => {}} />,
    );
    fireEvent.contextMenu(screen.getByRole("button", { name: "Folder Kit" }));
    expect(items()).toEqual(["New workflow here"]);
  });
});

describe("folder menu: save folder as template", () => {
  const show = (rows: AutomationSummaryDto[], extra: string[] = []) => {
    const onSave = vi.fn();
    render(
      <WorkflowList listId="list" listRef={{ current: null }} owners={{ owners: [LOCAL, BETA] }} rows={rows} activeId=""
        collapsed={false} nowMs={0} emptyFolders={{ local: extra }} onToggleCollapsed={() => {}} onOpen={() => {}} onCreate={() => {}}
        onImportLocal={() => {}} onMoveFolder={() => {}} onSaveFolderTemplate={onSave} />,
    );
    return onSave;
  };

  it("keeps a folder with its nested workflows, a read-only space's too", () => {
    const onSave = show([row("Main", "Kit"), row("Helper", "Kit/Lib"), row("Daily", "Ops", BETA)]);
    fireEvent.contextMenu(screen.getByRole("button", { name: "Folder Kit" }));
    expect(items()).toContain("Save folder as template");
    fireEvent.click(screen.getByRole("menuitem", { name: "Save folder as template" }));
    expect(onSave).toHaveBeenCalledWith("local", "Kit");
    cleanup();
    const onShared = show([row("Daily", "Ops", BETA)]);
    fireEvent.contextMenu(screen.getByRole("button", { name: "Folder Ops" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Save folder as template" }));
    expect(onShared).toHaveBeenCalledWith("spaceB", "Ops");
  });

  it("is not offered for a folder with no workflows in it", () => {
    show([row("Loose", "")], ["Empty"]);
    fireEvent.contextMenu(screen.getByRole("button", { name: "Folder Empty" }));
    expect(items()).not.toContain("Save folder as template");
  });
});

describe("a space whose data was reset on the server", () => {
  it("says so and offers Upload my copy and Clear my copy", () => {
    const reset: WorkflowOwnerDto = { id: "spaceR", kind: "shared", label: "Gamma", state: "reset", readOnly: true,
      reason: "Gamma's data was reset on the server.", resetContents: ["Workflows"] };
    const onResetChoice = vi.fn();
    render(
      <WorkflowList listId="list" listRef={{ current: null }} owners={{ owners: [LOCAL, ALPHA, reset] }} rows={[row("Team flow", "", reset)]}
        activeId="" collapsed={false} nowMs={0} onToggleCollapsed={() => {}} onOpen={() => {}} onCreate={() => {}} onImportLocal={() => {}}
        onResetChoice={onResetChoice} />,
    );
    expect(screen.getByText("Gamma's data was reset on the server. Your copy here is read-only until you choose what to do with it.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Upload my copy" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear my copy" }));
    expect(onResetChoice.mock.calls).toEqual([["spaceR", "upload"], ["spaceR", "clear"]]);
    // Only that space: Alpha has no such row.
    expect(screen.getAllByRole("button", { name: "Upload my copy" }).length).toBe(1);
  });
});
