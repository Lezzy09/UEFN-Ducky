/**
 * Microphone recording for plugin panels (bridge `audio.recordStart` / `audio.recordStop`).
 *
 * Plugin iframes are sandboxed without microphone access; the host window already has it
 * (voice dictation), so it records on the panel's behalf and hands back the finished take.
 */

interface Take {
  pluginId: string;
  recorder: MediaRecorder;
  stream: MediaStream;
  parts: Blob[];
  started: number;
  stopped: Promise<void>;
}

const takes = new Map<string, Take>();
const MAX_SECONDS = 600;

function preferredMime(): string {
  const options = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const mime of options) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(mime)) return mime;
  }
  return "";
}

function release(take: Take) {
  for (const track of take.stream.getTracks()) track.stop();
}

export async function startRecording(pluginId: string): Promise<{ id: string }> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("This device has no microphone access.");
  for (const [id, take] of takes) {
    if (take.pluginId === pluginId) {
      try {
        take.recorder.stop();
      } catch {
        /* already stopped */
      }
      release(take);
      takes.delete(id);
    }
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = preferredMime();
  const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
  const parts: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size) parts.push(event.data);
  };
  const stopped = new Promise<void>((resolve) => {
    recorder.onstop = () => resolve();
  });
  const id = `rec-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const take: Take = { pluginId, recorder, stream, parts, started: performance.now(), stopped };
  takes.set(id, take);
  recorder.start(250);
  setTimeout(() => {
    if (takes.get(id) === take && recorder.state === "recording") recorder.stop();
  }, MAX_SECONDS * 1000);
  return { id };
}

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(binary);
}

export async function stopRecording(
  pluginId: string,
  id: string,
): Promise<{ b64: string; mime: string; seconds: number; bytes: number }> {
  const take = takes.get(id);
  if (!take || take.pluginId !== pluginId) throw new Error("That recording is not running.");
  if (take.recorder.state !== "inactive") take.recorder.stop();
  await take.stopped;
  release(take);
  takes.delete(id);
  const blob = new Blob(take.parts, { type: take.recorder.mimeType || "audio/webm" });
  if (!blob.size) throw new Error("Nothing was recorded. Check the microphone.");
  return {
    b64: await blobToBase64(blob),
    mime: (blob.type || "audio/webm").split(";")[0],
    seconds: Math.round((performance.now() - take.started) / 100) / 10,
    bytes: blob.size,
  };
}

export function cancelRecording(pluginId: string, id: string): { ok: boolean } {
  const take = takes.get(id);
  if (!take || take.pluginId !== pluginId) return { ok: false };
  try {
    take.recorder.stop();
  } catch {
    /* already stopped */
  }
  release(take);
  takes.delete(id);
  return { ok: true };
}
