/**
 * A view's tour, once, the first time the view opens (Workflows…). It waits for Welcome to
 * be done or skipped, never starts over another tour or a Show me, and respects
 * Settings → General → "Show a tour the first time I open something".
 */
import { getApi } from "../hooks/usePanelApi";
import { getShowMeState } from "../showme/ShowMeService";
import { isGuidedUiBusy } from "../ui-targets/guidedBusy";
import { whenWalkthroughHydrated } from "./persistence";
import { getTour, getWalkthroughState, isCompleted, startTour } from "./WalkthroughService";

const started = new Set<string>();
let toursAllowed: boolean | null = null;

/** Settings switch changed (or read): remember it for this session. */
export function setFirstOpenToursAllowed(on: boolean): void {
  toursAllowed = on;
}

async function allowed(): Promise<boolean> {
  if (toursAllowed !== null) return toursAllowed;
  try {
    const settings = (await getApi()?.get_settings?.()) as { first_open_tours?: boolean } | undefined;
    toursAllowed = settings?.first_open_tours !== false;
  } catch {
    toursAllowed = true;
  }
  return toursAllowed;
}

/** Start `tourId` if this is its first time. True when it started. */
export async function startFirstOpenTour(tourId: string, delayMs = 700): Promise<boolean> {
  if (started.has(tourId)) return false;
  started.add(tourId);
  await whenWalkthroughHydrated();
  if (!getTour(tourId) || isCompleted(tourId) || !(await allowed())) return false;
  // Let the view mount what the tour points at.
  await new Promise((r) => globalThis.setTimeout(r, delayMs));
  // Welcome comes first on a new install; a tour or Show me on screen now (or Ducky
  // opening this view to show something) wins too. Try again the next time it opens.
  if (!isCompleted("app.shell") || getWalkthroughState().active || getShowMeState().request || isGuidedUiBusy()) {
    started.delete(tourId);
    return false;
  }
  return startTour(tourId);
}

/** Test helper. */
export function _resetFirstOpenForTests(): void {
  started.clear();
  toursAllowed = null;
}
