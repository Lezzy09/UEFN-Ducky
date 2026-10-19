import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { getDirectTransport, type DirectStatus } from "../remote/directTransport";
import { ownWindow, useHtmlClass } from "../remote/ownWindow";
import { requestOpenChatTab } from "../navigation/openChatReference";
import { Icons } from "../icons/Icons";
import { useRemotePicture } from "../remote/remotePicture";
import type { ResizeEdge } from "../utils/nativeWindowChrome";

const OPEN_CHAT_TRIES = 30;
const OPEN_CHAT_EVERY_MS = 500;
const DRAG_SLOP_PX = 4;
const TOP_GRIPS: ResizeEdge[] = ["n", "nw", "ne"];

/** What the bar says for each link state. */
export function remoteDuckyLine(name: string, status: DirectStatus | null): { text: string; tone: "live" | "wait" | "off" } {
  const state = status?.state ?? "connecting";
  if (state === "live") return { text: `Talking to ${name}`, tone: "live" };
  if (state === "failed") {
    const why = status?.reason ? ` ${status.reason}` : "";
    return { text: `Can't reach ${name}.${why}`, tone: "off" };
  }
  return { text: `Connecting to ${name}…`, tone: "wait" };
}

/** Fit: the picture as large as this monitor allows, plus the bars around it (physical px). */
function fitToPicture(picture: { w: number; h: number }) {
  const screen = document.querySelector<HTMLElement>(".remote-window-screen");
  if (!screen) return;
  const dpr = window.devicePixelRatio || 1;
  const padW = Math.max(0, window.innerWidth - screen.clientWidth) * dpr;
  const padH = Math.max(0, window.innerHeight - screen.clientHeight) * dpr;
  ownWindow.chrome("fit", picture.w, picture.h, padW, padH);
}

const onButton = (target: EventTarget | null) =>
  target instanceof Element && !!target.closest("button, .remote-ducky-bar__grip");

/**
 * The title bar of a window that shows another of your UEFN Duckies: which one you're
 * talking to, whether the link is up, and this window's own buttons (the window is
 * frameless, like a focus window). Everything below it is that Ducky's own app: a chat
 * started here runs on its computer, with its tools. Full screen (F11) covers the whole
 * monitor; the bar then slides down from the top edge.
 */
export function RemoteDuckyBar({ name, chat = "" }: { name: string; chat?: string }) {
  const [status, setStatus] = useState<DirectStatus | null>(null);
  const opened = useRef(false);
  const dragFrom = useRef<{ x: number; y: number } | null>(null);
  const maximized = useHtmlClass("window-maximized");
  const fullscreen = useHtmlClass("window-fullscreen");
  const picture = useRemotePicture();
  useEffect(() => getDirectTransport()?.onStatus(setStatus), []);
  // Opened at one of that Ducky's chats (a synced copy in the sidebar): open it once the
  // link is up and the app has mounted its chat tabs.
  const live = status?.state === "live";
  useEffect(() => {
    if (!chat || !live || opened.current) return;
    let tries = 0;
    const t = window.setInterval(() => {
      tries += 1;
      if (requestOpenChatTab(chat) || tries >= OPEN_CHAT_TRIES) {
        opened.current = true;
        window.clearInterval(t);
      }
    }, OPEN_CHAT_EVERY_MS);
    return () => window.clearInterval(t);
  }, [chat, live]);

  // F11 is this window's, before a stream sends it to the PC.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "F11") return;
      ev.preventDefault();
      ev.stopPropagation();
      if (!ev.repeat) ownWindow.chrome("fullscreen", !document.documentElement.classList.contains("window-fullscreen"));
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  const onPointerDown = (ev: ReactPointerEvent<HTMLDivElement>) => {
    if (ev.button !== 0 || fullscreen || onButton(ev.target)) return;
    // A still click finishes in the page (double-click maximizes); once it moves, Windows drags.
    dragFrom.current = { x: ev.screenX, y: ev.screenY };
  };
  const onPointerMove = (ev: ReactPointerEvent<HTMLDivElement>) => {
    const from = dragFrom.current;
    if (!from) return;
    if (!(ev.buttons & 1)) {
      dragFrom.current = null;
    } else if (Math.abs(ev.screenX - from.x) >= DRAG_SLOP_PX || Math.abs(ev.screenY - from.y) >= DRAG_SLOP_PX) {
      dragFrom.current = null;
      ownWindow.move();
    }
  };

  const line = remoteDuckyLine(name, status);
  return (
    <>
      <div
        className={`remote-ducky-bar is-${line.tone}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => (dragFrom.current = null)}
        onDoubleClick={(ev) => {
          if (onButton(ev.target)) return;
          if (fullscreen) ownWindow.chrome("fullscreen", false);
          else ownWindow.chrome("maximize", !maximized);
        }}
        onContextMenu={(ev) => {
          if (onButton(ev.target) || fullscreen) return;
          if (ownWindow.menu()) ev.preventDefault();
        }}
      >
        <span className="remote-ducky-bar__status" role="status" aria-live="polite">
          <span className="remote-ducky-bar__dot" aria-hidden="true" />
          <span className="remote-ducky-bar__text">{line.text}</span>
        </span>
        {line.tone === "off" ? (
          <button type="button" className="remote-ducky-bar__retry" onClick={() => window.location.reload()}>
            Try again
          </button>
        ) : null}
        <span className="remote-ducky-bar__fill" aria-hidden="true" />
        <div className="window-controls remote-ducky-bar__controls">
          {picture && !fullscreen ? (
            <button
              type="button"
              className="window-control-btn"
              title="Fit to screen: the picture as big as this monitor allows"
              aria-label="Fit to screen"
              onClick={() => fitToPicture(picture)}
            >
              <Icons.FitView />
            </button>
          ) : null}
          <button
            type="button"
            className="window-control-btn"
            title={fullscreen ? "Exit full screen (F11)" : "Full screen (F11)"}
            aria-label={fullscreen ? "Exit full screen" : "Full screen"}
            onClick={() => ownWindow.chrome("fullscreen", !fullscreen)}
          >
            {fullscreen ? <Icons.ExitFullScreen /> : <Icons.FullScreen />}
          </button>
          {fullscreen ? null : (
            <>
              <button type="button" className="window-control-btn" title="Minimize" onClick={() => ownWindow.chrome("minimize")}>
                <Icons.Minimize />
              </button>
              <button
                type="button"
                className="window-control-btn"
                title={maximized ? "Restore" : "Maximize"}
                onClick={() => ownWindow.chrome("maximize", !maximized)}
              >
                {maximized ? <Icons.WindowRestore /> : <Icons.Maximize />}
              </button>
            </>
          )}
          <button type="button" className="window-control-btn is-close" title="Close" onClick={() => ownWindow.chrome("close")}>
            <Icons.Close />
          </button>
        </div>
        {/* The top edge has no OS frame: these grips hand off to its resize loop. */}
        {fullscreen || maximized
          ? null
          : TOP_GRIPS.map((edge) => (
              <span
                key={edge}
                className={`remote-ducky-bar__grip remote-ducky-bar__grip--${edge}`}
                aria-hidden="true"
                onMouseDown={(ev) => {
                  if (ev.button !== 0) return;
                  ev.preventDefault();
                  ev.stopPropagation();
                  ownWindow.resize(edge, ev.detail === 2);
                }}
              />
            ))}
      </div>
      {fullscreen ? <div className="remote-ducky-reveal" aria-hidden="true" /> : null}
    </>
  );
}
