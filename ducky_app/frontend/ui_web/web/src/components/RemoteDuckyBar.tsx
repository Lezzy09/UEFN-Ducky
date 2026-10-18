import { useEffect, useState } from "react";
import { getDirectTransport, type DirectStatus } from "../remote/directTransport";

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

/**
 * Top of a window that shows another of your UEFN Duckies: which one you're talking
 * to and whether the link is up. Everything below it is that Ducky's own app: a chat
 * started here runs on its computer, with its tools.
 */
export function RemoteDuckyBar({ name }: { name: string }) {
  const [status, setStatus] = useState<DirectStatus | null>(null);
  useEffect(() => getDirectTransport()?.onStatus(setStatus), []);
  const line = remoteDuckyLine(name, status);
  return (
    <div className={`remote-ducky-bar is-${line.tone}`} role="status" aria-live="polite">
      <span className="remote-ducky-bar__dot" aria-hidden="true" />
      <span className="remote-ducky-bar__text">{line.text}</span>
      {line.tone === "off" ? (
        <button type="button" className="remote-ducky-bar__retry" onClick={() => window.location.reload()}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
