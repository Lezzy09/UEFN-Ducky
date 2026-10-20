/**
 * The main window's WebRTC host for live editing (backend/uefn_plugins/rtc.py). The
 * spaces provider asks for connections to other Duckies with `rtc_cmd` events; the
 * window opens them, answers with `rtc_reply`, and reports what arrives and how each link
 * is with `rtc_event`. Bytes travel as the base64 text the backend sends: the window
 * never reads them.
 *
 * Two DataChannels per peer: `live` (ordered, reliable) and `live-fast` (unordered, no
 * retransmits: pointers). An offer or answer waits for ICE gathering (3 s cap) so it
 * carries every candidate and one message each way sets up a link.
 */
import { installAgentEventBus, subscribeAgentEventsImmediate } from "../hooks/useAgentEventBus";
import { onApiReady } from "../hooks/onApiReady";
import { getApi, isRemote } from "../hooks/usePanelApi";
import { WINDOW_ID } from "../tabs/tabRegistryClient";

export const LIVE_CHANNELS = ["live", "live-fast"] as const;
const GATHER_MS = 3000;

type Peer = { pc: RTCPeerConnection; channels: Map<string, RTCDataChannel>; told: string };
type Desc = { type: string; sdp: string };
type Cmd = {
  type: "rtc_cmd";
  id?: string;
  op: "open" | "accept" | "finish" | "send" | "close";
  peer: string;
  ice?: RTCIceServer[];
  offer?: Desc;
  answer?: Desc;
  channel?: string;
  data?: string;
};

const peers = new Map<string, Peer>();
let installed = false;

function reply(id: string | undefined, result: Record<string, unknown>) {
  if (id) void getApi()?.rtc_reply?.(id, result);
}

function tell(peer: string, kind: "message" | "state", payload: Record<string, unknown>) {
  void getApi()?.rtc_event?.(peer, kind, payload);
}

/** The link's state as the backend counts it: `connected` once `live` can carry bytes. */
function stateOf(p: Peer): string {
  const st = p.pc.connectionState;
  if (st === "failed" || st === "closed" || st === "disconnected") return st;
  return p.channels.get("live")?.readyState === "open" ? "connected" : "connecting";
}

function report(peerId: string, p: Peer) {
  const st = stateOf(p);
  if (st === p.told) return;
  p.told = st;
  tell(peerId, "state", { state: st });
}

function wire(peerId: string, p: Peer, ch: RTCDataChannel) {
  if (!(LIVE_CHANNELS as readonly string[]).includes(ch.label)) return;
  p.channels.set(ch.label, ch);
  ch.onmessage = (ev) => {
    if (typeof ev.data === "string") tell(peerId, "message", { channel: ch.label, data: ev.data });
  };
  ch.onopen = () => report(peerId, p);
  ch.onclose = () => report(peerId, p);
}

function newPeer(peerId: string, ice: RTCIceServer[]): Peer {
  drop(peerId, false);
  const pc = new RTCPeerConnection({ iceServers: ice });
  const p: Peer = { pc, channels: new Map(), told: "" };
  peers.set(peerId, p);
  pc.onconnectionstatechange = () => report(peerId, p);
  pc.ondatachannel = (ev) => wire(peerId, p, ev.channel);
  return p;
}

function drop(peerId: string, say = true) {
  const p = peers.get(peerId);
  if (!p) return;
  peers.delete(peerId);
  try {
    p.pc.close();
  } catch {
    /* already closed */
  }
  if (say) tell(peerId, "state", { state: "closed" });
}

/** The local description once ICE gathering is done (or 3 s passed), as plain JSON:
 * pywebview can't pass an RTCSessionDescription. */
function gathered(pc: RTCPeerConnection): Promise<Desc> {
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check);
      window.clearTimeout(timer);
      const d = pc.localDescription;
      resolve({ type: d?.type ?? "", sdp: d?.sdp ?? "" });
    };
    const check = () => {
      if (pc.iceGatheringState === "complete") done();
    };
    const timer = window.setTimeout(done, GATHER_MS);
    pc.addEventListener("icegatheringstatechange", check);
    check();
  });
}

export async function handleRtcCmd(cmd: Cmd): Promise<void> {
  const peerId = String(cmd.peer || "");
  try {
    if (cmd.op === "open") {
      const p = newPeer(peerId, cmd.ice ?? []);
      wire(peerId, p, p.pc.createDataChannel("live", { ordered: true }));
      wire(peerId, p, p.pc.createDataChannel("live-fast", { ordered: false, maxRetransmits: 0 }));
      await p.pc.setLocalDescription(await p.pc.createOffer());
      reply(cmd.id, { offer: await gathered(p.pc) });
    } else if (cmd.op === "accept") {
      const p = newPeer(peerId, cmd.ice ?? []);
      await p.pc.setRemoteDescription(cmd.offer as RTCSessionDescriptionInit);
      await p.pc.setLocalDescription(await p.pc.createAnswer());
      reply(cmd.id, { answer: await gathered(p.pc) });
    } else if (cmd.op === "finish") {
      const p = peers.get(peerId);
      if (!p) throw new Error("no such peer");
      await p.pc.setRemoteDescription(cmd.answer as RTCSessionDescriptionInit);
      reply(cmd.id, { ok: true });
    } else if (cmd.op === "send") {
      const ch = peers.get(peerId)?.channels.get(String(cmd.channel || ""));
      if (ch?.readyState === "open" && typeof cmd.data === "string") ch.send(cmd.data);
    } else if (cmd.op === "close") {
      drop(peerId);
    }
  } catch (err) {
    reply(cmd.id, { error: String((err as Error)?.message || err) });
  }
}

export function installLivePeerHost(): () => void {
  if (installed) return () => {};
  installed = true;
  installAgentEventBus();
  // Not frame-batched: a hidden or minimized window still answers its teammates.
  const unsub = subscribeAgentEventsImmediate((event) => {
    if (event.type === "rtc_cmd") void handleRtcCmd(event as unknown as Cmd);
  });
  return () => {
    installed = false;
    unsub();
    for (const id of [...peers.keys()]) drop(id);
  };
}

/** The desktop app's main window only: phones, the window for another Ducky and focus
 * windows never host this PC's links. Decided once the pywebview bridge is in. */
export function installLivePeerHostOnDesktop(): () => void {
  let undo = () => {};
  const stop = onApiReady(() => {
    if (!isRemote() && WINDOW_ID === "main") undo = installLivePeerHost();
  });
  return () => {
    stop();
    undo();
  };
}

export function livePeerCountForTest(): number {
  return peers.size;
}
