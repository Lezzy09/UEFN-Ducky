// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PromptQueueBar } from "./PromptQueueBar";
import { makeQueuedPrompt } from "../hooks/promptQueue";

afterEach(cleanup);

describe("PromptQueueBar", () => {
  it("hands Edit to the composer immediately without opening an inline editor or sending", () => {
    const onEdit = vi.fn();
    const onSendNow = vi.fn();
    const onDelete = vi.fn();
    render(<PromptQueueBar
      items={[makeQueuedPrompt("revise me", { id: "q1", mode: "agent", model: "m" })!]}
      onEdit={onEdit} onSendNow={onSendNow} onDelete={onDelete}
    />);

    fireEvent.click(screen.getByRole("button", { name: "Edit queued prompt" }));
    expect(onEdit).toHaveBeenCalledExactlyOnceWith("q1");
    expect(onSendNow).not.toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("says what Send now does: next step for text, stops the turn for files", () => {
    const pic = { kind: "image" as const, name: "shot.png", data_base64: "AA==" };
    render(<PromptQueueBar
      items={[
        makeQueuedPrompt("just text", { id: "t", mode: "agent", model: "m" })!,
        makeQueuedPrompt("with a picture", { id: "p", mode: "agent", model: "m", attachments: [pic] })!,
      ]}
      onEdit={vi.fn()} onSendNow={vi.fn()} onDelete={vi.fn()}
    />);
    const [text, files] = screen.getAllByRole("button", { name: "Send queued prompt now" });
    expect(text.getAttribute("title")).toBe("Send now (the agent reads it at its next step)");
    expect(files.getAttribute("title")).toBe("Send now (stops current turn)");
  });
});
