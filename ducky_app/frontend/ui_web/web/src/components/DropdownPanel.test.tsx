// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useRef } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { DropdownPanel } from "./DropdownPanel";

function Menu({ zIndex }: { zIndex?: number }) {
  const anchor = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={anchor}>open</button>
      <DropdownPanel anchorRef={anchor} open onClose={() => {}} zIndex={zIndex}>
        items
      </DropdownPanel>
    </>
  );
}

afterEach(cleanup);

describe("DropdownPanel stacking", () => {
  it("passes its zIndex through the variable the panel's own rule reads", () => {
    render(<Menu zIndex={2147483300} />);
    const css = [...document.querySelectorAll("style")].map((s) => s.textContent).join("\n");
    expect(css).toContain("--dropdown-z: 2147483300");
    // A plain z-index on the scoped class loses to `.dropdown-panel.is-positioned`: menus in the
    // setup opened under it. The positioned rule must read the variable instead.
    const sheet = readFileSync(join(process.cwd(), "src/theme/styles/components-inline.css"), "utf8");
    expect(sheet).toMatch(/\.dropdown-panel\.is-positioned \{[^}]*z-index: var\(--dropdown-z, 100010\)/);
  });
});
