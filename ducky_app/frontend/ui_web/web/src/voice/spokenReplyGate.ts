/**
 * "Spoken replies" speaks answers to turns YOU sent from the composer — never
 * replies that finish in the background (automations, sub-agents, spawned or
 * other chats). Without this gate every assistant_done in the app was read
 * aloud, which sounded like Ducky talking on its own.
 */

/** A turn's replies (group chats send several) may arrive this long after Send. */
const WINDOW_MS = 10 * 60_000;

const asked = new Map<string, number>();

/** The user sent a message in this chat — speak the reply when it lands. */
export function noteUserTurn(convId: string): void {
  const id = (convId || "").trim();
  if (id) asked.set(id, Date.now() + WINDOW_MS);
}

/** True while a reply in this chat answers something the user sent recently. */
export function userAwaitsReply(convId: string): boolean {
  const id = (convId || "").trim();
  const until = asked.get(id);
  if (until == null) return false;
  if (until < Date.now()) {
    asked.delete(id);
    return false;
  }
  return true;
}

/** Test helper. */
export function _resetSpokenReplyGate(): void {
  asked.clear();
}
