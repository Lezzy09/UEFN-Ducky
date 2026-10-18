import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icons } from "../icons/Icons";
import { getApi } from "../hooks/usePanelApi";

export type AccountDucky = { keyId: string; name: string; live: boolean; mine: boolean };

const MENU_WIDTH = 280;
const REFRESH_MS = 60_000;

/** This Ducky first, then the reachable ones, then the rest, each by name. */
export function sortDuckies(rows: Array<Partial<AccountDucky>>): AccountDucky[] {
  return rows
    .filter((r) => r.keyId)
    .map((r) => ({ keyId: String(r.keyId), name: String(r.name || "UEFN Ducky"), live: !!r.live, mine: !!r.mine }))
    .sort((a, b) => Number(b.mine) - Number(a.mine) || Number(b.live) - Number(a.live) || a.name.localeCompare(b.name));
}

/** The other Duckies' line: who you can reach right now. */
export function othersLine(duckies: AccountDucky[]): string {
  const others = duckies.filter((d) => !d.mine);
  const live = others.filter((d) => d.live).length;
  if (!others.length) return "";
  return live ? `${live} of ${others.length} online` : "None online";
}

/**
 * Header: which UEFN Ducky you're on, and your account's other UEFN Duckies. Picking
 * one opens it in its own window (its whole app: a chat started there runs on that
 * Ducky's computer, with its tools). Shown only when the account has another Ducky.
 */
export function DuckiesDropdown() {
  const [duckies, setDuckies] = useState<AccountDucky[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const api = getApi();
    if (!api?.ducky_link_list) return;
    try {
      const res = await api.ducky_link_list();
      if (res?.ok === false) {
        setError(String(res.error || ""));
        return;
      }
      setError("");
      setDuckies(sortDuckies(res?.devices ?? []));
    } catch {
      /* signed out or offline: the button stays as it was */
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      setPos(null);
      return;
    }
    const r = triggerRef.current.getBoundingClientRect();
    setPos({ top: r.bottom + 6, left: Math.max(8, Math.min(r.left, window.innerWidth - MENU_WIDTH - 8)) });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const others = duckies.filter((d) => !d.mine);
  if (!others.length) return null;
  const me = duckies.find((d) => d.mine);

  const openDucky = (d: AccountDucky) => {
    setOpen(false);
    void getApi()?.ducky_link_open?.(d.keyId, d.name);
  };

  const menu =
    open && pos ? (
      <div
        ref={menuRef}
        className="connection-status-menu connection-status-menu--portaled duckies-menu no-drag"
        style={{ top: pos.top, left: pos.left, width: MENU_WIDTH }}
        role="dialog"
        aria-label="Your UEFN Duckies"
      >
        <div className="connection-status-menu-head">Your UEFN Duckies</div>
        {me ? (
          <div className="connection-status-menu-row is-ok">
            <span className="connection-status-menu-dot" aria-hidden />
            <div className="connection-status-menu-text">
              <span className="connection-status-menu-label">{me.name}</span>
              <span className="connection-status-menu-detail">This one · you're here</span>
            </div>
          </div>
        ) : null}
        {others.map((d) => (
          <button
            key={d.keyId}
            type="button"
            className={`connection-status-menu-row duckies-menu-row is-${d.live ? "ok" : "off"}`}
            disabled={!d.live}
            title={d.live ? `Open ${d.name} here` : `${d.name} is offline, or Remote access is off on it`}
            onClick={() => openDucky(d)}
          >
            <span className="connection-status-menu-dot" aria-hidden />
            <div className="connection-status-menu-text">
              <span className="connection-status-menu-label">{d.name}</span>
              <span className="connection-status-menu-detail">{d.live ? "Online · open to talk to it" : "Offline"}</span>
            </div>
          </button>
        ))}
        {error ? <div className="duckies-menu-note">{error}</div> : null}
        <div className="duckies-menu-note">A Ducky shows online while it's open with Remote access on.</div>
      </div>
    ) : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`no-drag duckies-btn${open ? " is-active" : ""}`}
        title={`Your UEFN Duckies · ${othersLine(duckies)}`}
        aria-label="Your UEFN Duckies"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <Icons.Users />
        <span className="duckies-btn__count">{others.filter((d) => d.live).length}</span>
      </button>
      {menu ? createPortal(menu, document.body) : null}
    </>
  );
}
