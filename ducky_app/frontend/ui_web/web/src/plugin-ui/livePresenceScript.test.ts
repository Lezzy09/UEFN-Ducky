// @vitest-environment jsdom
/** The live script the host puts first in every panel page (backend/uefn_plugins/ui_kit.py
 * LIVE_PRESENCE_SCRIPT), run as a page would: what it sends while live, what it draws, the
 * controls it greys out while a teammate holds them, and pictures that aren't here yet. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const CHANNEL = "uefn-plugin-ui";

/** The script's text from the Python source (a raw string). */
function liveScript(): string {
  const py = readFileSync(join(__dirname, "../../../../../backend/uefn_plugins/ui_kit.py"), "utf8");
  const open = 'LIVE_PRESENCE_SCRIPT = r"""';
  const start = py.indexOf(open) + open.length;
  return py.slice(start, py.indexOf('"""', start)).replace(/^<script>/, "").replace(/<\/script>$/, "");
}

const sent: { method: string; params: Record<string, unknown> }[] = [];
const tell = (event: Record<string, unknown>) =>
  window.dispatchEvent(new MessageEvent("message", { data: { channel: CHANNEL, event }, source: window }));
const layer = () => document.querySelector("[data-ducky-live]");
const holds = () => sent.filter((m) => m.method === "live.hold").map((m) => m.params);
const ALEX = { name: "Alex", device: "d1" };
const BOX = { left: 100, top: 50, width: 200, height: 100, right: 300, bottom: 150, x: 100, y: 50, toJSON: () => ({}) };

beforeAll(() => {
  vi.useFakeTimers();
  vi.setSystemTime(10_000);
  vi.spyOn(window, "postMessage").mockImplementation((msg: unknown) => {
    const m = msg as { method: string; params: Record<string, unknown> };
    sent.push({ method: m.method, params: m.params });
  });
  (0, eval)(liveScript());
});
beforeEach(() => {
  document.body.innerHTML = '<div data-live-id="clip-1"><span id="name">Pip</span></div><button>Go</button>' +
    '<input id="title" value="Untitled island 1"><a href="#x">Docs</a><img id="logo" src="logo.png">';
  for (const el of document.body.querySelectorAll("*")) el.getBoundingClientRect = () => BOX;
});
afterEach(() => {
  tell({ type: "live.state", on: false });
  vi.advanceTimersByTime(3000);
  sent.length = 0;
});

it("sends nothing until live, then this pointer as an anchor and fractions, at most every 50 ms", () => {
  const clip = document.querySelector("[data-live-id]") as HTMLElement;
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 150, clientY: 75, bubbles: true }));
  expect(sent).toEqual([]);
  tell({ type: "live.state", on: true });
  vi.setSystemTime(20_000);
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 150, clientY: 75, bubbles: true }));
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 160, clientY: 75, bubbles: true }));
  const pointers = () => sent.filter((m) => m.method === "live.pointer");
  expect(pointers()).toEqual([{ method: "live.pointer", params: { anchor: '[data-live-id="clip-1"]', fx: 0.25, fy: 0.25, v: expect.stringMatching(/^v/) } }]);
  vi.setSystemTime(20_100);
  document.getElementById("name")?.dispatchEvent(new MouseEvent("pointermove", { clientX: 300, clientY: 150, bubbles: true }));
  expect(pointers()[1]).toMatchObject({ method: "live.pointer", params: { anchor: '[id="name"]', fx: 1, fy: 1 } });
  // A click on something that isn't a control is a selection.
  document.getElementById("name")?.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  expect(sent.find((m) => m.method === "live.select")).toEqual({ method: "live.select", params: { anchor: '[id="name"]' } });
});

