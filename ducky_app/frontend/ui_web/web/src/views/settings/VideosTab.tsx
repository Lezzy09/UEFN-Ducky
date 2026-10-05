/**
 * Settings → Videos — video attachment limits and the on-demand ffmpeg install.
 */

import { useCallback, useEffect, useState } from "react";
import { getApi } from "../../hooks/usePanelApi";
import type { FfmpegStatusDto, VideoSettingsDto } from "../../types/panel";
import { Icons } from "../../icons/Icons";
import { GeneralSectionHeader } from "./GeneralSectionHeader";

type NumericKey = "video_max_mb" | "video_frames_per_video" | "max_images_per_message";

const FIELDS: { key: NumericKey; label: string; min: number; max: number; hint: string }[] = [
  { key: "video_max_mb", label: "Max video size (MB)", min: 10, max: 200, hint: "Largest video one message can carry." },
  { key: "video_frames_per_video", label: "Frames per video", min: 1, max: 40, hint: "Frames sent to models without native video (Claude, OpenAI, coding agents…)." },
  { key: "max_images_per_message", label: "Max images per message", min: 1, max: 100, hint: "Images per message, video frames included." },
];

function ffmpegLabel(st: FfmpegStatusDto): string {
  if (st.state === "ready") return `Installed (${st.version})`;
  if (st.state === "installing") return `Installing… ${Math.round(st.progress * 100)}%`;
  if (st.state === "error") return st.error || "Install failed";
  return "Not installed";
}

export function VideosTab() {
  const [settings, setSettings] = useState<VideoSettingsDto | null>(null);
  const [draft, setDraft] = useState<Record<NumericKey, string>>({
    video_max_mb: "", video_frames_per_video: "", max_images_per_message: "",
  });

  const apply = useCallback((s: VideoSettingsDto) => {
    setSettings(s);
    setDraft({
      video_max_mb: String(s.video_max_mb),
      video_frames_per_video: String(s.video_frames_per_video),
      max_images_per_message: String(s.max_images_per_message),
    });
  }, []);

  useEffect(() => {
    void getApi()?.get_video_settings?.().then((s) => s && apply(s));
  }, [apply]);

  const installing = settings?.ffmpeg.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => {
      void getApi()?.get_ffmpeg_status?.().then((ffmpeg) => {
        if (ffmpeg) setSettings((prev) => (prev ? { ...prev, ffmpeg } : prev));
      });
    }, 500);
    return () => window.clearInterval(timer);
  }, [installing]);

  const save = useCallback(async (key: NumericKey) => {
    const value = Number(draft[key]);
    if (!Number.isFinite(value)) return;
    const next = await getApi()?.set_video_settings?.({ [key]: value });
    if (next) apply(next);
  }, [draft, apply]);

  const runFfmpeg = useCallback(async (action: "install" | "remove") => {
    const api = getApi();
    const ffmpeg = action === "install" ? await api?.install_ffmpeg?.() : await api?.remove_ffmpeg?.();
    if (ffmpeg) setSettings((prev) => (prev ? { ...prev, ffmpeg } : prev));
  }, []);

  if (!settings) return null;
  return (
    <div className="general-tab-shell videos-tab">
      <GeneralSectionHeader icon={<Icons.Play />} title="Videos" />
      {FIELDS.map((f) => (
        <label key={f.key} className="memory-tab-field">
          <span className="memory-tab-field-label">{f.label}</span>
          <input
            className="memory-tab-input"
            type="number"
            min={f.min}
            max={f.max}
            aria-label={f.label}
            value={draft[f.key]}
            onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            onBlur={() => void save(f.key)}
          />
          <span className="memory-tab-field-hint">{f.hint}</span>
        </label>
      ))}
      <div className="memory-tab-field">
        <span className="memory-tab-field-label">ffmpeg</span>
        <span>{ffmpegLabel(settings.ffmpeg)}</span>
        <span className="memory-tab-field-hint">
          Downloaded automatically (~67 MB, LGPL build) the first time a video needs frames. Gemini users with small
          videos never need it.
        </span>
        <div className="videos-tab-actions">
          {settings.ffmpeg.state !== "ready" ? (
            <button type="button" disabled={installing} onClick={() => void runFfmpeg("install")}>
              Install now
            </button>
          ) : (
            <button type="button" onClick={() => void runFfmpeg("remove")}>
              Remove
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
