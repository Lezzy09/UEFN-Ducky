// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SearchHit } from "../../types/panel";

const searchQuery = vi.fn();
vi.mock("../../hooks/usePanelApi", () => ({ getApi: () => ({ search_query: searchQuery }) }));

const { SkillSearchHits, useSkillSearch } = await import("./SkillSearchHits");

const HIT: SearchHit = {
  kind: "section",
  title: "Night sky",
  where: "Materials > Starfield > Night sky",
  snippet: "The starfield recipe builds twinkling stars.",
  score: 0.03,
  pack: "materials",
  subskill: "starfield_recipe",
  section: "Night sky",
  read: 'skill_read_subskill("materials", "starfield_recipe", section="Night sky")',
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("SkillSearchHits", () => {
  it("renders hits and opens the clicked one", () => {
    const onOpen = vi.fn();
    render(<SkillSearchHits hits={[HIT]} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /Night sky/ }));
    expect(onOpen).toHaveBeenCalledWith(HIT);
    expect(screen.getByText("Materials > Starfield > Night sky")).toBeTruthy();
  });

  it("renders nothing without hits", () => {
    const { container } = render(<SkillSearchHits hits={[]} onOpen={() => {}} />);
    expect(container.innerHTML).toBe("");
  });

  it("asks the index once per pause and ignores short queries", async () => {
    vi.useFakeTimers();
    searchQuery.mockResolvedValue({ ok: true, results: [HIT] });
    const { result, rerender } = renderHook(({ q }) => useSkillSearch(q), { initialProps: { q: "ni" } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(searchQuery).not.toHaveBeenCalled();
    rerender({ q: "night" });
    rerender({ q: "night sky" });
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(searchQuery).toHaveBeenCalledTimes(1);
    expect(searchQuery).toHaveBeenCalledWith("night sky", "skills", 8);
    expect(result.current).toEqual([HIT]);
  });
});