it("draws a teammate's pointer with their name, and drops it when they leave", () => {
  tell({ type: "live.state", on: true });
  tell({ type: "live.message", topic: "ducky.pointer", from: ALEX, data: { anchor: '[data-live-id="clip-1"]', fx: 0.5, fy: 0.5 } });
  const drawn = layer()?.firstElementChild as HTMLElement;
  expect(drawn.textContent).toBe("Alex");
  expect(drawn.style.transform).toBe("translate(200px,100px)");
  expect(getComputedStyle(layer() as HTMLElement).pointerEvents).toBe("none");
  tell({ type: "live.message", topic: "ducky.select", from: ALEX, data: { anchor: '[id="name"]' } });
  expect(layer()?.children.length).toBe(2);
  tell({ type: "live.peers", on: true, peers: [{ device: "d2" }] });
  expect(layer()?.children.length).toBe(0);
});

it("sends this screen at once when someone new joins, not at the next 5 s beat", () => {
  tell({ type: "live.state", on: true });
  tell({ type: "live.peers", on: true, peers: [ALEX] });
  vi.advanceTimersByTime(300);
  sent.length = 0;
  tell({ type: "live.peers", on: true, peers: [ALEX] });  // nobody new: nothing extra
  expect(sent.filter((m) => m.method === "live.view")).toEqual([]);
  tell({ type: "live.peers", on: true, peers: [ALEX, { name: "You on Laptop", device: "d9" }] });
  expect(sent.filter((m) => m.method === "live.view")).toHaveLength(1);
});

it("sends this screen when a joiner's link comes up, not while they are still unlinked", () => {
  tell({ type: "live.state", on: true });
  tell({ type: "live.peers", on: true, peers: [] });
  vi.advanceTimersByTime(300);
  sent.length = 0;
  tell({ type: "live.peers", on: true, peers: [{ name: "Bo", device: "d7", path: "none" }] });  // in the group, no link
  expect(sent.filter((m) => m.method === "live.view")).toEqual([]);
  tell({ type: "live.peers", on: true, peers: [{ name: "Bo", device: "d7", path: "direct" }] });
  expect(sent.filter((m) => m.method === "live.view")).toHaveLength(1);
});

it("a message from another window is ignored; off clears what it drew", () => {
  tell({ type: "live.state", on: true });
  window.dispatchEvent(new MessageEvent("message", {
    data: { channel: CHANNEL, event: { type: "live.message", topic: "ducky.pointer", from: { name: "Eve", device: "e" },
      data: { anchor: "body" } } },
    source: {} as Window,
  }));
  expect(layer()?.children.length ?? 0).toBe(0);
  tell({ type: "live.message", topic: "ducky.pointer", from: ALEX, data: { anchor: "body" } });
  expect(layer()?.children.length).toBe(1);
  tell({ type: "live.state", on: false });
  expect(layer()?.children.length).toBe(0);
  document.body.dispatchEvent(new MouseEvent("pointermove", { clientX: 1, clientY: 1, bubbles: true }));
  expect(sent.filter((m) => m.method === "live.pointer")).toEqual([]);
});

it("pressing a control holds it until 1.5 s after the button comes up; a text field while it has focus", () => {
  tell({ type: "live.state", on: true });
  const go = document.querySelector("button") as HTMLButtonElement;
  go.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  expect(holds()).toEqual([{ anchor: "body>button:nth-of-type(1)", on: true, t: Date.now(), v: expect.stringMatching(/^v/) }]);
  expect(sent.some((m) => m.method === "live.select")).toBe(false);  // a held control isn't also a selection
  go.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
  vi.advanceTimersByTime(1000);
  expect(holds()).toHaveLength(1);
  vi.advanceTimersByTime(2000);
  expect(holds()[1]).toEqual({ anchor: "body>button:nth-of-type(1)", on: false });

  const title = document.getElementById("title") as HTMLInputElement;
  title.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  title.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  expect(holds()[2]).toMatchObject({ anchor: '[id="title"]', on: true });
  vi.advanceTimersByTime(11_000);  // still focused: renewed, never let go
  expect(holds()[3]).toMatchObject({ anchor: '[id="title"]', on: true });
  title.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  vi.advanceTimersByTime(3000);
  expect(holds()[4]).toEqual({ anchor: '[id="title"]', on: false });

  // Links never hold; nothing holds while not live.
  document.querySelector("a")?.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  tell({ type: "live.state", on: false });
  go.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  expect(holds()).toHaveLength(5);
});

