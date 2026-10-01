import { describe, expect, it } from "vitest";

import { encodeWavPcm16, isTooShortRecording, pickTranscriptionBackend } from "./transcriptionSession";
import { normalizeSttProvider } from "./voiceSettings";

describe("encodeWavPcm16", () => {
  it("writes a valid mono 16-bit WAV header", async () => {
    const samples = new Float32Array([0, 0.5, -0.5, 0]);
    const blob = encodeWavPcm16(samples, 16000);
    expect(blob.type).toBe("audio/wav");
    expect(blob.size).toBe(44 + samples.length * 2);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(String.fromCharCode(...bytes.subarray(0, 4))).toBe("RIFF");
    expect(String.fromCharCode(...bytes.subarray(8, 12))).toBe("WAVE");
    expect(String.fromCharCode(...bytes.subarray(12, 16))).toBe("fmt ");
    expect(String.fromCharCode(...bytes.subarray(36, 40))).toBe("data");
  });
});

describe("isTooShortRecording", () => {
  it("rejects empty and silent buffers", () => {
    expect(isTooShortRecording(new Float32Array(0), 24000)).toBe(true);
    expect(isTooShortRecording(new Float32Array(24000), 24000)).toBe(true);
  });

  it("accepts a second of audible speech", () => {
    const samples = new Float32Array(24000);
    for (let i = 0; i < samples.length; i += 1) samples[i] = Math.sin(i / 20) * 0.2;
    expect(isTooShortRecording(samples, 24000)).toBe(false);
  });
});

describe("pickTranscriptionBackend", () => {
  const desktop = { windowsSpeech: true, browserSpeech: false };
  const phone = { windowsSpeech: false, browserSpeech: true };

  it("uses Windows speech in the desktop app — never the dead WebView2 browser speech", () => {
    expect(pickTranscriptionBackend({ preference: "", ...desktop, openaiReady: false })).toEqual({
      backend: "windows",
      openaiMissingKey: false,
    });
    expect(pickTranscriptionBackend({ preference: "webspeech", ...desktop, openaiReady: true }).backend).toBe(
      "windows",
    );
  });

  it("uses browser speech on a phone", () => {
    expect(pickTranscriptionBackend({ preference: "", ...phone, openaiReady: false }).backend).toBe("webspeech");
  });

  it("uses OpenAI when picked and a key is saved", () => {
    expect(pickTranscriptionBackend({ preference: "openai", ...desktop, openaiReady: true })).toEqual({
      backend: "openai",
      openaiMissingKey: false,
    });
  });

  it("flags a missing OpenAI key instead of silently swapping engines", () => {
    expect(pickTranscriptionBackend({ preference: "openai", ...desktop, openaiReady: false })).toEqual({
      backend: "windows",
      openaiMissingKey: true,
    });
    expect(
      pickTranscriptionBackend({ preference: "openai", windowsSpeech: false, browserSpeech: false, openaiReady: false }),
    ).toEqual({ backend: "none", openaiMissingKey: true });
  });

  it("falls back to OpenAI only when no system engine exists", () => {
    const none = { windowsSpeech: false, browserSpeech: false };
    expect(pickTranscriptionBackend({ preference: "", ...none, openaiReady: true }).backend).toBe("openai");
    expect(pickTranscriptionBackend({ preference: "", ...none, openaiReady: false }).backend).toBe("none");
  });

  it("normalizes listen preference", () => {
    expect(normalizeSttProvider("OpenAI")).toBe("openai");
    expect(normalizeSttProvider("default")).toBe("");
    expect(normalizeSttProvider("")).toBe("");
  });
});
