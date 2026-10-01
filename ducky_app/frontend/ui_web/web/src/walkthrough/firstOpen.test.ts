import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./persistence", () => ({ whenWalkthroughHydrated: () => Promise.resolve() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => ({ get_settings: async () => ({ first_open_tours: true }) }) }));

import { asGuidedUi } from "../ui-targets/guidedBusy";
import { _resetFirstOpenForTests, setFirstOpenToursAllowed, startFirstOpenTour } from "./firstOpen";
import { _resetWalkthroughServiceForTests, getWalkthroughState, registerTour, setCompletedMap, skipTour } from "./WalkthroughService";

const TOUR = { id: "demo.view", title: "Demo", autoStart: "never" as const, steps: [{ target: "demo.a", title: "A", body: "a", advance: "next" as const }] };

beforeEach(() => {
  _resetWalkthroughServiceForTests();
  _resetFirstOpenForTests();
  registerTour(TOUR);
  setCompletedMap({ "app.shell": true });
});
afterEach(async () => {
  if (getWalkthroughState().active) await skipTour();
});

describe("first-open tours", () => {
  it("start once, the first time the view opens", async () => {
    expect(await startFirstOpenTour("demo.view", 0)).toBe(true);
    expect(getWalkthroughState().tourId).toBe("demo.view");
    await skipTour();
    expect(await startFirstOpenTour("demo.view", 0)).toBe(false);
  });

  it("don't start when done, switched off, or before Welcome", async () => {
    setCompletedMap({ "app.shell": true, "demo.view": true });
    expect(await startFirstOpenTour("demo.view", 0)).toBe(false);

    _resetFirstOpenForTests();
    setCompletedMap({ "app.shell": true });
    setFirstOpenToursAllowed(false);
    expect(await startFirstOpenTour("demo.view", 0)).toBe(false);

    _resetFirstOpenForTests();
    setCompletedMap({});
    expect(await startFirstOpenTour("demo.view", 0)).toBe(false);  // Welcome first
    setCompletedMap({ "app.shell": true });
    expect(await startFirstOpenTour("demo.view", 0)).toBe(true);  // next time the view opens
  });

  it("wait while Ducky is showing something (it opened the view)", async () => {
    await asGuidedUi(async () => {
      expect(await startFirstOpenTour("demo.view", 0)).toBe(false);
    });
    expect(await startFirstOpenTour("demo.view", 0)).toBe(true);
  });
});