it("dragging anything holds it", () => {
  tell({ type: "live.state", on: true });
  const clip = document.querySelector("[data-live-id]") as HTMLElement;
  clip.dispatchEvent(new MouseEvent("pointerdown", { clientX: 110, clientY: 60, bubbles: true }));
  expect(holds()).toEqual([]);
  clip.dispatchEvent(new MouseEvent("pointermove", { clientX: 130, clientY: 60, buttons: 1, bubbles: true }));
  expect(holds()).toEqual([{ anchor: '[data-live-id="clip-1"]', on: true, t: Date.now(), v: expect.stringMatching(/^v/) }]);
});

it("what a teammate holds is greyed out with their name and can't be used, until they let go", () => {
  tell({ type: "live.state", on: true });
  const title = document.getElementById("title") as HTMLInputElement & { inert?: boolean };
  tell({ type: "live.message", topic: "ducky.hold", from: ALEX, data: { anchor: '[id="title"]', on: true, t: 1 } });
  expect(title.getAttribute("data-ducky-held")).toBe("Alex");
  expect(title.inert).toBe(true);
  expect(title.getAttribute("aria-disabled")).toBe("true");
  expect(layer()?.textContent).toContain("Alex");
  // Pressing it here holds nothing.
  title.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  expect(holds()).toEqual([]);
  tell({ type: "live.message", topic: "ducky.hold", from: ALEX, data: { anchor: '[id="title"]', on: false } });
  expect(title.getAttribute("data-ducky-held")).toBeNull();
  expect(title.inert).toBe(false);
  expect(title.getAttribute("aria-disabled")).toBeNull();
});

it("two presses at once: the earlier keeps it, the later lets go", () => {
  tell({ type: "live.state", on: true });
  const go = document.querySelector("button") as HTMLButtonElement;
  go.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  const mine = holds()[0].t as number;
  // Theirs came later: they let go, nothing changes here.
  tell({ type: "live.message", topic: "ducky.hold", from: ALEX, data: { anchor: "body>button:nth-of-type(1)", on: true, t: mine + 5 } });
  expect(go.getAttribute("data-ducky-held")).toBeNull();
  // Theirs came first: this PC lets go, and the button is theirs.
  tell({ type: "live.message", topic: "ducky.hold", from: { name: "Sam", device: "d2" }, data: { anchor: "body>button:nth-of-type(1)", on: true, t: mine - 5 } });
  expect(holds()[1]).toEqual({ anchor: "body>button:nth-of-type(1)", on: false });
  expect(go.getAttribute("data-ducky-held")).toBe("Sam");
});

it("a hold nobody renews goes after 30 s; one of someone who left goes at once", () => {
  tell({ type: "live.state", on: true });
  const go = document.querySelector("button") as HTMLButtonElement;
  tell({ type: "live.message", topic: "ducky.hold", from: ALEX, data: { anchor: "body>button:nth-of-type(1)", on: true, t: 1 } });
  vi.advanceTimersByTime(29_000);
  expect(go.getAttribute("data-ducky-held")).toBe("Alex");
  vi.advanceTimersByTime(2000);
  expect(go.getAttribute("data-ducky-held")).toBeNull();
  tell({ type: "live.message", topic: "ducky.hold", from: ALEX, data: { anchor: "body>button:nth-of-type(1)", on: true, t: 2 } });
  tell({ type: "live.peers", on: true, peers: [] });
  expect(go.getAttribute("data-ducky-held")).toBeNull();
});

it("a picture that isn't here yet shows a placeholder on a team copy, and loads again after a sync", () => {
  const logo = document.getElementById("logo") as HTMLImageElement;
  logo.dispatchEvent(new Event("error"));
  expect(logo.getAttribute("src")).toBe("logo.png");  // Local: the plugin's own way
  tell({ type: "sync.state", shared: true, incoming: 1 });
  expect(decodeURIComponent(logo.getAttribute("src") ?? "")).toContain("Getting picture…");
  tell({ type: "sync.state", shared: true, incoming: 0 });
  expect(decodeURIComponent(logo.getAttribute("src") ?? "")).toContain("Not on this PC yet");
  tell({ type: "plugin_scope_changed", reason: "synced" });
  expect(logo.getAttribute("src")).toBe("logo.png");
  // The plugin put another picture in: the placeholder never replaces it.
  logo.dispatchEvent(new Event("error"));
  logo.setAttribute("src", "other.png");
  tell({ type: "sync.state", shared: true, incoming: 2 });
  expect(logo.getAttribute("src")).toBe("other.png");
  tell({ type: "sync.state", shared: false, incoming: 0 });
});

