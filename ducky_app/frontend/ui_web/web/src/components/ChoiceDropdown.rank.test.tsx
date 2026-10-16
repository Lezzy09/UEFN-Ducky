// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChoiceDropdown, type ChoiceOption } from "./ChoiceDropdown";

const OPTIONS: ChoiceOption[] = [
  { value: "photoshop_save_document", label: "photoshop_save_document", group: "Adobe" },
  { value: "save_current_level", label: "save_current_level", group: "Scene" },
  { value: "spawn_actor", label: "spawn_actor", group: "Scene" },
];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ChoiceDropdown rankSearch", () => {
  it("puts ranked values first, then plain word matches", async () => {
    vi.useFakeTimers();
    const rank = vi.fn().mockResolvedValue(["spawn_actor"]);
    render(
      <ChoiceDropdown aria-label="Tool" value="" options={OPTIONS} onChange={() => {}} searchable rankSearch={rank} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Tool/ }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "save" } });
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(rank).toHaveBeenCalledWith("save");
    const labels = screen.getAllByRole("radio").map((el) => el.closest("label")?.textContent || "");
    expect(labels[0]).toContain("spawn_actor");
    expect(labels.slice(1).join(" ")).toContain("save_current_level");
  });

  it("filters by words alone when ranking finds nothing", async () => {
    vi.useFakeTimers();
    const rank = vi.fn().mockResolvedValue([]);
    render(
      <ChoiceDropdown aria-label="Tool" value="" options={OPTIONS} onChange={() => {}} searchable rankSearch={rank} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Tool/ }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "spawn" } });
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(screen.getAllByRole("radio")).toHaveLength(1);
  });
});
