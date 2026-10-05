// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./usePanelApi", () => ({
  getApi: vi.fn(),
}));

import { getApi } from "./usePanelApi";
import { composerAttachmentsFromDto, useComposerAttachments } from "./useComposerAttachments";
import type { MessageAttachmentDto } from "../types/panel";

beforeEach(() => {
  vi.mocked(getApi).mockReturnValue(undefined as never);
});
afterEach(cleanup);

describe("restoring queued attachments", () => {
  it("round-trips images, capture paths and file text while preserving draft attachments", () => {
    const { result } = renderHook(() => useComposerAttachments());
    const draft: MessageAttachmentDto = {
      kind: "file", name: "draft.txt", mime: "text/plain", text: "existing draft",
    };
    const queued: MessageAttachmentDto[] = [
      {
        kind: "image", name: "capture.png", mime: "image/png",
        data_base64: "aW1hZ2U=", project_path: "Saved/DuckyCaptures/capture.png",
      },
      { kind: "file", name: "notes.txt", mime: "text/plain", text: "queued\nnotes" },
    ];
    act(() => result.current.restoreAttachments([draft]));
    act(() => result.current.restoreAttachments(queued));
    expect(result.current.hasImages).toBe(true);
    expect(result.current.toApiAttachments()).toEqual([...queued, draft]);
    expect(new Set(result.current.attachments.map((a) => a.id)).size).toBe(3);
    act(() => result.current.removeAttachment(result.current.attachments[0].id));
    expect(result.current.toApiAttachments()).toEqual([queued[1], draft]);
  });

  it("restores an image-only prompt and allows clearing it after resend", () => {
    const { result } = renderHook(() => useComposerAttachments());
    act(() => result.current.restoreAttachments([
      { kind: "image", name: "shot.png", data_base64: "eA==" },
    ]));
    expect(result.current.toApiAttachments()).toEqual([
      { kind: "image", name: "shot.png", mime: "image/png", data_base64: "eA==" },
    ]);
    act(() => result.current.clearAttachments());
    expect(result.current.attachments).toEqual([]);
  });

  it("seeds from initial DTOs and replaceAttachments overwrites instead of appending", () => {
    const seeded: MessageAttachmentDto[] = [
      { kind: "file", name: "draft.txt", mime: "text/plain", text: "cached draft" },
      {
        kind: "image", name: "card.png", mime: "image/png",
        data_base64: "aW1hZ2U=", project_path: "Saved/DuckyCaptures/card.png",
      },
    ];
    const { result } = renderHook(() => useComposerAttachments(seeded));
    expect(result.current.toApiAttachments()).toEqual(seeded);

    const next: MessageAttachmentDto[] = [
      { kind: "file", name: "other.txt", mime: "text/plain", text: "switched chat" },
    ];
    act(() => result.current.replaceAttachments(next));
    expect(result.current.toApiAttachments()).toEqual(next);
    expect(result.current.attachments).toHaveLength(1);
  });
});