it("on a team copy, holds work without live and come from teammates' presence, on the same screen only", () => {
  tell({ type: "sync.state", shared: true, incoming: 0 });
  // A team copy asks once what teammates hold now.
  const ask = sent.find((m) => m.method === "live.holds");
  expect(ask).toBeTruthy();
  const go = document.querySelector("button") as HTMLButtonElement;
  go.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  expect(holds()[0]).toMatchObject({ anchor: "body>button:nth-of-type(1)", on: true });
  go.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
  vi.advanceTimersByTime(3000);
  // Teammates' holds from presence: greyed out on this screen, never on another one.
  const title = document.getElementById("title") as HTMLInputElement;
  const v = holds()[0].v as string;
  tell({ type: "live.holds", holds: [{ device: "d9", name: "Mo", anchor: '[id="title"]', t: 5, v: "vother" }] });
  expect(title.getAttribute("data-ducky-held")).toBeNull();
  tell({ type: "live.holds", holds: [{ device: "d9", name: "Mo", anchor: '[id="title"]', t: 5, v }] });
  expect(title.getAttribute("data-ducky-held")).toBe("Mo");
  tell({ type: "live.holds", holds: [] });
  expect(title.getAttribute("data-ducky-held")).toBeNull();
  tell({ type: "sync.state", shared: false, incoming: 0 });
});

it("a screen the plugin marks with data-live-view keeps holds to that screen", () => {
  tell({ type: "sync.state", shared: true, incoming: 0 });
  document.body.setAttribute("data-live-view", "project-a");
  const title = document.getElementById("title") as HTMLInputElement;
  title.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  const v = holds().at(-1)?.v as string;
  document.body.setAttribute("data-live-view", "project-b");
  tell({ type: "live.holds", holds: [{ device: "d9", name: "Mo", anchor: '[id="title"]', t: 1, v }] });
  expect(title.getAttribute("data-ducky-held")).toBeNull();  // Mo is on project A, this page on B
  document.body.setAttribute("data-live-view", "project-a");
  vi.advanceTimersByTime(1000);
  expect(title.getAttribute("data-ducky-held")).toBe("Mo");
  document.body.removeAttribute("data-live-view");
  tell({ type: "live.holds", holds: [] });
  tell({ type: "sync.state", shared: false, incoming: 0 });
});

it("following the host: their scroll and tab clicks are replayed here, nobody else's", () => {
  document.body.insertAdjacentHTML("beforeend",
    '<div id="list" style="overflow:auto"></div><button role="tab" id="video-tab">Video</button>');
  const tab = document.getElementById("video-tab") as HTMLButtonElement;
  const clicks = vi.fn();
  tab.addEventListener("click", clicks);
  tell({ type: "live.state", on: true });
  const v = sent.find((m) => m.method === "live.view")?.params.v as string;
  tell({ type: "live.follow", device: "d1" });
  tell({ type: "live.message", topic: "ducky.nav", from: { name: "Sam", device: "d2" }, data: { anchor: '[id="video-tab"]' } });
  expect(clicks).not.toHaveBeenCalled();
  tell({ type: "live.message", topic: "ducky.nav", from: ALEX, data: { anchor: '[id="video-tab"]' } });
  expect(clicks).toHaveBeenCalledTimes(1);
  expect(sent.some((m) => m.method === "live.nav")).toBe(false);  // a replayed click isn't sent on
  // A button that isn't a tab is never clicked for you.
  tell({ type: "live.message", topic: "ducky.nav", from: ALEX, data: { anchor: "body>button:nth-of-type(1)" } });
  const list = document.getElementById("list") as HTMLElement;
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: { v, scroll: [{ anchor: '[id="list"]', top: 120, left: 0 }] } });
  expect(list.scrollTop).toBe(120);
  tell({ type: "live.follow", device: "" });
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: { v, scroll: [{ anchor: '[id="list"]', top: 0, left: 0 }] } });
  expect(list.scrollTop).toBe(120);
});

