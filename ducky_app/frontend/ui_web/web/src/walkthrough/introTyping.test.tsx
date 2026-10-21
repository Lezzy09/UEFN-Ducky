// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { _resetIntroForTests, armIntro, INTRO_WORD_MS, nextIntroLength, useIntroTyping, whenIntroDone } from "./introTyping";

const TEXT = "Hi there, ducky.";

function Bubble({ offers = true }: { offers?: boolean }) {
  const shown = useIntroTyping(TEXT, offers);
  return <p data-testid="b">{shown ?? TEXT}</p>;
}

beforeEach(() => {
  _resetIntroForTests();
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the welcome intro", () => {
  it("steps through the text a word at a time", () => {
    expect(nextIntroLength(TEXT, 0)).toBe(2);
    expect(nextIntroLength(TEXT, 2)).toBe(9);
    expect(nextIntroLength(TEXT, 9)).toBe(TEXT.length);
    expect(nextIntroLength(TEXT, TEXT.length)).toBe(TEXT.length);
  });

  it("types itself out once when armed, then the flow goes on", async () => {
    armIntro();
    const done = vi.fn();
    void whenIntroDone().then(done);
    render(<Bubble />);
    expect(screen.getByTestId("b").textContent).toBe(""); // never a flash of the whole text
    act(() => {
      vi.advanceTimersByTime(INTRO_WORD_MS);
    });
    expect(screen.getByTestId("b").textContent).toBe("Hi");
    for (let i = 0; i < 4; i++) {
      await act(async () => {
        vi.advanceTimersByTime(INTRO_WORD_MS);
      });
    }
    expect(screen.getByTestId("b").textContent).toBe(TEXT);
    expect(done).toHaveBeenCalledOnce();

    cleanup();
    render(<Bubble />); // reopening the chat later shows it whole
    expect(screen.getByTestId("b").textContent).toBe(TEXT);
  });

  it("shows other messages whole, and never holds the flow when nothing types", async () => {
    armIntro();
    render(<Bubble offers={false} />);
    expect(screen.getByTestId("b").textContent).toBe(TEXT);
    const done = vi.fn();
    void whenIntroDone(1000).then(done);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(done).toHaveBeenCalledOnce();
  });
});
