// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AskUserForm } from "./AskUserForm";
import { parseAskUserQuestions } from "./types";

afterEach(cleanup);

const questions = parseAskUserQuestions([
  { id: "a", prompt: "Which map?", options: [{ id: "x", label: "Desert" }, { id: "y", label: "Snow" }] },
  { id: "b", prompt: "How many players?", options: [{ id: "4", label: "Four" }] },
]);

it("shows a header bar, the question count and a checklist, then submits every answer", () => {
  const done = vi.fn();
  render(<AskUserForm questions={questions} title="" captureKeys={false} onComplete={done} />);
  expect(screen.getByText("Question")).toBeTruthy();
  expect(screen.getByLabelText("Question 1 of 2")).toBeTruthy();
  expect(screen.getByText("Agent paused")).toBeTruthy();
  // Nothing picked yet: Next waits.
  expect((screen.getByRole("button", { name: /Next/ }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("radio", { name: /Snow/ }));
  fireEvent.click(screen.getByRole("button", { name: /Next/ }));
  // The checklist marks the first answer and shows what was picked.
  expect(screen.getByText("Snow", { selector: ".ask-user-batch-status" })).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", { name: /Four/ }));
  fireEvent.click(screen.getByRole("button", { name: /Submit/ }));
  expect(done).toHaveBeenCalledOnce();
  expect(done.mock.calls[0][0].answers).toMatchObject({ a: { selected: ["y"] }, b: { selected: ["4"] } });
});

it("names the asking ducky instead of Question, and hides Back for one question", () => {
  render(
    <AskUserForm
      questions={questions.slice(0, 1)}
      title=""
      captureKeys={false}
      author={{ name: "Verse Coder", color: "" } as never}
      onComplete={() => {}}
    />,
  );
  expect(screen.getByText("Verse Coder")).toBeTruthy();
  expect(screen.queryByText("Question")).toBeNull();
  expect(screen.queryByRole("button", { name: /Back/ })).toBeNull();
});