it("following the host goes to their screen (the plugin opens it), then scrolls with it there", () => {
  document.body.insertAdjacentHTML("beforeend", '<div id="list" style="overflow:auto"></div>');
  const went: string[] = [];
  const onGo = (e: Event) => went.push((e as CustomEvent<{ view: string }>).detail.view);
  window.addEventListener("ducky-live-goto", onGo);
  document.body.setAttribute("data-live-view", "p1:video");
  tell({ type: "live.state", on: true });
  // What this page sends names its screen the plugin's way, so a follower can open it.
  const video = sent.find((m) => m.method === "live.view")?.params;
  expect(video).toMatchObject({ at: "p1:video" });
  const hostView = { v: video?.v, at: "p1:video", scroll: [{ anchor: '[id="list"]', top: 80, left: 0 }] };
  document.body.setAttribute("data-live-view", "p1:thumbs");  // this page is on another tab
  tell({ type: "live.follow", device: "d1" });
  tell({ type: "live.message", topic: "ducky.view", from: { name: "Sam", device: "d2" }, data: hostView });
  expect(went).toEqual([]);  // not the one followed
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: hostView });
  expect(went).toEqual(["p1:video"]);
  const list = document.getElementById("list") as HTMLElement;
  expect(list.scrollTop).toBe(0);  // another screen: its scroll waits
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: hostView });
  expect(went).toHaveLength(1);  // the same screen again at once (the host scrolled) asks nothing new
  vi.advanceTimersByTime(5000);  // the plugin couldn't open it yet (still syncing): asked again
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: hostView });
  expect(went).toEqual(["p1:video", "p1:video"]);
  document.body.setAttribute("data-live-view", "p1:video");  // the plugin opened it
  vi.advanceTimersByTime(1000);
  expect(list.scrollTop).toBe(80);
  list.scrollTop = 0;  // the follower scrolls: a heartbeat never pulls it back
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: hostView });
  expect(list.scrollTop).toBe(0);
  document.body.setAttribute("data-live-view", "p1:rules");  // nor when they open something else
  vi.advanceTimersByTime(5000);
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: hostView });
  expect(went).toHaveLength(2);
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: { ...hostView, at: "p1:submit", v: "vsubmit" } });
  expect(went.at(-1)).toBe("p1:submit");  // the host moved: the follower goes too
  // A page not following anyone sends its screen again every 5 s: one that joins or reloads
  // catches up (a follower sends only its own moves, to the leader).
  tell({ type: "live.follow", device: "" });
  const views = () => sent.filter((m) => m.method === "live.view" && !m.params.ask).length;
  const before = views();
  vi.advanceTimersByTime(5000);
  expect(views()).toBeGreaterThan(before);
  window.removeEventListener("ducky-live-goto", onGo);
  document.body.removeAttribute("data-live-view");
});

it("while live, this page's tab clicks and screen go to the group", () => {
  document.body.insertAdjacentHTML("beforeend", '<button role="tab" id="rules-tab">Rules</button>');
  tell({ type: "live.state", on: true });
  expect(sent.find((m) => m.method === "live.view")?.params).toMatchObject({ v: expect.stringMatching(/^v/), scroll: [{ anchor: "@doc", top: 0, left: 0 }] });
  (document.getElementById("rules-tab") as HTMLButtonElement).click();
  expect(sent.find((m) => m.method === "live.nav")).toEqual({ method: "live.nav",
    params: { anchor: '[id="rules-tab"]', v: expect.stringMatching(/^v/), o: expect.stringMatching(/^[a-z0-9]+:\d+$/) } });
});

const SAM = { name: "Sam", device: "d2" };
const navs = () => sent.filter((m) => m.method === "live.nav").map((m) => m.params);

