// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { registerTarget, unregisterTarget } from "./registry";
import {
  accessibleName,
  findByRole,
  findByText,
  isTargetSpec,
  listUiActions,
  registerTargetResolver,
  registerUiAction,
  resolveTarget,
  roleOf,
  runUiAction,
  targetKey,
  waitForTarget,
} from "./resolve";

function sized<T extends HTMLElement>(el: T, w = 40, h = 20): T {
  el.getBoundingClientRect = () => ({ x: 10, y: 10, left: 10, top: 10, width: w, height: h, right: 10 + w, bottom: 10 + h, toJSON: () => ({}) }) as DOMRect;
  return el;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("finding what to show", () => {
  it("reads roles and accessible names like a screen reader", () => {
    document.body.innerHTML = `<button aria-label="Close details">x</button><a href="#">Docs</a><input id="t" /><label for="t">Title</label><textarea></textarea>`;
    const [button, link, input, , area] = Array.from(document.body.children) as HTMLElement[];
    expect([roleOf(button), roleOf(link), roleOf(input), roleOf(area)]).toEqual(["button", "link", "textbox", "textbox"]);
    expect(accessibleName(button)).toBe("Close details");
    expect(accessibleName(input)).toBe("Title");
  });

  it("finds a button by name: exact first, then starts with, then contains, inside a scope", () => {
    document.body.innerHTML = `
      <div id="a"><button>Save as template</button><button>Save</button></div>
      <div id="b"><button>Save and run</button></div>`;
    for (const el of Array.from(document.querySelectorAll("button"))) sized(el as HTMLElement);
    expect(findByRole("button", "save")?.textContent).toBe("Save");
    expect(findByRole("button", "save and")?.textContent).toBe("Save and run");
    expect(findByRole("button", "template")?.textContent).toBe("Save as template");
    registerTarget("zone.b", document.getElementById("b")!);
    expect(resolveTarget({ role: "button", name: "save", within: "zone.b" })?.textContent).toBe("Save and run");
    unregisterTarget("zone.b");
    expect(findByRole("button", "nothing like it")).toBeNull();
  });

  it("finds the smallest element with some text", () => {
    document.body.innerHTML = `<section><p>Run log <span>3 steps</span></p></section>`;
    expect(findByText("3 steps")?.tagName).toBe("SPAN");
  });

  it("resolves registry ids, then view resolvers by longest prefix", () => {
    const el = sized(document.createElement("button"));
    document.body.append(el);
    registerTarget("demo.button", el);
    expect(resolveTarget("demo.button")).toBe(el);
    const pin = sized(document.createElement("span"));
    document.body.append(pin);
    const off = registerTargetResolver("demo.pin.", { find: (id) => (id === "demo.pin.a.in.x" ? pin : null) });
    const offShort = registerTargetResolver("demo.", { find: () => null });
    expect(resolveTarget("demo.pin.a.in.x")).toBe(pin);
    off();
    offShort();
    expect(resolveTarget("demo.pin.a.in.x")).toBeNull();
    unregisterTarget("demo.button");
  });

  it("names targets and knows what counts as one", () => {
    expect(targetKey("workflows.toolbar.run")).toBe("workflows.toolbar.run");
    expect(targetKey({ role: "button", name: "Save", within: "workflows.details" })).toBe('button "Save" in workflows.details');
    expect(isTargetSpec("x")).toBe(true);
    expect(isTargetSpec({ name: "Save" })).toBe(true);
    expect(isTargetSpec({})).toBe(false);
    expect(isTargetSpec(" ")).toBe(false);
    expect(isTargetSpec(["x"])).toBe(false);
  });

  it("waits for a target that mounts a moment later", async () => {
    setTimeout(() => {
      const el = sized(document.createElement("button"));
      registerTarget("later.button", el);
      document.body.append(el);
    }, 150);
    const found = await waitForTarget("later.button", 2000);
    expect(found?.tagName).toBe("BUTTON");
    expect(await waitForTarget("never.there", 150)).toBeNull();
    unregisterTarget("later.button");
  });
});

describe("UI actions", () => {
  it("run by name and list per view", async () => {
    const calls: unknown[] = [];
    const off = registerUiAction("demo.open", (args) => { calls.push(args); }, { label: "Open", route: "demo" });
    expect(listUiActions("demo")).toEqual([{ id: "demo.open", label: "Open", route: "demo" }]);
    expect(await runUiAction("demo.open", { id: "w1" })).toEqual({ ok: true });
    expect(calls).toEqual([{ id: "w1" }]);
    expect((await runUiAction("demo.nope")).ok).toBe(false);
    const boom = registerUiAction("demo.boom", () => { throw new Error("broke"); });
    expect(await runUiAction("demo.boom")).toEqual({ ok: false, error: "broke" });
    off();
    boom();
    expect(listUiActions("demo")).toEqual([]);
  });
});
