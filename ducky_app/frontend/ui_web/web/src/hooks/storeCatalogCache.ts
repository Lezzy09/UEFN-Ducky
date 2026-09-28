import type { DuckyOSStoreCatalog } from "../types/panel";

const STORAGE_KEY = "uefn-store-catalog-v1";

/** In-memory catalog — survives Settings tab switches within the same panel session. */
let memory: DuckyOSStoreCatalog | null = null;

/** Disk snapshot without icon payloads (base64 blows past localStorage quotas). */
function forDisk(catalog: DuckyOSStoreCatalog): DuckyOSStoreCatalog {
  return {
    ok: catalog.ok,
    error: catalog.error,
    code: catalog.code,
    account: catalog.account,
    teams: catalog.teams,
    teamsInfo: catalog.teamsInfo,
    items: (catalog.items || []).map((item) => {
      const { icon_data_url: _drop, ...rest } = item;
      return rest;
    }),
  };
}

function readDisk(): DuckyOSStoreCatalog | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DuckyOSStoreCatalog;
    if (!parsed || !Array.isArray(parsed.items)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeDisk(catalog: DuckyOSStoreCatalog): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(forDisk(catalog)));
  } catch {
    /* quota / private mode — memory cache still works */
  }
}

/** Last known good catalog (memory first, then disk). */
export function peekStoreCatalogCache(): DuckyOSStoreCatalog | null {
  if (memory?.items?.length) return memory;
  const disk = readDisk();
  if (disk?.items?.length) {
    memory = disk;
    return disk;
  }
  return memory;
}

/**
 * Remember a catalog fetch. A failed empty refresh keeps the last good copy, but
 * only for the same account: another account's copy (private team items) is replaced.
 */
export function rememberStoreCatalog(catalog: DuckyOSStoreCatalog): void {
  const sameAccount = (catalog.account ?? "") === (peekStoreCatalogCache()?.account ?? "");
  if (sameAccount && catalog.ok === false && !(catalog.items || []).length) return;
  memory = catalog;
  writeDisk(catalog);
}

/** Account switched (login / logout / expiry): drop every copy, the Store refetches. */
export function clearStoreCatalogCache(): void {
  memory = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* private mode */
  }
}
