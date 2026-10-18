import { useCallback, useEffect, useState } from "react";
import { getApi } from "../../hooks/usePanelApi";
import { Icons } from "../../icons/Icons";
import { Modal, ModalActions } from "../Modal";
import type { DuckySyncPeer } from "../../types/panel";

const REFRESH_MS = 60_000;

/** "just now", "5 min ago", "3 h ago", "2 d ago". */
export function agoText(secs: number, now = Date.now() / 1000): string {
  if (!secs) return "never";
  const d = Math.max(0, now - secs);
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return `${Math.floor(d / 86400)} d ago`;
}

/** Peers with chats, live ones first, each with its live flag from the account's list. */
export function withLive(peers: DuckySyncPeer[], live: Record<string, boolean>): Array<DuckySyncPeer & { live: boolean }> {
  return peers
    .filter((p) => p.chats.length)
    .map((p) => ({ ...p, live: !!live[p.ducky] }))
    .sort((a, b) => Number(b.live) - Number(a.live) || a.name.localeCompare(b.name));
}

type CopyView = {
  peer: DuckySyncPeer & { live: boolean };
  chat: DuckySyncPeer["chats"][number];
  rows: Array<{ id?: number | string; role?: string; text?: string }>;
  synced: number;
  error: string;
};

/**
 * Bottom of the Duckies panel: your other UEFN Duckies' chats, copied here by sync. A
 * chat lives on its home Ducky (its agent runs there): pressing one opens it there while
 * that Ducky is online, else shows the copy, read only.
 */
export function OtherDuckiesChats() {
  const [peers, setPeers] = useState<DuckySyncPeer[]>([]);
  const [live, setLive] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [copy, setCopy] = useState<CopyView | null>(null);

  const load = useCallback(async () => {
    const api = getApi();
    if (!api?.ducky_sync_list) return;
    try {
      const [list, link] = await Promise.all([api.ducky_sync_list(), api.ducky_link_list?.()]);
      if (list?.ok !== false) setPeers(list?.duckies ?? []);
      const flags: Record<string, boolean> = {};
      for (const d of link?.devices ?? []) if (d.keyId) flags[d.keyId] = !!d.live;
      setLive(flags);
    } catch {
      /* signed out or offline: keep what's shown */
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const shown = withLive(peers, live);
  if (!shown.length) return null;

  const openChat = async (peer: DuckySyncPeer & { live: boolean }, chat: DuckySyncPeer["chats"][number]) => {
    const api = getApi();
    if (peer.live && api?.ducky_link_open) {
      void api.ducky_link_open(peer.ducky, peer.name, chat.conv_id);
      return;
    }
    const res = await api?.ducky_sync_copy?.(peer.ducky, chat.conv_id);
    setCopy({
      peer,
      chat,
      rows: res?.rows ?? [],
      synced: Number(res?.synced || chat.synced || 0),
      error: res?.ok === false ? String(res.error || "") : "",
    });
  };

  return (
    <div className="other-duckies" aria-label="Chats on your other UEFN Duckies">
      <div className="other-duckies__head">
        <span>On your other Duckies</span>
        <button
          type="button"
          className="other-duckies__sync"
          title="Sync now"
          aria-label="Sync now with your other UEFN Duckies"
          onClick={() => {
            void getApi()?.ducky_sync_now?.();
            window.setTimeout(() => void load(), 8_000);
          }}
        >
          <Icons.Refresh />
        </button>
      </div>
      {shown.map((peer) => {
        const expanded = !!open[peer.ducky];
        return (
          <div key={peer.ducky} className="other-duckies__peer">
            <button
              type="button"
              className="other-duckies__peer-row"
              aria-expanded={expanded}
              onClick={() => setOpen((o) => ({ ...o, [peer.ducky]: !expanded }))}
            >
              <span className={`other-duckies__chev${expanded ? " is-open" : ""}`} aria-hidden="true">
                <Icons.ChevronRight />
              </span>
              <span className={`other-duckies__dot${peer.live ? " is-live" : ""}`} aria-hidden="true" />
              <span className="other-duckies__name">{peer.name}</span>
              <span className="other-duckies__meta">{peer.live ? "online" : `synced ${agoText(peer.synced)}`}</span>
            </button>
            {expanded
              ? peer.chats.map((chat) => (
                  <button
                    key={chat.conv_id}
                    type="button"
                    className="other-duckies__chat"
                    title={peer.live ? `Open on ${peer.name}` : `Read the copy from ${agoText(chat.synced)}`}
                    onClick={() => void openChat(peer, chat)}
                  >
                    <Icons.Chat />
                    <span className="other-duckies__chat-title">{chat.title || "Untitled chat"}</span>
                  </button>
                ))
              : null}
          </div>
        );
      })}
      <Modal
        open={!!copy}
        onClose={() => setCopy(null)}
        title={copy ? copy.chat.title || "Untitled chat" : ""}
        width={640}
        footer={
          copy ? (
            <ModalActions
              onCancel={() => setCopy(null)}
              cancelLabel="Close"
              confirmLabel={`Open on ${copy.peer.name}`}
              confirmDisabled={!copy.peer.live}
              onConfirm={() => {
                void getApi()?.ducky_link_open?.(copy.peer.ducky, copy.peer.name, copy.chat.conv_id);
                setCopy(null);
              }}
            />
          ) : null
        }
      >
        {copy ? (
          <div className="other-duckies-copy">
            <p className="other-duckies-copy__note">
              On {copy.peer.name} · a read-only copy from {agoText(copy.synced)}.
              {copy.peer.live ? "" : ` ${copy.peer.name} is offline: open it there to talk to it.`}
            </p>
            {copy.error ? <p className="other-duckies-copy__note">{copy.error}</p> : null}
            {copy.rows.map((row, i) => (
              <div key={`${row.id ?? i}-${i}`} className={`other-duckies-copy__row is-${row.role || "assistant"}`}>
                <span className="other-duckies-copy__who">{row.role === "user" ? "You" : row.role === "tool" ? "Tool" : "Ducky"}</span>
                <span className="other-duckies-copy__text">{row.text}</span>
              </div>
            ))}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
