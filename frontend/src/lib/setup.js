// Whether this browser has finished (or skipped) the guided setup.
// Stored per browser; "Restart setup" in Settings and Help clears it.

const KEY = "dogwatch-setup-done";
const local = () => { try { return globalThis.localStorage; } catch { return null; } };

export function setupDone(store = local()) {
  try { return store?.getItem(KEY) === "1"; } catch { return false; }
}

export function markSetupDone(store = local()) {
  try { store?.setItem(KEY, "1"); } catch { /* storage blocked: setup may show again, that's all */ }
}

export function resetSetup(store = local()) {
  try { store?.removeItem(KEY); } catch { /* nothing to clear */ }
}

/** Open the setup when the home page loads with no cameras on a browser that hasn't done it. */
export function shouldOpenSetup({ sources, pathname, done }) {
  return pathname === "/" && Array.isArray(sources) && sources.length === 0 && !done;
}

export const STEPS = ["Add a camera", "See a dog", "Mark a zone", "Tour"];
