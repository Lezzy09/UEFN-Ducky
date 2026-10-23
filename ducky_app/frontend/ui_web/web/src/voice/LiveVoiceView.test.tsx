// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get_settings: vi.fn(async () => ({})),
  save_agent_settings: vi.fn(async () => ({ ok: true })),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
vi.mock("./pluginVoices", () => ({ useTtsVoiceOptions: () => [] }));

import { patchLiveVoiceState, setLiveVoiceChat, type LiveVoiceUiStatus } from "./liveChats";
import { lastLine, LiveVoiceView } from "./LiveVoiceView";

const CHAT = "live-view";

afterEach(() => {
  cleanup();
  setLiveVoiceChat(CHAT, false);
  vi.clearAllMocks();
});

function view(extra: Partial<Parameters<typeof LiveVoiceView>[0]> = {}) {
  return render(
    <LiveVoiceView chatId={CHAT} onEnd={vi.fn()} onShowChat={vi.fn()} muted={false} setMuted={vi.fn()} {...extra} />,
  );
}

describe("LiveVoiceView", () => {
  const cases: Array<[LiveVoiceUiStatus, string, string]> = [
    ["listening", "listening", "Listening"],
    ["thinking", "thinking", "Thinking"],
    ["connecting", "thinking", "Thinking"],
    ["speaking", "speaking", "Speaking"],
    ["muted", "muted", "Mic muted"],
    ["error", "error", "Mic problem"],
  ];

  it.each(cases)("shows the %s status on the chip and orb", (live, orb, chip) => {
    setLiveVoiceChat(CHAT, true);
    patchLiveVoiceState(CHAT, { status: live, error: live === "error" ? "No mic found" : "" });
    const { container } = view();
    const root = screen.getByRole("dialog", { name: "Live voice" });
    expect(root.getAttribute("data-status")).toBe(orb);
    expect(screen.getByRole("status").textContent).toContain(chip);
    expect(container.querySelector(`.voice-orb--${orb}`)).toBeTruthy();
  });

  it("captions the user's interim words, then Ducky's last spoken line", () => {
    setLiveVoiceChat(CHAT, true);
    patchLiveVoiceState(CHAT, { status: "listening", userInterim: "make it blue" });
    view();
    expect(screen.getByText("make it blue")).toBeTruthy();
    act(() => {
      patchLiveVoiceState(CHAT, {
        status: "speaking",
        userInterim: "",
        spokenText: "Found two errors. Fixing the second error",
      });
    });
    expect(screen.getByText("Fixing the second error")).toBeTruthy();
  });

  it("adds the work status to the chip when given", () => {
    setLiveVoiceChat(CHAT, true);
    patchLiveVoiceState(CHAT, { status: "thinking" });
    view({ workStatus: "Reading voice settings" });
    expect(screen.getByRole("status").textContent).toContain("Reading voice settings");
  });

  it("mutes, ends and opens the settings sheet with the pickers", () => {
    setLiveVoiceChat(CHAT, true);
    patchLiveVoiceState(CHAT, { status: "listening" });
    const setMuted = vi.fn();
    const onEnd = vi.fn();
    view({ setMuted, onEnd, setVoiceId: vi.fn(), setSpeed: vi.fn() });
    fireEvent.click(screen.getByLabelText("Mute microphone"));
    expect(setMuted).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByLabelText("End live voice"));
    expect(onEnd).toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Voice settings" })).toBeNull();
    fireEvent.click(screen.getByLabelText("Voice settings"));
    const sheet = screen.getByRole("dialog", { name: "Voice settings" });
    expect(sheet.querySelector(".live-voice-pickers")).toBeTruthy();
  });

  it("'Show chat' brings the transcript back", () => {
    setLiveVoiceChat(CHAT, true);
    patchLiveVoiceState(CHAT, { status: "listening" });
    function Host() {
      const [chatShown, setChatShown] = useState(false);
      return chatShown ? (
        <div>
          <p>transcript</p>
          <button type="button" onClick={() => setChatShown(false)}>
            Voice view
          </button>
        </div>
      ) : (
        <LiveVoiceView chatId={CHAT} onEnd={vi.fn()} onShowChat={() => setChatShown(true)} muted={false} setMuted={vi.fn()} />
      );
    }
    render(<Host />);
    fireEvent.click(screen.getByLabelText("Show chat"));
    expect(screen.getByText("transcript")).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "Live voice" })).toBeNull();
    fireEvent.click(screen.getByText("Voice view"));
    expect(screen.getByRole("dialog", { name: "Live voice" })).toBeTruthy();
  });

  it("uses the phone layout class on narrow screens", () => {
    setLiveVoiceChat(CHAT, true);
    const wide = view({ narrow: false });
    expect(wide.container.querySelector(".live-voice-view--narrow")).toBeNull();
    wide.unmount();
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query.includes("max-width: 600px"),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    window.matchMedia = globalThis.matchMedia;
    const phone = view();
    expect(phone.container.querySelector(".live-voice-view--narrow")).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it("keeps the caption to the last sentence", () => {
    expect(lastLine("One. Two? Three")).toBe("Three");
    expect(lastLine("  ")).toBe("");
  });
});
