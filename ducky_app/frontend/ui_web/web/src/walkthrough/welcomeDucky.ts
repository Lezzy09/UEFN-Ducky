/**
 * Finish on the first-run setup: the left dock slides open, the welcome ducky (made after the
 * setup saved the Default Model, so the chat runs on it) opens and types its first message out,
 * then the first-run tour walks through the chat. The message is written ahead of time: no
 * model call, no tokens. Replying to it is a normal chat on the Default Model.
 */
import { getApi } from "../hooks/usePanelApi";
import { requestOpenChatTab } from "../navigation/openChatReference";
import { requestOpenDockSide, requestOpenSidebarPanel } from "../navigation/openSidebarPanel";
import { FIRST_RUN_TOUR_ID } from "./firstRunSetup";
import { armIntro, disarmIntro, whenIntroDone } from "./introTyping";
import { markTourCompleted, startTour } from "./WalkthroughService";

function wait(ms: number): Promise<void> {
  return new Promise((r) => globalThis.setTimeout(r, ms));
}

/** Runs once the setup closes; resolves when the first-run tour has started (or there is none). */
export async function welcomeAfterSetup(): Promise<void> {
  requestOpenDockSide("left");
  requestOpenSidebarPanel("chats");
  // The dock slides in before the chat opens next to it.
  await wait(350);
  const api = getApi();
  if (!api?.finish_first_run_setup) return;
  armIntro();
  let made: Awaited<ReturnType<NonNullable<typeof api.finish_first_run_setup>>>;
  try {
    made = await api.finish_first_run_setup();
  } catch {
    made = { ok: false };
  }
  if (!made?.created || !made.id) {
    disarmIntro();
    return;
  }
  // The new chat opens on its own when Ducky announces it; ask too, in case that was missed.
  for (let i = 0; i < 10; i++) {
    if (requestOpenChatTab(made.id, made.title || "Welcome to Ducky")) break;
    await wait(200);
  }
  await whenIntroDone();
  // The first-run tour walks through the chat box, so the chat's own tour is covered.
  markTourCompleted("chat.composer");
  await wait(250);
  await startTour(FIRST_RUN_TOUR_ID, { force: true });
}
