// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { getTargetElement, registerTarget, targetRef, unregisterTarget } from "./registry";

function shown(el: HTMLElement): HTMLElement {
  el.getBoundingClientRect = () => ({ x: 0, y: 0, width: 200, height: 300, top: 0, left: 0, right: 200, bottom: 300, toJSON: () => ({}) });
  return el;
}

afterEach(() => {
  unregisterTarget("shared.list");
  document.body.replaceChildren();
});

describe("one id on several elements", () => {
  it("means the visible one, and keeps it when a hidden copy leaves", () => {
    // The docked Duckies list and a hidden copy both tag shell.chat_history.
    const docked = shown(document.body.appendChild(document.createElement("div")));
    const hidden = document.body.appendChild(document.createElement("div"));
    const ref = targetRef("shared.list");
    ref(docked);
    ref(hidden); // the hidden copy registers last
    expect(getTargetElement("shared.list")).toBe(docked);

    hidden.remove();
    ref(null); // React can't say which copy left
    expect(getTargetElement("shared.list")).toBe(docked);
  });

  it("drops an element that left the page, and the id with the last one", () => {
    const a = document.body.appendChild(document.createElement("div"));
    const b = document.body.appendChild(document.createElement("div"));
    registerTarget("shared.list", a);
    registerTarget("shared.list", b);
    b.remove();
    expect(getTargetElement("shared.list")).toBe(a); // never a node that is gone
    unregisterTarget("shared.list", a);
    expect(getTargetElement("shared.list")).toBeNull();
  });
});