it("a member's own tab click goes to the leader; what the leader does, every page does once", () => {
  document.body.insertAdjacentHTML("beforeend", '<button role="tab" id="video-tab">Video</button>');
  const tab = document.getElementById("video-tab") as HTMLButtonElement;
  const clicks = vi.fn();
  tab.addEventListener("click", clicks);
  tell({ type: "live.state", on: true });
  tell({ type: "live.follow", device: "d1", leading: false });  // Alex leads
  tab.click();  // this person's own click: it happens here at once and asks the leader
  const asked = navs()[0];
  expect(asked).toMatchObject({ anchor: '[id="video-tab"]', ask: 1, to: "d1" });
  tell({ type: "live.message", topic: "ducky.nav", from: ALEX, data: { anchor: '[id="video-tab"]', v: asked.v, o: asked.o } });
  expect(clicks).toHaveBeenCalledTimes(1);  // the leader telling everyone: this page did it already
  tell({ type: "live.message", topic: "ducky.nav", from: ALEX, data: { anchor: '[id="video-tab"]', v: asked.v, o: "sam:3" } });
  expect(clicks).toHaveBeenCalledTimes(2);  // Sam's click, through the leader
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]', v: asked.v, o: "sam:4", ask: 1 } });
  expect(clicks).toHaveBeenCalledTimes(2);  // a member's ask is the leader's to do
  expect(navs()).toHaveLength(1);
  tell({ type: "live.follow", device: "" });
});

it("the leader does a member's click and tells everyone, naming who did it first", () => {
  document.body.insertAdjacentHTML("beforeend", '<button role="tab" id="video-tab">Video</button>');
  const clicks = vi.fn();
  document.getElementById("video-tab")?.addEventListener("click", clicks);
  tell({ type: "live.state", on: true });
  tell({ type: "live.follow", device: "", leading: true });
  const v = sent.find((m) => m.method === "live.view")?.params.v as string;
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]', v, o: "sam:1", ask: 1 } });
  expect(clicks).toHaveBeenCalledTimes(1);
  expect(navs()).toEqual([{ anchor: '[id="video-tab"]', o: "sam:1", v }]);  // to everyone, Sam's page skips it
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]', v, o: "sam:2" } });
  expect(clicks).toHaveBeenCalledTimes(1);  // not an ask: only the leader's own go to everyone
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]', v: "vother", o: "sam:3", ask: 1 } });
  expect(clicks).toHaveBeenCalledTimes(1);  // asked from another screen: not here
  tell({ type: "live.follow", device: "", leading: false });
});

it("a member's own move to another screen or scroll goes to the leader, which goes there with everyone", () => {
  document.body.insertAdjacentHTML("beforeend", '<div id="list" style="overflow:auto"></div>');
  const list = document.getElementById("list") as HTMLElement;
  const went: string[] = [];
  const onGo = (e: Event) => went.push((e as CustomEvent<{ view: string }>).detail.view);
  window.addEventListener("ducky-live-goto", onGo);
  document.body.setAttribute("data-live-view", "p1:video");
  tell({ type: "live.state", on: true });
  tell({ type: "live.follow", device: "d1", leading: false });
  const v = sent.find((m) => m.method === "live.view")?.params.v as string;
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: { v, at: "p1:video", scroll: [] } });
  sent.length = 0;
  vi.advanceTimersByTime(5000);
  expect(sent.filter((m) => m.method === "live.view")).toEqual([]);  // where the leader is: a member sends no heartbeat
  document.body.setAttribute("data-live-view", "p1:rules");  // this person opened Rules themselves
  vi.advanceTimersByTime(1000);
  expect(sent.find((m) => m.method === "live.view")?.params).toMatchObject({ at: "p1:rules", ask: 1, to: "d1" });
  sent.length = 0;
  vi.advanceTimersByTime(1000);
  list.scrollTop = 200;
  list.dispatchEvent(new Event("scroll"));  // their own scroll
  expect(sent.find((m) => m.method === "live.view")?.params).toMatchObject({ ask: 1, scroll: expect.arrayContaining([
    { anchor: '[id="list"]', top: 200, left: 0 }]) });
  // The leader's older scroll arriving while they scroll never pulls them back.
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: { v: sent[0].params.v, at: "p1:rules", scroll: [{ anchor: '[id="list"]', top: 0, left: 0 }] } });
  expect(list.scrollTop).toBe(200);
  // On the leader's page a member's ask moves the leader, and its screen goes to everyone.
  tell({ type: "live.follow", device: "", leading: true });
  tell({ type: "live.message", topic: "ducky.view", from: SAM, data: { v: "vx", at: "p1:thumbs", scroll: [], ask: 1 } });
  expect(went.at(-1)).toBe("p1:thumbs");
  window.removeEventListener("ducky-live-goto", onGo);
  document.body.removeAttribute("data-live-view");
  tell({ type: "live.follow", device: "", leading: false });
});

