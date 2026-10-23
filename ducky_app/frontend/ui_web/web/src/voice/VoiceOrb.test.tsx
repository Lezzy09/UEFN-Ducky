// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceOrb, type VoiceOrbStatus } from "./VoiceOrb";

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduce && query.includes("reduce"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  window.matchMedia = globalThis.matchMedia;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VoiceOrb", () => {
  const statuses: VoiceOrbStatus[] = ["listening", "thinking", "speaking", "muted", "error"];

  it.each(statuses)("uses the %s state class", (status) => {
    mockReducedMotion(false);
    const { container } = render(<VoiceOrb status={status} />);
    const orb = container.querySelector(".voice-orb")!;
    expect(orb.classList.contains(`voice-orb--${status}`)).toBe(true);
    expect(orb.getAttribute("data-animated")).toBe("true");
    expect(orb.classList.contains("voice-orb--still")).toBe(false);
  });

  it("scales with the mic level while listening", () => {
    mockReducedMotion(false);
    const { container } = render(<VoiceOrb status="listening" level={0.6} />);
    const orb = container.querySelector<HTMLElement>(".voice-orb")!;
    expect(orb.style.getPropertyValue("--orb-level")).toBe("0.6");
    expect(orb.classList.contains("voice-orb--reactive")).toBe(true);
  });

  it("turns the animation off when the OS asks for reduced motion", () => {
    mockReducedMotion(true);
    const { container } = render(<VoiceOrb status="speaking" level={0.8} />);
    const orb = container.querySelector<HTMLElement>(".voice-orb")!;
    expect(orb.classList.contains("voice-orb--still")).toBe(true);
    expect(orb.getAttribute("data-animated")).toBe("false");
    expect(orb.style.getPropertyValue("--orb-level")).toBe("0");
  });

  it("honors an explicit reducedMotion prop", () => {
    mockReducedMotion(false);
    const { container } = render(<VoiceOrb status="thinking" reducedMotion />);
    expect(container.querySelector(".voice-orb--still")).toBeTruthy();
  });
});
