/**
 * While Ducky is showing the user something (Show me, a tour it asked for), a view that
 * opens because of it must not start its own first-open tour over the top.
 */
let busy = 0;

/** Run `work` as AI-guided UI: first-open tours wait until it is done. */
export async function asGuidedUi<T>(work: () => Promise<T>): Promise<T> {
  busy += 1;
  try {
    return await work();
  } finally {
    busy = Math.max(0, busy - 1);
  }
}

export function isGuidedUiBusy(): boolean {
  return busy > 0;
}