it("a groupmate on an older app: every page on the group's screen does its tab clicks, and nobody relays them", () => {
  document.body.insertAdjacentHTML("beforeend", '<button role="tab" id="video-tab">Video</button><div id="list" style="overflow:auto"></div>');
  const clicks = vi.fn();
  document.getElementById("video-tab")?.addEventListener("click", clicks);
  const list = document.getElementById("list") as HTMLElement;
  const went: string[] = [];
  const onGo = (e: Event) => went.push((e as CustomEvent<{ view: string }>).detail.view);
  window.addEventListener("ducky-live-goto", onGo);
  document.body.setAttribute("data-live-view", "p1:video");
  tell({ type: "live.state", on: true });
  tell({ type: "live.follow", device: "", leading: true, older: ["d2"] });  // Sam's app is older
  // An older app's click asks nobody and names no origin or screen: the leader does it, and
  // passes it on to nobody (Sam would hear it back and click it twice).
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]' } });
  expect(clicks).toHaveBeenCalledTimes(1);
  expect(navs()).toEqual([]);
  tell({ type: "live.message", topic: "ducky.nav", from: ALEX, data: { anchor: '[id="video-tab"]', o: "alex:1" } });
  expect(clicks).toHaveBeenCalledTimes(1);  // Alex is up to date: only Alex's asks are the leader's to do
  // Its screen and scroll stay its own.
  tell({ type: "live.message", topic: "ducky.view", from: SAM, data: { v: "vs", at: "p1:rules", scroll: [{ anchor: '[id="list"]', top: 300, left: 0 }] } });
  expect(went).toEqual([]);
  expect(list.scrollTop).toBe(0);
  // A member on the group's screen does it too; one who turned that off doesn't.
  tell({ type: "live.follow", device: "d1", leading: false, older: ["d2"] });
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]' } });
  expect(clicks).toHaveBeenCalledTimes(2);
  tell({ type: "live.follow", device: "", leading: false, older: ["d2"] });
  tell({ type: "live.message", topic: "ducky.nav", from: SAM, data: { anchor: '[id="video-tab"]' } });
  expect(clicks).toHaveBeenCalledTimes(2);
  window.removeEventListener("ducky-live-goto", onGo);
  document.body.removeAttribute("data-live-view");
  tell({ type: "live.follow", device: "", leading: false });
});

it("an update to who is on an older app keeps a member's place on the group's screen", () => {
  document.body.setAttribute("data-live-view", "p1:video");
  tell({ type: "live.state", on: true });
  tell({ type: "live.follow", device: "d1", leading: false, older: [] });
  const v = sent.find((m) => m.method === "live.view")?.params.v as string;
  tell({ type: "live.message", topic: "ducky.view", from: ALEX, data: { v, at: "p1:video", scroll: [] } });
  tell({ type: "live.follow", device: "d1", leading: false, older: ["d2"] });  // someone older joined
  sent.length = 0;
  vi.advanceTimersByTime(5000);
  expect(sent.filter((m) => m.method === "live.view")).toEqual([]);  // still where the leader is: nothing to ask
  document.body.removeAttribute("data-live-view");
  tell({ type: "live.follow", device: "", leading: false });
});
