// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../hooks/graphActivity", () => ({ requestFocusGraph: vi.fn() }));
vi.mock("../navigation/openWorkflowsTab", () => ({ requestOpenWorkflowsTab: vi.fn() }));
vi.mock("../components/rich-content/MarkdownContent", () => ({ MarkdownContent: ({ text }: { text: string }) => <p>{text}</p> }));

import { requestFocusGraph } from "../hooks/graphActivity";
import { requestOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import { registerTarget, unregisterTarget } from "../ui-targets/registry";
import { registerUiAction } from "../ui-targets/resolve";
import { ShowMeLayer } from "./ShowMeLayer";
import { _resetShowMeForTests, closeShowMe, getShowMeState, parseShowMeRequest, playShowMe, whenShowMeClosed } from "./ShowMeService";

const ids: string[] = [];
function target(id: string, label = id): HTMLButtonElement {
  const el = document.createElement("button");
  el.textContent = label;
  el.getBoundingClientRect = () => ({ x: 200, y: 300, left: 200, top: 300, width: 80, height: 30, right: 280, bottom: 330, toJSON: () => ({}) }) as DOMRect;
  document.body.append(el);
  registerTarget(id, el);
  ids.push(id);
  return el;
}

beforeEach(() => _resetShowMeForTests(200));
afterEach(() => {
  act(() => closeShowMe());
  cleanup();
  for (const id of ids.splice(0)) unregisterTarget(id);
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("Show me", () => {
  it("highlights the target with a popup that only its close button closes", async () => {
    render(<ShowMeLayer />);
    const save = target("demo.save", "Save");
    let result: Awaited<ReturnType<typeof playShowMe>> | undefined;
    await act(async () => {
      result = await playShowMe({ target: "demo.save", title: "Save", body: "Keeps your changes." });
    });
    expect(result).toMatchObject({ ok: true, shown: true, missing: false, target: "demo.save" });
    expect(screen.getByRole("dialog", { name: "Save" })).toBeTruthy();
    expect(screen.getByText("Keeps your changes.")).toBeTruthy();
    expect(document.querySelector(".showme-overlay")?.getAttribute("data-hole")).toBe("1");

    // Esc, clicks and presses elsewhere don't close it.
    const blocker = document.querySelector(".showme-blocker")!;
    fireEvent.keyDown(document.body, { key: "Escape" });
    fireEvent.pointerDown(blocker);
    fireEvent.click(blocker);
    expect(screen.getByRole("dialog", { name: "Save" })).toBeTruthy();
    expect(blocker.getAttribute("style") || "").toContain("polygon(evenodd");  // a hole over the target

    // The highlighted thing still works.
    const clicked = vi.fn();
    save.addEventListener("click", clicked);
    fireEvent.click(save);
    expect(clicked).toHaveBeenCalled();
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Close");  // focus on the way out

    const closed = whenShowMeClosed();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await closed;
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says when it can't find the target, and still waits for close", async () => {
    render(<ShowMeLayer />);
    let result: Awaited<ReturnType<typeof playShowMe>> | undefined;
    await act(async () => {
      result = await playShowMe({ target: "not.on.screen", title: "Nowhere", body: "" });
    });
    expect(result).toMatchObject({ shown: false, missing: true });
    expect(screen.getByText(/Can't find this on screen/)).toBeTruthy();
    expect(getShowMeState().request).not.toBeNull();
  });

  it("opens the workflow first and selects the nodes it points at", async () => {
    render(<ShowMeLayer />);
    target("workflows.node.servers", "Fortnite servers up?");
    await act(async () => {
      await playShowMe({ target: "workflows.node.servers", workflow_id: "wf1", title: "Servers", body: "Waits for Epic." });
    });
    expect(requestOpenWorkflowsTab).toHaveBeenCalled();
    expect(requestFocusGraph).toHaveBeenCalledWith("wf1", { nodes: ["servers"], select: true });
    expect(screen.getByRole("dialog", { name: "Servers" })).toBeTruthy();
  });

  it("runs a UI action before looking, and a new one replaces the old", async () => {
    render(<ShowMeLayer />);
    const run = vi.fn(() => { target("demo.menu.item", "Item"); });
    const off = registerUiAction("demo.open_menu", run);
    target("demo.first", "First");
    await act(async () => { await playShowMe({ target: "demo.first", title: "First", body: "" }); });
    const firstClosed = whenShowMeClosed();
    await act(async () => {
      await playShowMe({ target: "demo.menu.item", action: { id: "demo.open_menu", args: { q: 1 } }, title: "Second", body: "" });
    });
    await firstClosed;  // the first one's waiter hears it was replaced
    expect(run).toHaveBeenCalledWith({ q: 1 });
    expect(screen.queryByRole("dialog", { name: "First" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Second" })).toBeTruthy();
    off();
  });
});

describe("Show me with several steps", () => {
  it("walks the steps with Back / Next and ends with Close", async () => {
    render(<ShowMeLayer />);
    target("demo.a", "A");
    target("demo.b", "B");
    let result: Awaited<ReturnType<typeof playShowMe>> | undefined;
    const request = parseShowMeRequest({ steps: [
      { target: "demo.a", title: "First", body: "One" },
      { target: "demo.b", title: "Second", body: "Two" },
    ] })!;
    await act(async () => {
      result = await playShowMe(request);
    });
    expect(result).toMatchObject({ shown: true, steps: 2 });
    expect(screen.getByRole("dialog", { name: "First" })).toBeTruthy();
    expect(screen.getByText("1 / 2")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await new Promise((r) => setTimeout(r, 300));
    });
    expect(screen.getByRole("dialog", { name: "Second" })).toBeTruthy();
    expect(screen.getByText("2 / 2")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Back" }));
      await new Promise((r) => setTimeout(r, 300));
    });
    expect(screen.getByRole("dialog", { name: "First" })).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await new Promise((r) => setTimeout(r, 300));
    });
    const closed = whenShowMeClosed();
    const stepClose = screen.getAllByRole("button", { name: "Close" }).find((b) => b.classList.contains("showme-step-btn"));
    expect(stepClose).toBeTruthy();
    act(() => fireEvent.click(stepClose!));
    await closed;
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(getShowMeState().request).toBeNull();
  });

  it("moves on when the user clicks the highlight on a click step", async () => {
    render(<ShowMeLayer />);
    const a = target("demo.a", "A");
    target("demo.b", "B");
    await act(async () => {
      await playShowMe(parseShowMeRequest({ steps: [
        { target: "demo.a", title: "Press A", click: true },
        { target: "demo.b", title: "Then B" },
      ] })!);
    });
    expect(screen.getByText("Click the highlight to go on")).toBeTruthy();
    await act(async () => {
      fireEvent.click(a);
      await new Promise((r) => setTimeout(r, 700));
    });
    expect(screen.getByRole("dialog", { name: "Then B" })).toBeTruthy();
  });

  it("reads steps, with the top-level fields as step 1", () => {
    const only = parseShowMeRequest({ steps: [{ target: "a", title: "A" }, { target: "b", title: "B", click: true }, { title: "no target" }] });
    expect(only?.title).toBe("A");
    expect(only?.steps?.map((s) => s.title)).toEqual(["A", "B"]);
    expect(only?.steps?.[1].click).toBe(true);
    const top = parseShowMeRequest({ target: "z", title: "Z", steps: [{ target: "a", title: "A" }] });
    expect(top?.steps?.map((s) => s.title)).toEqual(["Z", "A"]);
    expect(parseShowMeRequest({ steps: [{ target: "a", title: "A" }] })?.steps).toBeUndefined();
  });
});

describe("Show me requests", () => {
  it("reads the AI's arguments and refuses what can't be shown", () => {
    expect(parseShowMeRequest({ target: "a.b", title: "A" })).toMatchObject({ target: "a.b", title: "A", body: "" });
    expect(parseShowMeRequest({ target: { role: "button", name: "Save" }, body: "Saves it" })).toMatchObject({ title: "Saves it" });
    expect(parseShowMeRequest({ target: ["workflows.node.a", "workflows.node.b"], title: "Both", workflow_id: "w" })).toMatchObject({ workflow_id: "w" });
    expect(parseShowMeRequest({ target: "a", title: "x", action: { id: "workflows.add_menu", args: { query: "if" } } })?.action).toEqual({ id: "workflows.add_menu", args: { query: "if" } });
    expect(parseShowMeRequest({ title: "no target" })).toBeNull();
    expect(parseShowMeRequest({ target: "a.b" })).toBeNull();
    expect(parseShowMeRequest({ target: [], title: "x" })).toBeNull();
  });
});
