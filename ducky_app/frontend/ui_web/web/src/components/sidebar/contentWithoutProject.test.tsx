// @vitest-environment jsdom
import { createRef } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SidebarStackedPanels } from "./SidebarStackedPanels";
import { canToggleStackedPanel, contentCollapsedWithoutProject, hasOpenProject } from "./contentWithoutProject";

vi.mock("../CtrlWheelZoomRoot", () => ({
  CtrlWheelZoomRoot: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

afterEach(cleanup);

// What the owner saw on Oct 16 2026: no project open, and Content took half the rail
// to say "No project selected." in red.
function rail(projectSlug: string, saved = { chats: false, files: false }) {
  return render(
    <SidebarStackedPanels
      order={["chats", "files"]}
      collapsed={contentCollapsedWithoutProject(saved, projectSlug)}
      splitRatio={0.5}
      stackRef={createRef<HTMLDivElement>()}
      panels={{
        chats: { title: "Duckies", children: "No-model test" },
        files: { title: "Content", children: "No project selected." },
      }}
      onResizeSplit={vi.fn()}
      onPersistSplit={vi.fn()}
      onToggleCollapsed={vi.fn()}
      onSwapPanels={vi.fn()}
    />,
  );
}

function panel(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector<HTMLElement>(`.sidebar-stacked-panel[data-panel-id="${id}"]`)!;
}

it("shows Content collapsed while no project is open, and Duckies keeps the rail", () => {
  const { container } = rail("_no_project");
  expect(panel(container, "files").classList.contains("is-collapsed")).toBe(true);
  expect(panel(container, "files").querySelector(".sidebar-stacked-panel-body")!.getAttribute("aria-hidden")).toBe("true");
  expect(panel(container, "chats").classList.contains("is-collapsed")).toBe(false);
  expect(screen.queryAllByRole("separator")).toHaveLength(0); // nothing to resize against
});

it("opens Content again as it was once a project is open", () => {
  const { container } = rail("tycoony");
  expect(panel(container, "files").classList.contains("is-collapsed")).toBe(false);
  cleanup();
  const kept = rail("tycoony", { chats: false, files: true });
  expect(panel(kept.container, "files").classList.contains("is-collapsed")).toBe(true); // their own choice stays
});

it("does not let Content be expanded with no project", () => {
  expect(canToggleStackedPanel("files", "_no_project")).toBe(false);
  expect(canToggleStackedPanel("files", "")).toBe(false);
  expect(canToggleStackedPanel("chats", "_no_project")).toBe(true);
  expect(canToggleStackedPanel("files", "tycoony")).toBe(true);
});

it("leaves the saved state alone", () => {
  const saved = { chats: false, files: false, outline: false };
  expect(contentCollapsedWithoutProject(saved, "_no_project")).toEqual({ chats: false, files: true, outline: false });
  expect(saved.files).toBe(false);
  expect(contentCollapsedWithoutProject(saved, "tycoony")).toBe(saved);
  expect(hasOpenProject(" ")).toBe(false);
});

