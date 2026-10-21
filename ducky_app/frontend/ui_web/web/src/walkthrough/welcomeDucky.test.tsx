// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({ finish: vi.fn(), intro: { armed: 0, done: vi.fn() } }));

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => ({ finish_first_run_setup: fake.finish }) }));
vi.mock("../hooks/usePluginContributions", () => ({
  usePluginContributions: () => ({ ready: false, walkthroughs: [], enabled_ids: [] }),
}));
vi.mock("./persistence", () => ({
  installWalkthroughPersistence: () => () => {},
  whenWalkthroughHydrated: () => Promise.resolve(),
}));
vi.mock("./WalkthroughOverlay", () => ({ WalkthroughOverlay: () => null }));
vi.mock("../hooks/useAgentEventBus", () => ({
  installAgentEventBus: () => {},
  subscribeAgentEvents: () => () => {},
}));
vi.mock("./introTyping", () => ({
  armIntro: () => {
    fake.intro.armed += 1;
  },
  disarmIntro: () => {
    fake.intro.armed -= 1;
  },
  whenIntroDone: () => fake.intro.done(),
}));

import { registerOpenChatReference } from "../navigation/openChatReference";
import { OPEN_DOCK_SIDE_EVENT, OPEN_SIDEBAR_PANEL_EVENT } from "../navigation/openSidebarPanel";
import { registerBuiltinTours } from "./builtinTours";
import { _resetFirstRunSetupForTests, FIRST_RUN_TOUR_ID, reportFirstRunSetup } from "./firstRunSetup";
import { TourOffer } from "./TourOffer";
import { WalkthroughHost } from "./WalkthroughHost";
import { welcomeAfterSetup } from "./welcomeDucky";
import {
  _resetWalkthroughServiceForTests,
  getWalkthroughState,
  isCompleted,
  registerTour,
  setCompletedMap,
  skipTour,
} from "./WalkthroughService";

let opened: string[] = [];
let unregister: () => void = () => {};

beforeEach(() => {
  _resetWalkthroughServiceForTests();
  _resetFirstRunSetupForTests();
  fake.finish.mockReset();
  fake.intro.armed = 0;
  fake.intro.done.mockReset().mockResolvedValue(undefined);
  opened = [];
  unregister = registerOpenChatReference((chat) => opened.push(chat.id));
});

afterEach(async () => {
  cleanup();
  unregister();
  await act(() => skipTour());
});

describe("the app around a first-run setup", () => {
  it("starts no tour behind the setup, and leaves the first tour to its Finish", async () => {
    reportFirstRunSetup(true); // a fresh install shows the setup first
    render(<WalkthroughHost />);
    await act(() => new Promise((r) => setTimeout(r, 700)));
    expect(getWalkthroughState().active).toBe(false);
    expect(opened).toEqual([]); // no chat opens behind it either

    reportFirstRunSetup(false); // Finish: welcomeAfterSetup runs the first-run tour itself
    await act(() => new Promise((r) => setTimeout(r, 1200)));
    expect(getWalkthroughState().tourId).not.toBe("app.shell");
  });

  it("starts the Welcome tour for an install that never saw the setup", async () => {
    reportFirstRunSetup(false);
    render(<WalkthroughHost />);
    await waitFor(() => expect(getWalkthroughState().tourId).toBe("app.shell"), { timeout: 3000 });
  });
});

describe("welcomeAfterSetup", () => {
  it("opens the left dock, the welcome ducky typed out, then the first-run tour", async () => {
    registerBuiltinTours(registerTour);
    const sides: string[] = [];
    const panels: string[] = [];
    const onSide = (e: Event) => sides.push((e as CustomEvent<{ side: string }>).detail.side);
    const onPanel = (e: Event) => panels.push((e as CustomEvent<{ panel: string }>).detail.panel);
    window.addEventListener(OPEN_DOCK_SIDE_EVENT, onSide);
    window.addEventListener(OPEN_SIDEBAR_PANEL_EVENT, onPanel);
    fake.finish.mockImplementation(async () => {
      expect(fake.intro.armed).toBe(1); // armed before the chat can open
      return { ok: true, created: true, id: "welcome-1", title: "Welcome to Ducky" };
    });

    await act(() => welcomeAfterSetup());
    window.removeEventListener(OPEN_DOCK_SIDE_EVENT, onSide);
    window.removeEventListener(OPEN_SIDEBAR_PANEL_EVENT, onPanel);

    expect(sides).toContain("left");
    expect(panels).toEqual(["chats"]);
    expect(opened).toEqual(["welcome-1"]);
    expect(fake.intro.done).toHaveBeenCalledOnce();
    expect(isCompleted("chat.composer")).toBe(true); // the first-run tour covers it
    expect(getWalkthroughState().tourId).toBe(FIRST_RUN_TOUR_ID);
  });

  it("opens no chat and no tour when no welcome ducky was made", async () => {
    registerBuiltinTours(registerTour);
    fake.finish.mockResolvedValue({ ok: true, created: false });
    await act(() => welcomeAfterSetup());
    expect(opened).toEqual([]);
    expect(fake.intro.armed).toBe(0);
    expect(getWalkthroughState().active).toBe(false);
  });
});

describe("the welcome ducky's walkthrough choices", () => {
  it("lists each offered tour with a Start button that runs it", async () => {
    registerBuiltinTours(registerTour);
    setCompletedMap({ "app.shell": true });
    render(<TourOffer ids={["app.shell", "chat.composer", "not.a.tour"]} />);

    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".tour-offer-title")?.textContent)).toEqual(["WelcomeSeen", "Chat"]);
    fireEvent.click(rows[1]!.querySelector("button")!);
    await waitFor(() => expect(getWalkthroughState().tourId).toBe("chat.composer"), { timeout: 3000 });
    await waitFor(() => expect(rows[1]!.querySelector("button")!.textContent).toBe("Running"));
  });
});
