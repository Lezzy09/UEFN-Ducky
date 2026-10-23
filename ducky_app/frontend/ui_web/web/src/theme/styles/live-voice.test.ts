import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("./live-voice.css", import.meta.url)), "utf8");

/** Declarations of every rule whose selector mentions `needle` ("sel {" = exactly that selector). */
function rulesFor(needle: string): string[] {
  const exact = needle.endsWith(" {") ? needle.slice(0, -2).trim() : "";
  const out: string[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    const selectors = m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim());
    if (exact ? selectors.includes(exact) : m[1].includes(needle)) out.push(m[2]);
  }
  if (!out.length) throw new Error(`no rule for ${needle}`);
  return out;
}

function px(decls: string, prop: string): number[] {
  const re = new RegExp(`(?:^|[;\\s])${prop}:\\s*(\\d+)px`, "g");
  return [...decls.matchAll(re)].map((m) => Number(m[1]));
}

describe("live-voice.css", () => {
  it("uses Appearance vars only (no hex or rgb colors)", () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/\brgba?\(/);
    expect(css).not.toMatch(/\bhsla?\(/);
  });

  it("phone layout gives 56-64 px targets and a 64 px End button", () => {
    const btn = rulesFor(".live-voice-view--narrow .live-voice-btn {").join(";");
    const end = rulesFor(".live-voice-view--narrow .live-voice-btn--end").join(";");
    for (const size of [...px(btn, "width"), ...px(btn, "height")]) {
      expect(size).toBeGreaterThanOrEqual(56);
      expect(size).toBeLessThanOrEqual(64);
    }
    expect(px(end, "width")).toEqual([64]);
    expect(px(end, "height")).toEqual([64]);
  });

  it("phone layout pads for the safe areas", () => {
    const narrow = rulesFor(".live-voice-view--narrow {").join(";");
    for (const side of ["top", "right", "bottom", "left"]) {
      expect(narrow).toContain(`env(safe-area-inset-${side}`);
    }
  });

  it("fits a 360 px screen without horizontal overflow", () => {
    const view = rulesFor(".live-voice-view {").join(";");
    expect(view).toMatch(/overflow:\s*hidden/);
    expect(view).toMatch(/max-width:\s*100%/);
    expect(view).toMatch(/box-sizing:\s*border-box/);
    // Narrow row: 4 buttons (3 x 56 + 64) + 3 gaps of 8 + 24 px padding must fit in 360.
    const row = 3 * 56 + 64 + 3 * 8 + 2 * 12;
    expect(row).toBeLessThanOrEqual(360);
    // No fixed width wider than 360 px anywhere in the narrow rules.
    for (const decls of rulesFor("--narrow")) {
      for (const w of [...px(decls, "width"), ...px(decls, "min-width")]) expect(w).toBeLessThanOrEqual(360);
    }
    // The orb is capped by the viewport.
    expect(rulesFor(".voice-orb {").join(";")).toMatch(/max-width:\s*60vw/);
  });

  it("turns orb animation off for reduced motion", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*animation:\s*none/);
    expect(rulesFor(".voice-orb--still .voice-orb-core").join(";")).toMatch(/animation:\s*none/);
  });
});
