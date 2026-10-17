/** Scope bar wording. Pure so the 80% / full rules have one test. */
import type { PluginScopeStatus, PluginScopeUsage } from "../types/panel";

const UNITS = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(n: number): string {
  let v = Math.max(0, n || 0);
  let i = 0;
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${i === 0 || v >= 10 ? Math.round(v) : v.toFixed(1).replace(/\.0$/, "")} ${UNITS[i]}`;
}

export type StorageLine = { text: string; pct: number; level: "ok" | "warn" | "full"; note: string };

/** "34 MB of 5 GB" + level: warn from 80%, full at the limit. The note carries the
 * level as text so it never rests on colour alone. */
export function storageLine(usage: PluginScopeUsage | undefined): StorageLine | null {
  const used = usage?.usedBytes ?? 0;
  const limit = usage?.limitBytes ?? 0;
  if (!limit) return null;
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const level = used >= limit ? "full" : used * 10 >= limit * 8 ? "warn" : "ok";
  const note = level === "full" ? "Storage full" : level === "warn" ? `${pct}% used` : "";
  return { text: `${formatBytes(used)} of ${formatBytes(limit)}`, pct, level, note };
}

export function agoText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Sync part of a shared bar: synced time, queued changes, or why it isn't syncing. */
export function syncText(status: PluginScopeStatus, nowMs: number): string {
  const pending = status.pending ?? 0;
  const waiting = pending ? ` · ${plural(pending, "change")} waiting` : "";
  // No provider: changes still queue here, and the reason is the whole phrase.
  if (status.state === "no_provider") return `${status.error || "Not connected"}${waiting}`;
  if (status.state === "offline") return `Offline${waiting}`;
  if (status.state === "error") return `Not synced${waiting}`;
  if (status.state === "unavailable") return status.error ? `Not available: ${status.error}` : "Not available";
  if (status.state === "reset") return "Reset on the server";
  const synced = status.syncedAt ? `Synced ${agoText(nowMs / 1000 - status.syncedAt)}` : "Not synced yet";
  return `${synced}${waiting}`;
}

/** What the bar says for a plugin that keeps its own files: nothing to share. */
export const LOCAL_ONLY_TEXT = "Local only: this plugin keeps its own files";

/** A shared copy the provider can't use now: read-only, with the reason. */
export function unavailableText(label: string, reason?: string): string {
  return `${label} isn't available right now${reason ? ` (${reason})` : ""}. Read-only until it's back.`;
}

/** A shared copy whose data was reset on the server: read-only until the user picks
 * Upload my copy or Clear my copy (`canChoose` false when this build offers neither). */
export function resetText(label: string, kind: string, canChoose: boolean): string {
  const what = `${label}'s ${kind} data was reset on the server.`;
  return canChoose
    ? `${what} Your copy here is read-only until you choose what to do with it.`
    : `${what} Your copy here is read-only.`;
}

export type HeldItem = {
  kind: string;
  key: string;
  state: string;
  /** "<key>: <reason>", one line. */
  text: string;
  /** Retry and Drop my change apply (refused or blocked). */
  fixable: boolean;
};

const HELD_REASONS: Record<string, string> = {
  refused: "the server refused it",
  conflict: "changed here and by someone else",
  locked_out: "locked by someone else",
};

/** Changes that aren't going out, each with its reason. `count` is the total; the list
 * may hold fewer (the status lists the newest only). */
export function notShared(status: PluginScopeStatus): { count: number; items: HeldItem[] } {
  const items = (status.items ?? []).map((item): HeldItem => {
    const tries = item.attempts ? ` after ${item.attempts} ${item.attempts === 1 ? "try" : "tries"}` : "";
    const reason = item.reason || HELD_REASONS[item.state] || (item.state === "blocked" ? `couldn't be sent${tries}` : "not sent");
    return {
      kind: item.kind,
      key: item.key,
      state: item.state,
      text: `${item.key}${item.deleted ? " (deleted here)" : ""}: ${reason}`,
      fixable: item.state === "refused" || item.state === "blocked",
    };
  });
  const counted = (status.refused ?? 0) + (status.blocked ?? 0) + (status.conflict ?? 0);
  return { count: Math.max(counted, items.length), items };
}

/** A shared copy whose access was lost: locked here, and when it leaves this PC. */
export function lostText(label: string, deleteAt?: number | null, locale?: string): string {
  const when = deleteAt
    ? new Date(deleteAt * 1000).toLocaleDateString(locale, { month: "long", day: "numeric" })
    : "";
  return when
    ? `You no longer have access to ${label}. Its data here is locked and leaves this PC on ${when} unless access comes back.`
    : `You no longer have access to ${label}. Its data here is locked until access comes back.`;
}

/** Title case of a provider's kind label ("space" → "Space"); "Space" when there is none. */
export function kindTitle(kindLabel?: string): string {
  const k = (kindLabel || "space").trim();
  return k.charAt(0).toUpperCase() + k.slice(1);
}

/** The question before a plugin's data switches: nothing is copied, and the plugin
 * restarts on the other copy. Leaving a shared copy (`from`), its changes still to send go
 * first, and the ones that aren't going out (`held`) stay in that copy on this PC. */
export function switchConfirm(
  plugin: string,
  to: { kind: string; label: string },
  from?: { label: string; pending?: number; held?: number },
): { title: string; message: string } {
  const shared = to.kind === "shared";
  const pending = from?.pending ?? 0;
  const held = from?.held ?? 0;
  const before = [
    pending ? `${plural(pending, "change")} not sent to ${from?.label} will be sent first.` : "",
    held ? `${plural(held, "change")} not shared stay${held === 1 ? "s" : ""} in ${from?.label}'s copy on this PC.` : "",
  ];
  return {
    title: `Switch ${plugin} to ${shared ? to.label : "Local"} data?`,
    message: [...before, `Nothing is copied. ${plugin} restarts with ${shared ? `${to.label}'s` : "its Local"} data.`]
      .filter(Boolean)
      .join(" "),
  };
}

/** The question before Drop my change: this PC's change goes, and is never sent. */
export function dropConfirm(label: string, key: string): { title: string; message: string } {
  return {
    title: `Drop your change to ${key}?`,
    message: `It is removed from this PC and never sent to ${label}.`,
  };
}

/** "A", "A and B", "A, B and C". */
export function listText(names: string[]): string {
  if (names.length < 2) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The question before Upload my copy / Clear my copy, after a reset on the server. Either
 * one is for this PC's whole copy of the space (`contents`: every plugin's data and its
 * workflows), so it names all of it. */
export function resetConfirm(
  action: "upload" | "clear",
  label: string,
  contents: string[] = [],
): { title: string; message: string } {
  const what = contents.length ? `: ${listText(contents)}` : "";
  return action === "upload"
    ? {
        title: `Upload your copy of ${label}?`,
        message: `This PC's whole copy of ${label}'s data is sent again, and everyone in ${label} gets it${what}.`,
      }
    : {
        title: `Clear your copy of ${label}?`,
        message: `This PC's whole copy of ${label}'s data is deleted${what}. ${label}'s data on the server comes down instead, and nothing is sent.`,
      };
}