describe("video attachments", () => {
  afterEach(() => vi.useRealTimers());

  function mockApi(api: Record<string, unknown>) {
    vi.mocked(getApi).mockReturnValue(api as never);
  }

  it("stages a video once and sends only its id", async () => {
    const stage = vi.fn().mockResolvedValue({
      ok: true, staged_id: "a".repeat(32) + ".mp4", size_bytes: 3, mime: "video/mp4",
      needs_ffmpeg: false, ffmpeg: { state: "missing", progress: 0, error: "", version: "v" },
    });
    mockApi({ stage_video_attachment: stage, get_video_settings: vi.fn().mockResolvedValue({ video_max_mb: 100, video_frames_per_video: 20, max_images_per_message: 40 }) });
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    const file = new File([new Uint8Array([1, 2, 3])], "bug.mp4", { type: "video/mp4" });
    await act(async () => { await result.current.addFiles([file]); });
    await vi.waitFor(() => expect(result.current.hasPendingVideos).toBe(false));
    expect(stage).toHaveBeenCalledWith("c1", "bug.mp4", "video/mp4", "AQID");
    expect(result.current.toApiAttachments()).toEqual([
      { kind: "video", name: "bug.mp4", mime: "video/mp4", staged_id: "a".repeat(32) + ".mp4", size_bytes: 3 },
    ]);
  });

  it("rejects a video over the size limit before reading it", async () => {
    const stage = vi.fn();
    const settings = vi.fn().mockResolvedValue({ video_max_mb: 10, video_frames_per_video: 20, max_images_per_message: 40 });
    mockApi({ stage_video_attachment: stage, get_video_settings: settings });
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await vi.waitFor(() => expect(settings).toHaveBeenCalled());
    await act(async () => {});
    const big = new File([new Uint8Array(11 * 1024 * 1024)], "big.mp4", { type: "video/mp4" });
    await act(async () => { await result.current.addFiles([big]); });
    expect(stage).not.toHaveBeenCalled();
    expect(result.current.error).toBe("big.mp4 exceeds the 10MB video limit.");
  });

  it("stays pending while ffmpeg installs, then becomes ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const status = vi.fn()
      .mockResolvedValueOnce({ state: "installing", progress: 0.5, error: "", version: "v" })
      .mockResolvedValue({ state: "ready", progress: 1, error: "", version: "v" });
    mockApi({
      stage_video_attachment: vi.fn().mockResolvedValue({
        ok: true, staged_id: "b".repeat(32) + ".mp4", size_bytes: 1, mime: "video/mp4",
        needs_ffmpeg: true, ffmpeg: { state: "installing", progress: 0, error: "", version: "v" },
      }),
      get_ffmpeg_status: status,
      get_video_settings: vi.fn().mockResolvedValue({ video_max_mb: 100, video_frames_per_video: 20, max_images_per_message: 40 }),
    });
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await act(async () => { await result.current.addFiles([new File([new Uint8Array([1])], "x.mp4", { type: "video/mp4" })]); });
    await vi.waitFor(() => expect(result.current.attachments[0]).toMatchObject({ status: "preparing" }));
    expect(result.current.hasPendingVideos).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    await vi.waitFor(() => expect(result.current.hasPendingVideos).toBe(false));
  });

  it("restores a queued video from its DTO", () => {
    const { result } = renderHook(() => useComposerAttachments());
    const dto: MessageAttachmentDto = { kind: "video", name: "q.mp4", mime: "video/mp4", staged_id: "c".repeat(32) + ".mp4", size_bytes: 9 };
    act(() => result.current.restoreAttachments([dto]));
    expect(result.current.hasPendingVideos).toBe(false);
    expect(result.current.toApiAttachments()).toEqual([dto]);
  });
});

describe("video preview release", () => {
  let counter = 0;
  let revoke: ReturnType<typeof vi.fn>;
  const origCreate = URL.createObjectURL;
  const origRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    counter = 0;
    revoke = vi.fn();
    URL.createObjectURL = (() => `blob:x-${++counter}`) as never;
    URL.revokeObjectURL = revoke as never;
    vi.mocked(getApi).mockReturnValue({
      stage_video_attachment: vi.fn().mockResolvedValue({ ok: true, staged_id: "s.mp4", size_bytes: 1, needs_ffmpeg: false }),
    } as never);
  });
  afterEach(() => {
    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
  });

  const vid = (n: string) => new File([new Uint8Array([1])], n, { type: "video/mp4" });

  it("revokes the blob URL on clearAttachments", async () => {
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await act(async () => { await result.current.addFiles([vid("a.mp4")]); });
    act(() => result.current.clearAttachments());
    expect(revoke).toHaveBeenCalledWith("blob:x-1");
  });

  it("revokes on replaceAttachments", async () => {
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await act(async () => { await result.current.addFiles([vid("a.mp4")]); });
    act(() => result.current.replaceAttachments([]));
    expect(revoke).toHaveBeenCalledWith("blob:x-1");
  });

  it("revokes remaining previews on unmount", async () => {
    const { result, unmount } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await act(async () => { await result.current.addFiles([vid("a.mp4")]); });
    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:x-1");
  });

  it("removing one of two videos revokes only that one", async () => {
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await act(async () => { await result.current.addFiles([vid("a.mp4"), vid("b.mp4")]); });
    act(() => result.current.removeAttachment(result.current.attachments[1].id));
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:x-2");
  });
});

describe("composerAttachmentsFromDto videos", () => {
  it("marks a video with neither staged_id nor abs_path as an error", () => {
    const [a] = composerAttachmentsFromDto([{ kind: "video", name: "a.mp4", mime: "video/mp4" }]);
    expect(a).toMatchObject({
      kind: "video",
      status: "error",
      error: "Upload interrupted — attach the video again.",
    });
  });

  it("keeps a staged video ready", () => {
    const [a] = composerAttachmentsFromDto([
      { kind: "video", name: "a.mp4", mime: "video/mp4", staged_id: "x.mp4" },
    ]);
    expect(a).toMatchObject({ status: "ready", stagedId: "x.mp4" });
  });
});
