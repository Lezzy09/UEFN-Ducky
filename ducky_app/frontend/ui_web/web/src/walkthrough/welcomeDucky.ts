/**
 * A fresh install's first start opens the welcome ducky: a chat whose first message
 * offers every walkthrough as a button (TourOffer). The backend makes it once per
 * AppData (`welcome_ducky_first_run`), so later starts open nothing.
 */
import { onApiReady } from "../hooks/onApiReady";
import { requestOpenChatTab } from "../navigation/openChatReference";

function wait(ms: number): Promise<void> {
  return new Promise((r) => globalThis.setTimeout(r, ms));
}

/** The welcome ducky's id when this start made it (and its tab was asked to open), else null. */
export async function openWelcomeDuckyOnFirstRun(): Promise<string | null> {
  const api = await new Promise<Parameters<Parameters<typeof onApiReady>[0]>[0]>((resolve) => {
    onApiReady(resolve);
  });
  if (!api.welcome_ducky_first_run) return null;
  let made: Awaited<ReturnType<NonNullable<typeof api.welcome_ducky_first_run>>>;
  try {
    made = await api.welcome_ducky_first_run();
  } catch {
    return null;
  }
  if (!made?.created || !made.id) return null;
  // The chats view may still be mounting on a first start: keep asking for a moment.
  for (let i = 0; i < 25; i++) {
    if (requestOpenChatTab(made.id, made.title || "Welcome to Ducky")) break;
    await wait(200);
  }
  return made.id;
}
