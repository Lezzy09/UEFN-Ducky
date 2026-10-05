// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ComposerAttachmentChips } from "./ComposerAttachmentChips";

afterEach(cleanup);

describe("video chips", () => {
  it("shows progress while preparing and a retry button on error", () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <ComposerAttachmentChips
        attachments={[{ id: "v1", kind: "video", name: "bug.mp4", mime: "video/mp4", sizeBytes: 5_000_000, status: "preparing", progress: 0.42 }]}
        onRemove={() => {}}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText("Preparing… 42%")).toBeTruthy();
    rerender(
      <ComposerAttachmentChips
        attachments={[{ id: "v1", kind: "video", name: "bug.mp4", mime: "video/mp4", sizeBytes: 5_000_000, status: "error", error: "offline" }]}
        onRemove={() => {}}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByTitle("offline")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry bug.mp4" }));
    expect(onRetry).toHaveBeenCalledWith("v1");
  });
});
