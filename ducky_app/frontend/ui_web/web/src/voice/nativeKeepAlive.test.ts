// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const svc = vi.hoisted(() => ({ stopLiveChat: vi.fn() }));
vi.mock("./liveSpeakService", () => svc);

type Cap = { Plugins?: Record<string, unknown> };
const g = globalThis as { Capacitor?: Cap };

function installPlugin() {
  const LiveVoice = { start: vi.fn().mockResolvedValue({ running: true }), stop: vi.fn().mockResolvedValue({ running: false }) };
  g.Capacitor = { Plugins: { LiveVoice } };
  return LiveVoice;
}

async function freshLiveChats() {
  vi.resetModules();
  return import("./liveChats");
}

beforeEach(() => svc.stopLiveChat.mockReset());
afterEach(() => {
  delete g.Capacitor;
});

describe("native keep-alive", () => {
  it("starts on the first live chat and stops after the last", async () => {
    const plugin = installPlugin();
    const { setLiveVoiceChat } = await freshLiveChats();
    setLiveVoiceChat("a", true);
    setLiveVoiceChat("b", true);
    expect(plugin.start).toHaveBeenCalledTimes(1);
    expect(plugin.stop).not.toHaveBeenCalled();
    setLiveVoiceChat("a", false);
    expect(plugin.stop).not.toHaveBeenCalled();
    setLiveVoiceChat("b", false);
    expect(plugin.stop).toHaveBeenCalledTimes(1);
    expect(plugin.start).toHaveBeenCalledTimes(1);
  });

  it("does nothing without the plugin (desktop, browser)", async () => {
    const { setLiveVoiceChat, getLiveVoiceChatIds } = await freshLiveChats();
    setLiveVoiceChat("a", true);
    setLiveVoiceChat("a", false);
    expect(getLiveVoiceChatIds().size).toBe(0);
    g.Capacitor = { Plugins: {} };
    setLiveVoiceChat("a", true);
    setLiveVoiceChat("a", false);
  });

  it("tries again on the next live chat after a refused start", async () => {
    const plugin = installPlugin();
    plugin.start.mockRejectedValueOnce(new Error("mic_permission"));
    const { setLiveVoiceChat } = await freshLiveChats();
    setLiveVoiceChat("a", true);
    await Promise.resolve();
    await Promise.resolve();
    setLiveVoiceChat("b", true);
    expect(plugin.start).toHaveBeenCalledTimes(2);
    setLiveVoiceChat("a", false);
    setLiveVoiceChat("b", false);
  });

  it("the notification's Stop ends every live chat without calling stop back", async () => {
    const plugin = installPlugin();
    const { setLiveVoiceChat } = await freshLiveChats();
    svc.stopLiveChat.mockImplementation((id: string) => setLiveVoiceChat(id, false));
    setLiveVoiceChat("a", true);
    setLiveVoiceChat("b", true);
    document.dispatchEvent(new CustomEvent("ud:live-voice-stop"));
    await vi.waitFor(() => expect(svc.stopLiveChat).toHaveBeenCalledTimes(2));
    expect(svc.stopLiveChat.mock.calls.map((c) => c[0]).sort()).toEqual(["a", "b"]);
    expect(plugin.stop).not.toHaveBeenCalled();
    expect(plugin.start).toHaveBeenCalledTimes(1);
    setLiveVoiceChat("c", true);
    expect(plugin.start).toHaveBeenCalledTimes(2);
    setLiveVoiceChat("c", false);
  });

  it("a Stop with nothing live doesn't block the next start", async () => {
    const plugin = installPlugin();
    const { setLiveVoiceChat } = await freshLiveChats();
    document.dispatchEvent(new CustomEvent("ud:live-voice-stop"));
    setLiveVoiceChat("a", true);
    expect(plugin.start).toHaveBeenCalledTimes(1);
    setLiveVoiceChat("a", false);
  });
});
