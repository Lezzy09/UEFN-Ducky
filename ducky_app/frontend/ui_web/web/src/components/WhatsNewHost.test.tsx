// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsNewStatus } from "../types/panel";

const getWhatsNew = vi.fn();
const markSeen = vi.fn();
let remote = false;
vi.mock("../hooks/usePanelApi", () => ({
  getApi: () => ({ get_whats_new: getWhatsNew, mark_whats_new_seen: markSeen }),
  isRemote: () => remote,
}));
vi.mock("../hooks/onApiReady", () => ({
  onApiReady: (cb: () => void) => {
    cb();
    return () => {};
  },
}));
const requestOpenSettings = vi.fn();
vi.mock("../navigation/openSettingsTab", () => ({ requestOpenSettings }));
vi.mock("./ducky/DuckyAvatars", () => ({ DuckyAvatar: () => <span data-testid="duck" /> }));

const { WhatsNewHost, openWhatsNew } = await import("./WhatsNewHost");

const VERSIONS = [
  {
    version: "1.2.412",
    created_at: "1792368000",
    items: [
      { kind: "fix" as const, text: "Team plugins no longer reset by themselves" },
      { kind: "new" as const, text: "What's new after updates" },
    ],
  },
  { version: "1.2.410", created_at: null, items: [{ kind: "improved" as const, text: "Faster start" }] },
];

function status(over: Partial<WhatsNewStatus> = {}): WhatsNewStatus {
  return {
    current: "1.2.412",
    last_seen: "1.2.409",
    enabled: true,
    show: true,
    versions: VERSIONS,
    recent: VERSIONS,
    ...over,
  };
}

beforeEach(() => {
  remote = false;
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  markSeen.mockResolvedValue({ ok: true });
});

afterEach(() => {
  cleanup();
  getWhatsNew.mockReset();
  markSeen.mockReset();
  requestOpenSettings.mockClear();
  vi.restoreAllMocks();
});

describe("WhatsNewHost", () => {
  it("lists each unseen version's one-line changes with their marks", async () => {
    getWhatsNew.mockResolvedValue(status());
    render(<WhatsNewHost />);
    expect(await screen.findByRole("dialog", { name: "What's new" })).toBeTruthy();
    expect(screen.getByText("You're on 1.2.412")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Version 1.2.412" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Version 1.2.410" })).toBeTruthy();
    expect(screen.getByText("Team plugins no longer reset by themselves")).toBeTruthy();
    expect(screen.getByText("Fixed")).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
    expect(screen.getByText("Better")).toBeTruthy();
  });

  it("Got it saves the version as seen with the Don't show again choice", async () => {
    getWhatsNew.mockResolvedValue(status());
    render(<WhatsNewHost />);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByLabelText("Don't show again"));
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(markSeen).toHaveBeenCalledWith("1.2.412", true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("All patch notes closes it and opens Settings > General", async () => {
    getWhatsNew.mockResolvedValue(status());
    render(<WhatsNewHost />);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "All patch notes" }));
    expect(markSeen).toHaveBeenCalledWith("1.2.412", false);
    expect(requestOpenSettings).toHaveBeenCalledWith("General");
  });

  it("shows nothing when there is nothing new (seen, fresh install or offline)", async () => {
    getWhatsNew.mockResolvedValue(status({ show: false, versions: [] }));
    render(<WhatsNewHost />);
    await waitFor(() => expect(getWhatsNew).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(markSeen).not.toHaveBeenCalled();
  });

  it("waits for the window to be focused before it opens", async () => {
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    getWhatsNew.mockResolvedValue(status());
    render(<WhatsNewHost />);
    await waitFor(() => expect(getWhatsNew).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByRole("dialog")).toBeNull();
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("never opens in a browser on another device", async () => {
    remote = true;
    getWhatsNew.mockResolvedValue(status());
    render(<WhatsNewHost />);
    await act(async () => {});
    expect(getWhatsNew).not.toHaveBeenCalled();
  });

  it("Settings reopens the latest versions after they were seen", async () => {
    getWhatsNew.mockResolvedValue(status({ show: false, versions: [] }));
    render(<WhatsNewHost />);
    await waitFor(() => expect(getWhatsNew).toHaveBeenCalledTimes(1));
    act(() => openWhatsNew());
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Faster start")).toBeTruthy();
  });
});
