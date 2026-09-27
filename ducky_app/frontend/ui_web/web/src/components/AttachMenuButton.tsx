import { useCallback, useEffect, useRef, useState } from "react";
import { useUiTarget } from "../ui-targets/registry";

interface AttachMenuButtonProps {
  disabled?: boolean;
  onAddFiles: (files: File[]) => void;
}

/** Phone back camera when the panel is on a phone; webcam on the desktop. */
export async function openCameraStream(): Promise<MediaStream> {
  const media = navigator.mediaDevices;
  if (!media?.getUserMedia) {
    throw new Error("Camera is not available on this device.");
  }
  try {
    return await media.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  } catch {
    return await media.getUserMedia({ video: true, audio: false });
  }
}

function stopStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

export function AttachMenuButton({ disabled, onAddFiles }: AttachMenuButtonProps) {
  const [open, setOpen] = useState(false);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [cameraError, setCameraError] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const uiTargetRef = useUiTarget("chat.composer.generated", {
    kind: "button",
    label: "Attach",
    route: "chat",
  });

  const close = useCallback(() => {
    setOpen(false);
    setCameraError("");
    setStream((current) => {
      stopStream(current);
      return null;
    });
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !stream) return;
    video.srcObject = stream;
    const played = video.play?.();
    if (played && typeof played.catch === "function") void played.catch(() => undefined);
  }, [stream]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, close]);

  const startCamera = async () => {
    setCameraError("");
    try {
      const next = await openCameraStream();
      setStream((current) => {
        stopStream(current);
        return next;
      });
    } catch {
      setCameraError("Camera blocked. Allow the camera, or upload a file instead.");
    }
  };

  const shutter = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      setCameraError("Camera is not ready yet.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setCameraError("Could not save that photo.");
          return;
        }
        const file = new File([blob], `photo-${Date.now()}.jpg`, { type: "image/jpeg" });
        onAddFiles([file]);
        close();
      },
      "image/jpeg",
      0.92,
    );
  };

  return (
    <div className="attach-menu-wrap" ref={wrapRef}>
      <button
        ref={uiTargetRef}
        type="button"
        className="snip-btn"
        title="Attach a picture or file"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="M21 15l-5-5L5 21" />
        </svg>
      </button>
      {open ? (
        <div className="attach-menu-flyout" role="menu">
          {cameraError ? <div className="attach-menu-error">{cameraError}</div> : null}
          {stream ? (
            <>
              <video ref={videoRef} className="attach-menu-preview" autoPlay playsInline muted />
              <button type="button" className="attach-menu-item" onClick={shutter}>
                Use photo
              </button>
            </>
          ) : (
            <>
              <button type="button" className="attach-menu-item" onClick={() => void startCamera()}>
                Take picture
              </button>
              <button type="button" className="attach-menu-item" onClick={() => fileRef.current?.click()}>
                Upload image or file
              </button>
            </>
          )}
        </div>
      ) : null}
      <input
        ref={fileRef}
        className="attach-menu-file"
        type="file"
        multiple
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = "";
          if (files.length === 0) return;
          onAddFiles(files);
          close();
        }}
      />
    </div>
  );
}
