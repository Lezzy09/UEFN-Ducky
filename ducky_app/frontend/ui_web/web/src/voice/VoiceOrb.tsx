import { useEffect, useRef, useState, type CSSProperties } from "react";

import { ttsEngine } from "./ttsEngine";

export type VoiceOrbStatus = "listening" | "thinking" | "speaking" | "muted" | "error";

export type VoiceOrbProps = {
  status: VoiceOrbStatus;
  /** Mic stream to read the level from while listening; without it the orb idles gently. */
  stream?: MediaStream | null;
  /** Fixed level 0..1 (overrides the stream; handy for tests and previews). */
  level?: number;
  /** Force reduced motion on or off; default follows `prefers-reduced-motion`. */
  reducedMotion?: boolean;
  size?: "large" | "small";
};

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

function readReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(REDUCED_QUERY).matches;
}

/** True while the OS asks for less motion; follows changes live. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(readReducedMotion);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(REDUCED_QUERY);
    const onChange = () => setReduced(mq.matches);
    onChange();
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}

/** Mic loudness 0..1 from an AnalyserNode on `stream`; 0 when there is no stream or no Web Audio. */
function useMicLevel(stream: MediaStream | null | undefined, active: boolean): number {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!stream || !active) {
      setLevel(0);
      return;
    }
    const Ctx: typeof AudioContext | undefined =
      typeof window !== "undefined"
        ? window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        : undefined;
    if (!Ctx) return;
    let ctx: AudioContext;
    try {
      ctx = new Ctx();
    } catch {
      return;
    }
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    let raf = 0;
    let smooth = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.min(1, Math.sqrt(sum / buf.length) * 4);
      smooth = smooth * 0.7 + rms * 0.3;
      setLevel(Math.round(smooth * 100) / 100);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      source.disconnect();
      void ctx.close().catch(() => undefined);
    };
  }, [stream, active]);
  return level;
}

/** Bumps once per spoken word (TTS char index moves) so the orb swells on each word. */
function useSpokenBeat(active: boolean): number {
  const [beat, setBeat] = useState(0);
  const lastIndex = useRef(-1);
  useEffect(() => {
    if (!active) return;
    return ttsEngine.onProgress((p) => {
      if (p.charIndex === lastIndex.current) return;
      lastIndex.current = p.charIndex;
      setBeat((b) => (b + 1) % 1000);
    });
  }, [active]);
  return beat;
}

/**
 * Live-voice orb: ripples with the mic level while listening, pulses (and swells per word)
 * while speaking, breathes slowly while thinking. Colors come from Appearance vars only.
 */
export function VoiceOrb({ status, stream, level, reducedMotion, size = "large" }: VoiceOrbProps) {
  const prefersReduced = usePrefersReducedMotion();
  const still = reducedMotion ?? prefersReduced;
  const micLevel = useMicLevel(stream, status === "listening" && !still && level === undefined);
  const beat = useSpokenBeat(status === "speaking" && !still);
  const live = level ?? micLevel;
  const reactive = status === "listening" && (level !== undefined || Boolean(stream));
  const style = { "--orb-level": still ? 0 : live } as CSSProperties;

  return (
    <div
      className={`voice-orb voice-orb--${status} voice-orb--${size}${still ? " voice-orb--still" : ""}${
        reactive ? " voice-orb--reactive" : ""
      }`}
      data-animated={still ? "false" : "true"}
      style={style}
      aria-hidden
    >
      <span className="voice-orb-ring voice-orb-ring--outer" />
      <span className="voice-orb-ring voice-orb-ring--inner" />
      <span key={status === "speaking" ? beat : 0} className="voice-orb-core" />
    </div>
  );
}
