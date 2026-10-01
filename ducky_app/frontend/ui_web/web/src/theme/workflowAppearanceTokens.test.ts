import { describe, expect, it } from "vitest";
import { computeCssVars, ALL_TOKEN_IDS } from "./tokenEngine";
import { defaultFoundation } from "./defaultTokens";
import { APPEARANCE_UI_SECTIONS } from "./appearanceSections";
import { WORKFLOW_APPEARANCE_TOKEN_IDS } from "./workflowAppearanceTokens";

describe("workflow appearance tokens", () => {
  it("gives the canvas the same background as the chats by default and node colors from the theme", () => {
    const vars = computeCssVars({ foundation: defaultFoundation(), overrides: {}, statusOverrides: {} });
    expect(vars["wf-canvas"]).toBe(vars.bg);
    expect(vars["wf-grid-minor"]).toMatch(/^rgba\(\d+, \d+, \d+, 0\.05\)$/);  // the text color, faint
    expect(vars["wf-node-starter"]).toBe(vars.red);
    expect(vars["wf-node-action"]).toBe(vars.blue);
    expect(vars["wf-wire-width"]).toBe("1.5px");
    expect(vars["wf-light-off"]).toBe(vars.red);
    expect(vars["wf-panel"]).toMatch(/^rgba\(\d+, \d+, \d+, 0\.58\)$/);  // see-through, from the theme background
    expect(vars["wf-panel-blur"]).toBe("28px");
  });
  it("lets Appearance override any of them", () => {
    const vars = computeCssVars({ foundation: defaultFoundation(), overrides: { "wf-canvas": "#101820", "wf-wire-width": "3px" }, statusOverrides: {} });
    expect(vars["wf-canvas"]).toBe("#101820");
    expect(vars["wf-wire-width"]).toBe("3px");
  });
  it("has its own Appearance section and keeps its overrides", () => {
    const section = APPEARANCE_UI_SECTIONS.find((item) => item.id === "workflows");
    expect(section?.tokenIds).toEqual(WORKFLOW_APPEARANCE_TOKEN_IDS);
    expect(WORKFLOW_APPEARANCE_TOKEN_IDS.every((id) => ALL_TOKEN_IDS.includes(id))).toBe(true);
  });
});
