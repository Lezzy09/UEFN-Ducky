// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const listGenerated = vi.fn();
vi.mock("../hooks/usePanelApi", () => ({
  getApi: () => ({ list_generated_images: listGenerated }),
}));

const { AttachMenuButton } = await import("./AttachMenuButton");

afterEach(() => {
  cleanup();
  listGenerated.mockClear();
  vi.unstubAllGlobals();
});

describe("AttachMenuButton", () => {
  it("uploads a file and does not list generated images", () => {
    const onAddFiles = vi.fn();
    render(<AttachMenuButton onAddFiles={onAddFiles} />);
    fireEvent.click(screen.getByTitle("Attach a picture or file"));
    fireEvent.click(screen.getByRole("button", { name: "Upload image or file" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["hello"], "note.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onAddFiles).toHaveBeenCalledWith([file]);
    expect(listGenerated).not.toHaveBeenCalled();
  });

  it("opens the camera for take picture", async () => {
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop() {} }],
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    render(<AttachMenuButton onAddFiles={() => {}} />);
    fireEvent.click(screen.getByTitle("Attach a picture or file"));
    fireEvent.click(screen.getByRole("button", { name: "Take picture" }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    expect(listGenerated).not.toHaveBeenCalled();
  });
});
