// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getApi } from "../../hooks/usePanelApi";
import { VideosTab } from "./VideosTab";

vi.mock("../../hooks/usePanelApi", () => ({ getApi: vi.fn() }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const settings = {
  video_max_mb: 100, video_frames_per_video: 20, max_images_per_message: 40,
  ffmpeg: { state: "missing", progress: 0, error: "", version: "n9.0.1" },
};

describe("VideosTab", () => {
  it("loads, saves a clamped value and installs ffmpeg", async () => {
    const set = vi.fn().mockResolvedValue({ ...settings, video_frames_per_video: 40 });
    const install = vi.fn().mockResolvedValue({ ...settings.ffmpeg, state: "installing" });
    vi.mocked(getApi).mockReturnValue({
      get_video_settings: vi.fn().mockResolvedValue(settings),
      set_video_settings: set,
      install_ffmpeg: install,
      get_ffmpeg_status: vi.fn().mockResolvedValue(settings.ffmpeg),
    } as never);
    render(<VideosTab />);
    const frames = await screen.findByLabelText("Frames per video");
    fireEvent.change(frames, { target: { value: "99" } });
    fireEvent.blur(frames);
    await waitFor(() => expect(set).toHaveBeenCalledWith({ video_frames_per_video: 99 }));
    expect((frames as HTMLInputElement).value).toBe("40");
    expect(screen.getByText("Not installed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Install now" }));
    await waitFor(() => expect(install).toHaveBeenCalled());
  });
});
