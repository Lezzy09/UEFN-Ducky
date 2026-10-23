// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  api: {
    get_settings: vi.fn(),
    save_agent_settings: vi.fn(),
    voice_lane_settings: vi.fn(),
    save_voice_lane_settings: vi.fn(),
  },
}));

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => mocks.api }));

import {
  _resetVoiceSettingsCache,
  getVoiceSettings,
  loadVoiceSettings,
  normalizeReplyLength,
  resolveVoiceModel,
  saveVoiceSettings,
  setChatVoiceModel,
} from "./voiceSettings";

describe("live voice model setting", () => {
  beforeEach(() => {
    localStorage.clear();
    _resetVoiceSettingsCache();
    mocks.api.get_settings.mockResolvedValue({ voice_process_talk: 0.7 });
    mocks.api.voice_lane_settings.mockResolvedValue({
      voice_live_model: "claude_code:claude-haiku-5-5",
      voice_reply_length: "normal",
    });
    mocks.api.save_voice_lane_settings.mockResolvedValue({});
    mocks.api.save_agent_settings.mockResolvedValue("ok");
  });

  it("loads the live model and reply length", async () => {
    const s = await loadVoiceSettings();
    expect(s.liveModel).toBe("claude_code:claude-haiku-5-5");
    expect(s.replyLength).toBe("normal");
  });

  it("defaults to the chat's model and short replies", async () => {
    mocks.api.voice_lane_settings.mockResolvedValue({});
    const s = await loadVoiceSettings();
    expect(s.liveModel).toBe("");
    expect(s.replyLength).toBe("short");
    expect(normalizeReplyLength("endless")).toBe("short");
  });

  it("saves lane fields through the voice lane API only when they change", async () => {
    await loadVoiceSettings();
    await saveVoiceSettings({ liveModel: "claude_code:claude-sonnet-5-5" });
    expect(mocks.api.save_voice_lane_settings).toHaveBeenCalledWith({
      voice_live_model: "claude_code:claude-sonnet-5-5",
      voice_reply_length: "normal",
    });
    mocks.api.save_voice_lane_settings.mockClear();
    await saveVoiceSettings({ processTalk: 0.3 });
    expect(mocks.api.save_voice_lane_settings).not.toHaveBeenCalled();
    expect(getVoiceSettings().liveModel).toBe("claude_code:claude-sonnet-5-5");
  });
});

describe("per-chat voice model", () => {
  beforeEach(async () => {
    localStorage.clear();
    _resetVoiceSettingsCache();
    mocks.api.get_settings.mockResolvedValue({});
    mocks.api.voice_lane_settings.mockResolvedValue({ voice_live_model: "claude_code:claude-haiku-5-5" });
    await loadVoiceSettings();
  });

  it("the chat's own value wins over the global one", () => {
    setChatVoiceModel("chat-a", "claude_code:claude-sonnet-5-5");
    expect(resolveVoiceModel("chat-a")).toBe("claude_code:claude-sonnet-5-5");
    expect(resolveVoiceModel("chat-b")).toBe("claude_code:claude-haiku-5-5");
  });

  it("clearing it falls back to the global model", () => {
    setChatVoiceModel("chat-a", "claude_code:claude-sonnet-5-5");
    setChatVoiceModel("chat-a", "");
    expect(resolveVoiceModel("chat-a")).toBe("claude_code:claude-haiku-5-5");
  });

  it("survives a reload from storage", () => {
    setChatVoiceModel("chat-a", "claude_code:claude-sonnet-5-5");
    _resetVoiceSettingsCache();
    expect(resolveVoiceModel("chat-a")).toBe("claude_code:claude-sonnet-5-5");
  });
});
