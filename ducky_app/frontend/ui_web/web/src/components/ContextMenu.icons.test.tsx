// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ContextMenu, type ContextMenuItem } from "./ContextMenu";

afterEach(cleanup);

it("shows each row's icon and keeps a long menu inside the window", () => {
  const items: ContextMenuItem[] = Array.from({ length: 60 }, (_, i) => ({
    id: `b${i}`,
    label: `Button ${i}`,
    icon: <svg data-testid={`icon-${i}`} />,
    switch: true,
    checked: i % 2 === 0,
  }));
  render(<ContextMenu x={10} y={10} items={items} onClose={() => {}} />);
  expect(document.querySelectorAll(".context-menu-icon")).toHaveLength(60);
  expect(document.querySelector("[data-testid=icon-59]")).toBeTruthy();
  // 60 rows don't fit: the menu is capped to the window and scrolls (style comes from CSS).
  const css = Array.from(document.querySelectorAll("style")).map((s) => s.textContent).join("");
  expect(css).toContain(`--context-menu-max-height: ${Math.max(120, window.innerHeight - 16)}px`);
});
