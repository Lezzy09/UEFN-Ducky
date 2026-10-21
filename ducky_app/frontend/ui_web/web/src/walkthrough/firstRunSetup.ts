/**
 * The first-run setup (Welcome → plugins → AI → defaults) runs before any tour of the app.
 * GatewaySetupNotice reports whether it (or the welcome after it) is showing; tours wait.
 */

/** The tour the setup's Finish runs (builtinTours defines its steps). */
export const FIRST_RUN_TOUR_ID = "first.run";

type Listener = () => void;

let decided = false;
let open = false;
let shown = false;
const listeners = new Set<Listener>();

function emit(): void {
  for (const fn of [...listeners]) fn();
}

/** The setup has read the first-run status; `isOpen` is whether it is on screen. */
export function reportFirstRunSetup(isOpen: boolean): void {
  if (decided && open === isOpen) return;
  decided = true;
  open = isOpen;
  if (isOpen) shown = true;
  emit();
}

/** The first-run setup was on screen this session: its Finish runs the first tour itself. */
export function didFirstRunSetupShow(): boolean {
  return shown;
}

export function isFirstRunSetupOpen(): boolean {
  return open;
}

/**
 * Resolves once the setup is not on screen. If it never reports (no panel API),
 * `decideWithinMs` lets the Welcome tour go ahead anyway.
 */
export function whenFirstRunSetupDone(decideWithinMs = 8000): Promise<void> {
  if (decided && !open) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = decided ? undefined : globalThis.setTimeout(() => {
      if (!decided) {
        decided = true;
        emit();
      }
    }, decideWithinMs);
    const check = () => {
      if (decided && !open) {
        if (timer !== undefined) globalThis.clearTimeout(timer);
        listeners.delete(check);
        resolve();
      }
    };
    listeners.add(check);
  });
}

/** Test helper. */
export function _resetFirstRunSetupForTests(): void {
  decided = false;
  open = false;
  shown = false;
  listeners.clear();
}
