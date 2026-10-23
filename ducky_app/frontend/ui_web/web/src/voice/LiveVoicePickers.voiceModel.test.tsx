// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./ttsEngine", () => ({ ttsEngine: { getProgress: () => ({}), onProgress: () => () => {} } }));
vi.mock("./pluginVoices", () => ({ useTtsVoiceOptions: () => [] }));
vi.mock("./transcriptionSession", () => ({ windowsSpeechUsable: () => true, browserSpeechUsable: () => false }));
vi.mock("../hooks/usePanelApi", () => ({ isRemote: () => false, getApi: () => null }));
vi.mock("./micPermission", () => ({
  listMicDevices: async () => ({ devices: [], defaultLabel: "Mic" }),
  listOutputDevices: async () => ({ devices: [], defaultLabel: "Speakers" }),
}));
vi.mock("../components/ModelSelector", () => ({
  ModelSelector: (p: { selectedModel: string; setSelectedModel: (v: string) => void; placeholder?: string }) => (
    <button type="button" aria-label={p.placeholder} data-model={p.selectedModel} onClick={() => p.setSelectedModel("claude_code:claude-sonnet-5-5")}>
      {p.selectedModel || p.placeholder}
    </button>
  ),
}));

import { LiveVoicePickers, voiceModelChatId } from "./LiveVoicePickers";
import { setLiveVoiceChat } from "./liveChats";
import { _resetVoiceSettingsCache, resolveVoiceModel } from "./voiceSettings";

beforeEach(() => {
  localStorage.clear();
  _resetVoiceSettingsCache();
});
afterEach(() => {
  cleanup();
  setLiveVoiceChat("one", false);
  setLiveVoiceChat("two", false);
});

describe("voice model chip", () => {
  it("sets the live chat's own voice model", () => {
    render(<LiveVoicePickers chatId="one" voiceId="" speed={1} setVoiceId={vi.fn()} setSpeed={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "Voice: chat's model" });
    fireEvent.click(chip);
    expect(resolveVoiceModel("one")).toBe("claude_code:claude-sonnet-5-5");
    expect(resolveVoiceModel("other")).toBe("");
    expect(chip.getAttribute("data-model")).toBe("claude_code:claude-sonnet-5-5");
  });

  it("falls back to the only live chat when no chat is given", () => {
    setLiveVoiceChat("one", true);
    expect(voiceModelChatId()).toBe("one");
    setLiveVoiceChat("two", true);
    expect(voiceModelChatId()).toBe("");
    expect(voiceModelChatId("two")).toBe("two");
  });
});
