import { useSyncExternalStore } from "react";

export type RemotePicture = { w: number; h: number };

/** The size of the PC picture on screen now (null while none shows): the title bar's Fit. */
let picture: RemotePicture | null = null;
const subs = new Set<() => void>();

export function setRemotePicture(next: RemotePicture | null) {
  if (picture === next || (picture && next && picture.w === next.w && picture.h === next.h)) return;
  picture = next;
  subs.forEach((fn) => fn());
}

export function useRemotePicture(): RemotePicture | null {
  return useSyncExternalStore(
    (onChange) => {
      subs.add(onChange);
      return () => subs.delete(onChange);
    },
    () => picture,
    () => null,
  );
}
