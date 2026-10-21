import { useEffect, useRef, type RefObject } from "react";

/** Load a plugin page again in place: the same src, so its theme and bridge listeners stay bound. */
export function reloadIframe(iframe: HTMLIFrameElement | null): void {
  const current = iframe?.getAttribute("src");
  if (iframe && current) iframe.setAttribute("src", current);
}

/**
 * An open plugin page keeps running the code it loaded. When its plugin's version changes
 * (a Store update or reinstall), load the page again so it runs the new files (served
 * no-cache). The first version seen is the one the page loaded with, so mounting never reloads.
 */
export function useReloadOnPluginUpdate(
  iframeRef: RefObject<HTMLIFrameElement | null>,
  version: string | number | undefined,
): void {
  const loaded = useRef(version);
  useEffect(() => {
    const was = loaded.current;
    loaded.current = version;
    if (was === undefined || version === undefined || was === version) return;
    reloadIframe(iframeRef.current);
  }, [iframeRef, version]);
}
