// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { CatalogModelRow } from "../hooks/modelsCatalogCache";
import { SeatEditor, type SwarmEdit, type SwarmSeat, parseLane } from "./SeatEditor";

afterEach(cleanup);

const seat: SwarmSeat = {
  name: "Core lead",
  job: "Core: engine",
  model: "claude:claude-sonnet-5-5",
  paths: ["src/core/**"],
  sub_plan: { title: "Core: engine", steps: [{ content: "Split the loop" }, { content: "Add the meter" }] },
};

const row = (providerKey: string, id: string, name: string) =>
  ({ providerKey, id, name, provider: providerKey }) as CatalogModelRow;
const models = [row("claude", "claude-sonnet-5-5", "Sonnet 5.5"), row("claude_code", "claude-opus-5-5", "Opus 5.5")];

function renderSeat() {
  const edits: SwarmEdit[] = [];
  render(<SeatEditor seat={seat} models={models} onEdit={(e) => edits.push(e)} />);
  return edits;
}

function retype(label: string, text: string) {
  const input = screen.getByLabelText(label);
  fireEvent.change(input, { target: { value: text } });
  fireEvent.blur(input);
}

describe("SeatEditor", () => {
  it("emits the same edits[] as the hand-written tool call", () => {
    const edits = renderSeat();
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "claude_code:claude-opus-5-5" } });
    retype("Lane paths", "src/core/**, src/meter.ts");
    retype("Step: Split the loop", "Split the event loop");
    fireEvent.change(screen.getByLabelText("New step"), { target: { value: "Write the tests" } });
    fireEvent.click(screen.getByText("Add step"));
    expect(edits).toEqual([
      { seat: "Core lead", model: "claude_code:claude-opus-5-5" },
      { seat: "Core lead", paths: ["src/core/**", "src/meter.ts"] },
      { seat: "Core lead", rename_step: "Split the loop", to: "Split the event loop" },
      { seat: "Core lead", add_step: "Write the tests" },
    ]);
  });

  it("renames and drops by job, drops steps by content, skips unchanged text", () => {
    const edits = renderSeat();
    retype("Seat name", "Engine lead");
    retype("Step: Add the meter", "Add the meter");
    fireEvent.click(screen.getByLabelText("Drop step Add the meter"));
    fireEvent.click(screen.getByText("Drop job"));
    expect(edits).toEqual([
      { rename: "Core: engine", to: "Engine lead" },
      { seat: "Core lead", drop_step: "Add the meter" },
      { drop: "Core: engine" },
    ]);
  });

  it("lists catalog models by name and keeps an unknown current model", () => {
    const edits: SwarmEdit[] = [];
    render(<SeatEditor seat={{ ...seat, model: "codex:gpt-6" }} models={models} onEdit={(e) => edits.push(e)} />);
    const values = Array.from((screen.getByLabelText("Model") as HTMLSelectElement).options).map((o) => o.value);
    expect(values).toEqual(["codex:gpt-6", "claude:claude-sonnet-5-5", "claude_code:claude-opus-5-5"]);
    expect(screen.getByText("Opus 5.5")).toBeTruthy();
  });

  it("toggling May release and dragging a step to another seat emit edits[]", () => {
    const edits: SwarmEdit[] = [];
    const other: SwarmSeat = { ...seat, name: "Store lead", job: "Store: ui", paths: ["ui/**"] };
    render(
      <>
        <SeatEditor seat={seat} models={models} onEdit={(e) => edits.push(e)} />
        <SeatEditor seat={other} models={models} onEdit={(e) => edits.push(e)} />
      </>,
    );
    fireEvent.click(screen.getAllByLabelText("May release/publish")[0]);
    const data = new Map<string, string>();
    const dataTransfer = { setData: (k: string, v: string) => data.set(k, v), getData: (k: string) => data.get(k) ?? "" };
    fireEvent.dragStart(screen.getAllByLabelText("Step: Add the meter")[0].closest("li")!, { dataTransfer });
    fireEvent.drop(screen.getByLabelText("Store lead steps"), { dataTransfer });
    fireEvent.drop(screen.getByLabelText("Core lead steps"), { dataTransfer });
    expect(edits).toEqual([
      { seat: "Core lead", may_release: true },
      { seat: "Core lead", move_step: "Add the meter", to_seat: "Store lead" },
    ]);
  });

  it("shows its lane overlaps", () => {
    render(
      <SeatEditor
        seat={seat}
        models={models}
        onEdit={() => {}}
        overlaps={[{ seat: "Plugin core", other: "Core lead", path: "src/core/x.ts" }]}
      />,
    );
    expect(screen.getByRole("alert").textContent).toBe("Core lead ⚠ lane overlaps Plugin core: src/core/x.ts");
  });

  it("parses lane text", () => {
    expect(parseLane(" a/**,\nb.ts , ")).toEqual(["a/**", "b.ts"]);
  });
});
