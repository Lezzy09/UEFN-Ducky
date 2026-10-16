// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({ firstRun: vi.fn() }));

vi.mock("../hooks/onApiReady", () => ({
  onApiReady: (cb: (api: unknown) => void) => {
    cb({ welcome_ducky_first_run: fake.firstRun });
    return () => {};
  },
}));
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

import { registerOpenChatReference } from "../navigation/openChatReference";
import { registerBuiltinTours } from "./builtinTours";
import { _resetFirstRunSetupForTests, reportFirstRunSetup } from "./firstRunSetup";
import { TourOffer } from "./TourOffer";
import { WalkthroughHost } from "./WalkthroughHost";
import {
  _resetWalkthroughServiceForTests,
  getWalkthroughState,
  registerTour,
  setCompletedMap,
  skipTour,
} from "./WalkthroughService";

let opened: string[] = [];
let unregister: () => void = () => {};

beforeEach(() => {
  _resetWalkthroughServiceForTests();
  _resetFirstRunSetupForTests();
  fake.firstRun.mockReset();
  opened = [];
  unregister = registerOpenChatReference((chat) => opened.push(chat.id));
});

afterEach(async () => {
  cleanup();
  unregister();
  await act(() => skipTour());
});

describe("first start after an install", () => {
  it("opens the welcome ducky and starts the Welcome walkthrough once the setup closes", async () => {
    fake.firstRun.mockResolvedValue({ ok: true, created: true, id: "welcome-1", title: "Welcome to Ducky" });
    reportFirstRunSetup(true); // a fresh install shows the setup (Welcome → plugins → Connect AI) first
    render(<WalkthroughHost />);

    await waitFor(() => expect(opened).toEqual(["welcome-1"]));
    expect(fake.firstRun).toHaveBeenCalledOnce();
    expect(getWalkthroughState().active).toBe(false); // not over the setup

    reportFirstRunSetup(false); // Finish
    await waitFor(() => expect(getWalkthroughState().tourId).toBe("app.shell"), { timeout: 3000 });
  });

  it("opens nothing and does not repeat the walkthrough on a later start", async () => {
    fake.firstRun.mockResolvedValue({ ok: true, created: false });
    setCompletedMap({ "app.shell": true });
    reportFirstRunSetup(false);
    render(<WalkthroughHost />);

    await waitFor(() => expect(fake.firstRun).toHaveBeenCalledOnce());
    await act(() => new Promise((r) => setTimeout(r, 700)));
    expect(opened).toEqual([]);
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
