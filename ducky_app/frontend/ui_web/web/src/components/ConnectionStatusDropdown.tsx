import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { ConnectionStatusIcon } from "./ConnectionStatusIcon";
import { Icons } from "../icons/Icons";
import type { ListenerStatus } from "../types/panel";
import { useListenerUptimeSec } from "../hooks/useListenerStatus";

function isFramedWebView(): boolean {
  return typeof window !== "undefined" && !window.pywebview && window.parent !== window;
}

const MENU_WIDTH = 300;
const MENU_GAP = 6;

function computeMenuPosition(trigger: HTMLElement): { top: number; left: number } {
  const rect = trigger.getBoundingClientRect();
  let left = rect.left;
  if (left + MENU_WIDTH > window.innerWidth - 8) {
    left = Math.max(8, window.innerWidth - MENU_WIDTH - 8);
  }
  if (left < 8) left = 8;
  return { top: rect.bottom + MENU_GAP, left };
}

interface RowProps {
  label: string;
  detail: string;
  ok: boolean;
  warn?: boolean;
}

/** UEFN and Unreal Editor 5.8+ serve the same Epic MCP on one port; epic_mcp_editor says which holds it. */
export function epicMcpRows(status: ListenerStatus): [RowProps, RowProps] {
  const url = status.epic_mcp_url || "http://127.0.0.1:8000/mcp";
  const reason = String(status.epic_mcp_reason || "").trim();
  const editor = status.epic_mcp_editor || "";
  // other_editor: the editor on the port is not the one this project belongs in.
  const wrongProject = reason === "other_editor";
  const row = (label: string, mine: boolean, otherEditor: string, offline: string): RowProps => {
    if (reason === "disabled") return { label, detail: "Disabled in Settings → MCPs", ok: false };
    if (reason === "port_taken") return { label, detail: "Port taken by another program", ok: false, warn: true };
    if (mine) {
      return wrongProject
        ? { label, detail: "Running · not used for this project", ok: false, warn: true }
        : { label, detail: `Connected · ${url}`, ok: true };
    }
    if (editor) return { label, detail: `Offline · port held by ${otherEditor}`, ok: false, warn: wrongProject };
    return { label, detail: offline, ok: false };
  };
  return [
    row(
      "UEFN MCP",
      editor === "uefn" || (!editor && Boolean(status.epic_mcp_online)),
      "Unreal Editor",
      `Offline${reason ? ` · ${reason}` : ""}`,
    ),
    row("Unreal MCP", editor === "unreal", "UEFN", "Offline · open Unreal Editor 5.8+ with Unreal MCP"),
  ];
}

function Row({ label, detail, ok, warn }: RowProps) {
  const state = warn ? "warn" : ok ? "ok" : "off";
  return (
    <div className={`connection-status-menu-row is-${state}`}>
      <span className="connection-status-menu-dot" aria-hidden />
      <div className="connection-status-menu-text">
        <span className="connection-status-menu-label">{label}</span>
        <span className="connection-status-menu-detail">{detail}</span>
      </div>
    </div>
  );
}

export interface ConnectionStatusDropdownProps {
  status: ListenerStatus;
  projectName?: string;
  hasStoreUpdates?: boolean;
  onOpenSettings: () => void;
  readonly?: boolean;
  /** Remote/mobile: recent projects list (replaces the header project dropdown). */
  extra?: ReactNode;
}

/** Header duck icon: click toggles Ducky MCP + UEFN listener + Epic MCP connection panel. */
export function ConnectionStatusDropdown({
  status,
  projectName,
  hasStoreUpdates = false,
  onOpenSettings,
  readonly = false,
  extra,
}: ConnectionStatusDropdownProps) {
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement | HTMLSpanElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const isOnline = Boolean(status.online);
  const isWedged = Boolean(status.wedged);
  const race = Boolean(status.listener_init_race) && !isOnline;
  const uptimeSec = useListenerUptimeSec(open) ?? status.uptime_sec;

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      setMenuPos(null);
      return;
    }
    const update = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      setMenuPos(computeMenuPosition(trigger));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const duckyDetail = isWedged
    ? "Wedged — reload_listener once, then stay on workspace_*"
    : isOnline
      ? `Connected · port ${status.port ?? 4200}${uptimeSec ? ` · up ${Math.floor(uptimeSec)}s` : ""}`
      : race
        ? "Offline — listener init race; stay on workspace_*"
        : "Offline — open UEFN + start listener";

  const [uefnMcpRow, unrealMcpRow] = epicMcpRows(status);

  const panelProject = projectName?.trim() || "";
  const duckyMcpDetail = panelProject ? `Connected · ${panelProject}` : "Connected";

  const title = status.status_text?.trim() || (isOnline ? "Online" : "Offline");

  const menu =
    open && menuPos && !readonly ? (
      <div
        ref={menuRef}
        className="connection-status-menu connection-status-menu--portaled no-drag"
        style={{ top: menuPos.top, left: menuPos.left }}
        role="dialog"
        aria-label="Connection status"
      >
        <button
          type="button"
          className="connection-status-menu-settings"
          onClick={() => {
            setOpen(false);
            onOpenSettings();
          }}
        >
          <Icons.Settings />
          <span>Settings</span>
          {hasStoreUpdates ? <span className="store-update-dot store-update-dot--inline" /> : null}
        </button>
        {isFramedWebView() ? (
          <button
            type="button"
            className="connection-status-menu-settings"
            onClick={() => {
              setOpen(false);
              window.parent.postMessage({ type: "ud-remote-close" }, "*");
            }}
          >
            <Icons.Close />
            <span>Close web view</span>
          </button>
        ) : null}
        {extra}
        <div className="connection-status-menu-head">Connections</div>
        <Row label="Ducky MCP" detail={duckyMcpDetail} ok />
        <Row label="UEFN listener" detail={duckyDetail} ok={isOnline && !isWedged} warn={isWedged || race} />
        <Row {...uefnMcpRow} />
        <Row {...unrealMcpRow} />
        {(status.plugin_connections ?? []).map((row) => (
          <Row
            key={row.id}
            label={row.label}
            detail={row.detail}
            ok={row.online}
            warn={row.warn}
          />
        ))}
      </div>
    ) : null;

  if (readonly) {
    return (
      <span className="connection-status-btn connection-status-btn--readonly" title={title}>
        <ConnectionStatusIcon isOnline={isOnline} isWedged={isWedged} />
      </span>
    );
  }

  return (
    <div className="connection-status-root">
      <button
        ref={triggerRef as RefObject<HTMLButtonElement>}
        type="button"
        className={`no-drag connection-status-btn${open ? " is-active" : ""}${hasStoreUpdates ? " has-store-update" : ""}`}
        title={title}
        aria-label={title}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <ConnectionStatusIcon isOnline={isOnline} isWedged={isWedged} />
        {hasStoreUpdates ? <span className="store-update-dot" aria-label="Store updates available" /> : null}
      </button>
      {menu ? createPortal(menu, document.body) : null}
    </div>
  );
}
