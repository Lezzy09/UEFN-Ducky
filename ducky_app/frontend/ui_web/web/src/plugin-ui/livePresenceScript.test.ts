// @vitest-environment jsdom
/** The pointer script the host puts first in every panel page (backend/uefn_plugins/ui_kit.py
 * LIVE_PRESENCE_SCRIPT), run as a page would: what it sends while live, and what it draws. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

const CHANNEL = "uefn-plugin-ui";

/** The script's text from the Python source: its string literals, joined and unescaped. */
function presenceScript(): string {
  const py = readFileSync(join(__dirname, "../../../../../backend/uefn_plugins/ui_kit.py"), "utf8");
  const start = py.indexOf("LIVE_PRESENCE_SCRIPT = (");
  const block = py.slice(start, py.indexOf("\n)", start));
  const parts = [...block.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1].replace(/\\(["'\\])/g, "$1"));
  return parts.join("").replace(/^<script>/, "").replace(/<\/script>$/, "");
}

const sent: { method: string; params: Record<string, unknown> }[] = [];
const tell = (event: Record<string, unknown>) =>
  window.dispatchEvent(new MessageEvent("message", { data: { channel: CHANNEL, event }, source: window }));
const layer = () => document.querySelector("[data-ducky-live]");

beforeAll(() => {
  vi.spyOn(window, "postMessage").mockImplementation((msg: unknown) => {
    const m = msg as { method: string; params: Record<string, unknown> };
    sent.push({ method: m.method, params: m.params });
  });
  document.body.innerHTML = '<div data-live-id="clip-1"><span id="name">Pip</span></div><button>Go</button>';
  for (const el of document.querySelectorAll("div, span, button")) {
    el.getBoundingClientRect = () => ({ left: 100, top: 50, width: 200, height: 100, right: 300, bottom: 150, x: 100, y: 50, toJSON: () => ({}) });
  }
  (0, eval)(presenceScript());
});
afterEach(() => {
  sent.length = 0;
  vi.restoreAllMocks();
  vi.spyOn(window, "postMessage").mockImplementation((msg: unknown) => {
    const m = msg as { method: string; params: Record<string, unknown> };
    sent.push({ method: m.method, params: m.params });
  });
});

it("sends nothing until live, then this pointer as an anchor and fractions, at most every 50 ms", () => {
  const clip = document.querySelector("[data-live-id]") as HTMLElement;
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 150, clientY: 75, bubbles: true }));
  expect(sent).toEqual([]);
  tell({ type: "live.state", on: true });
  const now = vi.spyOn(Date, "now").mockReturnValue(10_000);
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 150, clientY: 75, bubbles: true }));
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 160, clientY: 75, bubbles: true }));
  expect(sent).toEqual([{ method: "live.pointer", params: { anchor: '[data-live-id="clip-1"]', fx: 0.25, fy: 0.25 } }]);
  now.mockReturnValue(10_100);
  document.getElementById("name")?.dispatchEvent(new MouseEvent("pointermove", { clientX: 300, clientY: 150, bubbles: true }));
  expect(sent[1]).toEqual({ method: "live.pointer", params: { anchor: '[id="name"]', fx: 1, fy: 1 } });
  document.querySelector("button")?.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  expect(sent[2]).toEqual({ method: "live.select", params: { anchor: "body>button:nth-of-type(1)" } });
});

it("draws a teammate's pointer with their name, and drops it when they leave", () => {
  tell({ type: "live.state", on: true });
  tell({ type: "live.message", topic: "ducky.pointer", from: { name: "Alex", device: "d1" },
    data: { anchor: '[data-live-id="clip-1"]', fx: 0.5, fy: 0.5 } });
  const drawn = layer()?.firstElementChild as HTMLElement;
  expect(drawn.textContent).toBe("Alex");
  expect(drawn.style.transform).toBe("translate(200px,100px)");
  expect(getComputedStyle(layer() as HTMLElement).pointerEvents).toBe("none");
  tell({ type: "live.message", topic: "ducky.select", from: { name: "Alex", device: "d1" }, data: { anchor: '[id="name"]' } });
  expect(layer()?.children.length).toBe(2);
  tell({ type: "live.peers", on: true, peers: [{ device: "d2" }] });
  expect(layer()?.children.length).toBe(0);
});

it("a message from another window is ignored; off clears what it drew", () => {
  tell({ type: "live.state", on: true });
  window.dispatchEvent(new MessageEvent("message", {
    data: { channel: CHANNEL, event: { type: "live.message", topic: "ducky.pointer", from: { name: "Eve", device: "e" },
      data: { anchor: "body" } } },
    source: {} as Window,
  }));
  expect(layer()?.children.length ?? 0).toBe(0);
  tell({ type: "live.message", topic: "ducky.pointer", from: { name: "Alex", device: "d1" }, data: { anchor: "body" } });
  expect(layer()?.children.length).toBe(1);
  tell({ type: "live.state", on: false });
  expect(layer()?.children.length).toBe(0);
  document.body.dispatchEvent(new MouseEvent("pointermove", { clientX: 1, clientY: 1, bubbles: true }));
  expect(sent).toEqual([]);
});
