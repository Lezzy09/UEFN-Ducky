/**
 * Where plugin UI prefs live in localStorage: one bag per DuckyOS account (plan
 * rule 0.6), `uefn-plugin-ui-prefs@<account>` with the host's `account_key`
 * ("" when signed out). Every reader and writer goes through `pluginPrefsKey()`.
 * Switching accounts drops every other account's bag; the new account's prefs
 * come back from its own rows on disk (`plugin_prefs_get_all`).
 */
const BASE = "uefn-plugin-ui-prefs";
const OWNER = `${BASE}:account`;

const keyFor = (account: string) => `${BASE}@${account}`;

function owner(): string | null {
  try {
    return localStorage.getItem(OWNER);
  } catch {
    return null;
  }
}

/** The bag for the current account. Until the first account check (first run after
 * this change) it is the old shared key, which that check hands to the account. */
export function pluginPrefsKey(): string {
  const current = owner();
  return current === null ? BASE : keyFor(current);
}

/** Point prefs at `account`. Returns true when the bag changed (callers reload). */
export function setPluginPrefsAccount(account: string): boolean {
  try {
    const prev = owner();
    if (prev === account) return false;
    // First run: the shared pre-account bag belongs to whoever is signed in now,
    // like the host's own prefs rows.
    const legacy = prev === null ? localStorage.getItem(BASE) : null;
    const keep = keyFor(account);
    for (let i = localStorage.length - 1; i >= 0; i -= 1) {
      const k = localStorage.key(i);
      if (k && k !== keep && (k === BASE || k.startsWith(`${BASE}@`))) localStorage.removeItem(k);
    }
    if (legacy !== null && localStorage.getItem(keep) === null) localStorage.setItem(keep, legacy);
    localStorage.setItem(OWNER, account);
    return true;
  } catch {
    return false;
  }
}
