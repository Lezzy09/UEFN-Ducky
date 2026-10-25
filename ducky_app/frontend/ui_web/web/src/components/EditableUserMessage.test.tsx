// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { EditableUserMessage } from "./EditableUserMessage";
import type { MessageAttachmentDto } from "../types/panel";

vi.mock("./ModeSelector", () => ({ ModeSelector: () => null }));
vi.mock("./ModelSelector", () => ({ ModelSelector: () => null }));

afterEach(cleanup);

const files: MessageAttachmentDto[] = [
  { kind: "file", name: "keep.txt", mime: "text/plain" } as MessageAttachmentDto,
  { kind: "file", name: "drop.txt", mime: "text/plain" } as MessageAttachmentDto,
];

it("Restart from here calls back without opening the editor", () => {
  const onRestart = vi.fn();
  render(<EditableUserMessage text="Old ask" currentMode="agent" currentModel="m" onResend={vi.fn()} onRestart={onRestart} />);
  fireEvent.click(screen.getByRole("button", { name: "Restart from here" }));
  expect(onRestart).toHaveBeenCalledTimes(1);
  expect(screen.queryByPlaceholderText(/Edit and resend/)).toBeNull();
});

it("an attachment removed while editing is left out of the resend", () => {
  const onResend = vi.fn();
  render(<EditableUserMessage text="Fix it" attachments={files} editable currentMode="agent" currentModel="m" onResend={onResend} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit and resend" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove drop.txt" }));
  expect(screen.queryByRole("button", { name: "Remove drop.txt" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Resend" }));
  expect(onResend).toHaveBeenCalledWith("Fix it", "agent", "m", [files[0]]);
});
