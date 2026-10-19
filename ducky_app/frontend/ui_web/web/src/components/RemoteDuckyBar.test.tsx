// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RemoteDuckyBar } from "./RemoteDuckyBar";
import { setRemotePicture } from "../remote/remotePicture";

type Host = Window & { chrome?: { webview?: { postMessage: (m: unknown) => void } } };
let posted: unknown[][];

beforeEach(() => {
  posted = [];
  (window as Host).chrome = { webview: { postMessage: (m) => posted.push(m as unknown[]) } };
});

afterEach(() => {
  cleanup();
  delete (window as Host).chrome;
  document.documentElement.className = "";
  act(() => setRemotePicture(null));
});

const chromeCalls = () =>
  posted.filter((m) => m[0] === "uefnWindowChrome").map((m) => JSON.parse(String(m[1])) as unknown[]);

it("is this window's own title bar: its buttons reach this window, not the other Ducky", () => {
  render(<RemoteDuckyBar name="Ashins" />);
  fireEvent.click(screen.getByTitle("Minimize"));
  fireEvent.click(screen.getByTitle("Maximize"));
  fireEvent.click(screen.getByTitle("Full screen (F11)"));
  fireEvent.click(screen.getByTitle("Close"));
  expect(chromeCalls()).toEqual([["minimize"], ["maximize", true], ["fullscreen", true], ["close"]]);
});

it("F11 toggles full screen before a stream can send it to the PC", async () => {
  render(<RemoteDuckyBar name="Ashins" />);
  // The focused picture: it sends every key it gets to the PC.
  const picture = document.createElement("video");
  document.body.appendChild(picture);
  const toPc = vi.fn();
  picture.addEventListener("keydown", toPc);
  fireEvent.keyDown(picture, { key: "F11" });
  // Python marks the page once the window is full screen.
  await act(async () => document.documentElement.classList.add("window-fullscreen"));
  fireEvent.keyDown(picture, { key: "F11" });
  picture.remove();
  expect(chromeCalls()).toEqual([["fullscreen", true], ["fullscreen", false]]);
  expect(toPc).not.toHaveBeenCalled();
  expect(screen.getByTitle("Exit full screen (F11)")).toBeTruthy();
  expect(screen.queryByTitle("Minimize")).toBeNull();
});

it("offers Fit only while a PC picture shows, sized to it", () => {
  render(<RemoteDuckyBar name="Ashins" />);
  expect(screen.queryByLabelText("Fit to screen")).toBeNull();
  const area = document.createElement("div");
  area.className = "remote-window-screen";
  document.body.appendChild(area);
  act(() => setRemotePicture({ w: 1920, h: 1080 }));
  fireEvent.click(screen.getByLabelText("Fit to screen"));
  area.remove();
  const [op, w, h] = chromeCalls()[0];
  expect([op, w, h]).toEqual(["fit", 1920, 1080]);
});
