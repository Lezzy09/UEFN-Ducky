// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { parseSwarmResult } from "../components/tool-presenters/SwarmCard";
import type { SwarmCardData } from "../components/tool-presenters/SwarmCard";
import { SwarmTree, modelChip } from "./SwarmTree";
import fixture from "./fixtures/swarm_builder.json?raw";

const data = parseSwarmResult(fixture) as SwarmCardData;

afterEach(cleanup);

const labels = () => [...document.querySelectorAll(".rich-chart-node-label")].map((t) => t.textContent).sort();
const mark = (text: string) => screen.getByText(text).closest("g") as SVGGElement;

describe("SwarmTree", () => {
  it("draws the lead, every group and every seat of the fixture", () => {
    render(<SwarmTree data={data} leadModel="claude:claude-opus-5-5" />);
    expect(labels()).toEqual(
      [
        "Lead (Opus 5.5)",
        "Art: assets (2) · MUTED",
        "Modeling lead · Sonnet 5.5",
        "Texture lead · Sonnet 5.5",
        "Code: gameplay (2) · MUTED",
        "Verse lead · Opus 5.5",
        "UI lead · Sonnet 5.5",
        "Narrative lead · Haiku 5.5",
        "Tester · Sonnet 5.5",
      ].sort(),
    );
    expect(mark("Lead (Opus 5.5)").classList.contains("swarm-tree-node--root")).toBe(true);
    expect(mark("Art: assets (2) · MUTED").classList.contains("swarm-tree-node--muted")).toBe(true);
    expect(mark("Tester · Sonnet 5.5").classList.contains("swarm-tree-node--seat")).toBe(true);
    // The seat list carries each seat's profile icon and model chip.
    expect(document.querySelectorAll(".swarm-tree-seat").length).toBe(6);
    expect(screen.getByRole("img", { name: "verse-developer" })).toBeTruthy();
    expect([...document.querySelectorAll(".swarm-tree-model-chip")].map((c) => c.textContent)).toContain("Haiku 5.5");
  });

  it("updates when its props change: overlaps turn red, later seats are dashed, dropped seats go", () => {
    const { rerender } = render(<SwarmTree data={data} />);
    expect(mark("Verse lead · Opus 5.5").classList.contains("swarm-tree-node--overlap")).toBe(false);

    rerender(<SwarmTree data={data} overlaps={["Verse lead"]} later={{ "Code: gameplay": "P0" }} />);
    const verse = mark("Verse lead · Opus 5.5");
    expect(verse.classList.contains("swarm-tree-node--overlap")).toBe(true);
    expect(verse.classList.contains("rich-c-red")).toBe(true);
    expect(verse.classList.contains("swarm-tree-node--later")).toBe(true);
    expect((verse.querySelector("rect") as SVGRectElement).style.strokeDasharray).toBe("4 3");
    expect(mark("Code: gameplay (2) · MUTED · waits P0").classList.contains("swarm-tree-node--later")).toBe(true);
    expect(mark("Tester · Sonnet 5.5").classList.contains("swarm-tree-node--later")).toBe(false);

    rerender(<SwarmTree data={{ ...data, seats: data.seats.filter((s) => s.name !== "Tester") }} />);
    expect(labels()).not.toContain("Tester · Sonnet 5.5");
    expect(mark("Verse lead · Opus 5.5").classList.contains("swarm-tree-node--overlap")).toBe(false);
    expect((mark("Verse lead · Opus 5.5").querySelector("rect") as SVGRectElement).style.strokeDasharray).toBe("");
  });

  it("names models as chips", () => {
    expect(modelChip("claude:claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(modelChip("codex:gpt-6-luna")).toBe("gpt-6-luna");
  });
});
