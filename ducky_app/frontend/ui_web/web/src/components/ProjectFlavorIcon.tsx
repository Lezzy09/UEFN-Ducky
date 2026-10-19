import { useSyncExternalStore } from "react";
import { Icons } from "../icons/Icons";
import type { ProjectFlavor } from "../types/panel";

/* The open project's flavor, set from project info (useProject) like the Content root. */
let current: ProjectFlavor | "" = "";
const listeners = new Set<() => void>();

export function setProjectFlavor(next: ProjectFlavor | "" | undefined): void {
  const value = next || "";
  if (value === current) return;
  current = value;
  listeners.forEach((listener) => listener());
}

export function useProjectFlavor(): ProjectFlavor | "" {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
    () => current,
    () => current,
  );
}

const FLAVOR_NAMES: Record<ProjectFlavor, string> = {
  uefn: "UEFN island",
  roblox: "Roblox project",
  unreal: "Unreal project",
  unity: "Unity project",
  folder: "Folder project",
};

export function projectFlavorName(flavor: ProjectFlavor | "" | undefined): string {
  return FLAVOR_NAMES[flavor || "folder"];
}

/** A project's icon: Verse for an island, the engine's mark for Roblox / Unreal / Unity,
 * else a folder. */
export function ProjectFlavorIcon({ flavor }: { flavor: ProjectFlavor | "" | undefined }) {
  switch (flavor) {
    case "uefn":
      return <Icons.Verse />;
    case "roblox":
      return <Icons.Roblox />;
    case "unreal":
      return <Icons.Unreal />;
    case "unity":
      return <Icons.Box />;
    default:
      return <Icons.Folder />;
  }
}
