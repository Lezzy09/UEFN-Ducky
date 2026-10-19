/**
 * Settings → Videos — video attachment limits and the on-demand ffmpeg install.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getApi } from "../../hooks/usePanelApi";
import type { FfmpegStatusDto, VideoSettingsDto } from "../../types/panel";
import { AppNotice } from "../../components/AppNotice";
import { Icons } from "../../icons/Icons";
import { GeneralSectionHeader } from "./GeneralSectionHeader";

type NumericKey = "video_max_mb" | "video_frames_per_video" | "max_images_per_message";

const FIELDS: {
  key: NumericKey;
  label: string;
  unit?: string;
  min: number;
  max: number;
  hint: string;
  auto?: number;
}[] = [
  { key: "video_max_mb", label: "Max video size", unit: "MB", min: 10, max: 200, hint: "Largest video one message can carry." },
  { key: "video_frames_per_video", label: "Frames per video", min: 1, max: 40, auto: 20, hint: "Frames sent to models without native video (Claude, OpenAI, coding agents…)." },
  { key: "max_images_per_message", label: "Max images per message", min: 1, max: 100, auto: 40, hint: "Images per message, video frames included." },
];

function ffmpegLabel(st: FfmpegStatusDto): string {
  if (st.state === "ready" && st.bundled) return `Included with UEFN-Ducky (${st.version})`;
  if (st.state === "ready") return `Installed (${st.version})`;
  if (st.state === "installing") return `Installing… ${Math.round(st.progress * 100)}%`;
  if (st.state === "error") return st.error || "Install failed";
  return "Not installed";
}

function ffmpegTone(st: FfmpegStatusDto): string {
  if (st.state === "ready") return " general-tab-badge--installed";
  if (st.state === "error") return " videos-tab-badge--error";
  if (st.state === "installing") return "";
  return " videos-tab-badge--muted";
}

function errMsg(prefix: string, err: unknown): string {
  return `${prefix}: ${err instanceof Error ? err.message : String(err)}`;
}

export function VideosTab() {
  const [settings, setSettings] = useState<VideoSettingsDto | null>(null);
  const [draft, setDraft] = useState<Record<NumericKey, string>>({
    video_max_mb: "", video_frames_per_video: "", max_images_per_message: "",
  });

  const [error, setError] = useState("");
  const pollInFlight = useRef(false);

  const apply = useCallback((s: VideoSettingsDto) => {
    setSettings(s);
    setDraft({
      video_max_mb: String(s.video_max_mb),
      video_frames_per_video: String(s.video_frames_per_video),
      max_images_per_message: String(s.max_images_per_message),
    });
  }, []);

  const load = useCallback(async () => {
    try {
      const s = await getApi()?.get_video_settings?.();
      if (s) {
        apply(s);
        setError("");
      }
    } catch (err) {
      setError(errMsg("Failed to load video settings", err));
    }
  }, [apply]);

  useEffect(() => {
    void load();
  }, [load]);

  const installing = settings?.ffmpeg.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => {
      if (pollInFlight.current) return;
      pollInFlight.current = true;
      void (async () => {
        try {
          const ffmpeg = await getApi()?.get_ffmpeg_status?.();
          if (ffmpeg) setSettings((prev) => (prev ? { ...prev, ffmpeg } : prev));
        } catch (err) {
          setError(errMsg("Failed to read ffmpeg status", err));
        } finally {
          pollInFlight.current = false;
        }
      })();
    }, 500);
    return () => window.clearInterval(timer);
  }, [installing]);

  const save = useCallback(async (key: NumericKey) => {
    if (!settings) return;
    const raw = draft[key].trim();
    const rawValue = Number(raw);
    if (raw === "" || !Number.isFinite(rawValue)) {
      setDraft((d) => ({ ...d, [key]: String(settings[key]) }));
      return;
    }
    const field = FIELDS.find((f) => f.key === key);
    const value = field ? Math.max(field.min, rawValue) : rawValue;
    if (value === settings[key]) return;
    try {
      const next = await getApi()?.set_video_settings?.({ [key]: value });
      if (next) {
        apply(next);
        setError("");
      }
    } catch (err) {
      setError(errMsg("Failed to save video settings", err));
    }
  }, [draft, settings, apply]);

  const lastManual = useRef<Partial<Record<NumericKey, number>>>({});

  const toggleAuto = useCallback(async (key: NumericKey, defaultManual: number, on: boolean) => {
    if (!settings) return;
    if (on) {
      if (settings[key] > 0) lastManual.current[key] = settings[key];
    }
    const value = on ? 0 : lastManual.current[key] ?? defaultManual;
    try {
      const next = await getApi()?.set_video_settings?.({ [key]: value });
      if (next) {
        apply(next);
        setError("");
      }
    } catch (err) {
      setError(errMsg("Failed to save video settings", err));
    }
  }, [settings, apply]);

  const runFfmpeg = useCallback(async (action: "install" | "remove") => {
    try {
      const api = getApi();
      const ffmpeg = action === "install" ? await api?.install_ffmpeg?.() : await api?.remove_ffmpeg?.();
      if (ffmpeg) setSettings((prev) => (prev ? { ...prev, ffmpeg } : prev));
      setError("");
    } catch (err) {
      setError(errMsg(`Failed to ${action} ffmpeg`, err));
    }
  }, []);

  if (!settings) {
    return error ? (
      <div className="general-tab-shell videos-tab">
        <AppNotice message={error} className="plans-tab-notice" />
        <div className="general-tab-btn-row">
          <button type="button" className="settings-btn" onClick={() => void load()}>
            Retry
          </button>
        </div>
      </div>
    ) : null;
  }

  const ffmpeg = settings.ffmpeg;
  return (
    <div className="general-tab-shell videos-tab">
      {error ? <AppNotice message={error} className="plans-tab-notice" /> : null}
      <h2 className="general-tab-page-title">Videos</h2>

      <section className="general-tab-section">
        <GeneralSectionHeader
          icon={<Icons.Sliders />}
          title="Limits"
          description="How much video, and how many pictures, one message can carry."
        />
        <div className="general-tab-toggle-card">
          {FIELDS.map((f) => {
            const id = `videos-${f.key}`;
            const auto = f.auto !== undefined && settings[f.key] === 0;
            return (
              <div key={f.key} className="general-tab-toggle-row videos-tab-row">
                <div className="general-tab-toggle-row-text">
                  <label htmlFor={id} className="general-tab-toggle-label">
                    {f.label}
                  </label>
                  <p className="general-tab-toggle-desc">{f.hint}</p>
                </div>
                <div className="videos-tab-control">
                  {f.auto !== undefined ? (
                    <label className="videos-tab-auto">
                      <span>Auto</span>
                      <span className="general-tab-switch general-tab-switch--compact">
                        <input
                          type="checkbox"
                          className="general-tab-switch-input"
                          aria-label={`${f.label} Auto`}
                          checked={auto}
                          onChange={(e) => void toggleAuto(f.key, f.auto as number, e.target.checked)}
                        />
                        <span className="general-tab-switch-track" aria-hidden />
                      </span>
                    </label>
                  ) : null}
                  <span className={`videos-tab-number${auto ? " is-auto" : ""}`}>
                    <input
                      id={id}
                      className="settings-input videos-tab-input"
                      type="number"
                      min={f.min}
                      max={f.max}
                      aria-label={f.label}
                      value={auto ? "" : draft[f.key]}
                      placeholder={auto ? "Auto" : undefined}
                      disabled={auto}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                      onBlur={() => void save(f.key)}
                    />
                    {f.unit ? <span className="videos-tab-unit">{f.unit}</span> : null}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="general-tab-section">
        <GeneralSectionHeader
          icon={<Icons.Download />}
          title="ffmpeg"
          description="Turns a video into frames for models that can't watch video."
        />
        <div className="general-tab-toggle-card">
          <div className="general-tab-toggle-row videos-tab-row">
            <div className="general-tab-toggle-row-text">
              <span className={`general-tab-badge videos-tab-badge${ffmpegTone(ffmpeg)}`}>{ffmpegLabel(ffmpeg)}</span>
              {ffmpeg.bundled ? null : (
                <p className="general-tab-toggle-desc">
                  Downloaded automatically (~67 MB, LGPL build) the first time a video needs frames. Gemini users with
                  small videos never need it.
                </p>
              )}
              {installing ? (
                <progress className="videos-tab-progress" value={ffmpeg.progress} max={1} aria-label="ffmpeg download" />
              ) : null}
            </div>
            {ffmpeg.bundled ? null : ffmpeg.state !== "ready" ? (
              <button
                type="button"
                className="settings-btn general-tab-btn-primary videos-tab-action"
                disabled={installing}
                onClick={() => void runFfmpeg("install")}
              >
                Install now
              </button>
            ) : (
              <button type="button" className="settings-btn videos-tab-action" onClick={() => void runFfmpeg("remove")}>
                Remove
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
