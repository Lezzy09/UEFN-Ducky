// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// A live link to the other PC that records what the picture sends there.
const { fake, sent } = vi.hoisted(() => {
  const sent: Record<string, unknown>[] = [];
  const status = { state: "live", reason: "", desktopVersion: "" };
  const fake = {
    status,
    peer: null,
    invoke: async (name: string) => (name === "list_window_views" ? [] : { ok: true }),
    onVideo: () => () => {},
    onStatus: (fn: (s: typeof status) => void) => {
      fn(status);
      return () => {};
    },
    sendInput: (payload: Record<string, unknown>) => {
      sent.push(payload);
      return true;
    },
    retry: () => {},
    restart: () => {},
  };
  return { fake, sent };
});

vi.mock("../remote/directTransport", async (original) => ({
  ...(await original<typeof import("../remote/directTransport")>()),
  getDirectTransport: () => fake,
}));

import { RemoteWindowOverlay } from "./RemoteWindowView";

const VIDEO = { videoWidth: 1600, videoHeight: 900, readyState: 4 } as const;

function useScreen(desktop: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: desktop && query.includes("pointer: fine"),
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
}

async function showPicture() {
  const { container } = render(<RemoteWindowOverlay hwnd="monitor:1" />);
  await act(async () => {
    await Promise.resolve();
  });
  const video = container.querySelector("video") as HTMLVideoElement;
  await act(async () => void video.dispatchEvent(new Event("loadeddata")));
  return video;
}

const frame = () => new Promise((resolve) => window.setTimeout(resolve, 40));

beforeEach(() => {
  sent.length = 0;
  globalThis.ResizeObserver ??= class {
    observe() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  for (const [key, value] of Object.entries(VIDEO)) {
    Object.defineProperty(HTMLVideoElement.prototype, key, { configurable: true, get: () => value });
  }
  HTMLMediaElement.prototype.play = () => Promise.resolve();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: 800, height: 450, right: 800, bottom: 450, x: 0, y: 0, toJSON: () => ({}),
  } as DOMRect);
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  for (const key of Object.keys(VIDEO)) delete (HTMLVideoElement.prototype as unknown as Record<string, unknown>)[key];
});

it("on a PC the mouse moves the PC's mouse with no button held, and there is no typing box", async () => {
  useScreen(true);
  const video = await showPicture();
  expect(screen.queryByLabelText("Type on the PC")).toBeNull();
  fireEvent.pointerMove(video, { pointerType: "mouse", pointerId: 1, buttons: 0, clientX: 400, clientY: 225 });
  await frame();
  expect(sent).toContainEqual({ type: "move", x: 0.5, y: 0.5, button: 0 });
});

it("a pointer passing over a window in the background moves nothing", async () => {
  useScreen(true);
  const video = await showPicture();
  vi.spyOn(document, "hasFocus").mockReturnValue(false);
  fireEvent.pointerMove(video, { pointerType: "mouse", pointerId: 1, buttons: 0, clientX: 400, clientY: 225 });
  await frame();
  expect(sent.filter((p) => p.type === "move")).toEqual([]);
});

it("keys go to the PC, held keys repeat there, and this app's shortcuts never see them", async () => {
  useScreen(true);
  const video = await showPicture();
  const app = vi.fn();
  window.addEventListener("keydown", app);
  fireEvent.keyDown(video, { key: "Backspace" });
  fireEvent.keyDown(video, { key: "Backspace", repeat: true });
  fireEvent.keyUp(video, { key: "Backspace" });
  window.removeEventListener("keydown", app);
  expect(sent.filter((p) => p.type === "keydown" || p.type === "keyup")).toEqual([
    { type: "keydown", key: "Backspace" },
    { type: "keydown", key: "Backspace" },
    { type: "keyup", key: "Backspace" },
  ]);
  expect(app).not.toHaveBeenCalled();
});

it("on a phone the typing box stays under the picture", async () => {
  useScreen(false);
  await showPicture();
  expect(screen.getByLabelText("Type on the PC")).toBeTruthy();
});
