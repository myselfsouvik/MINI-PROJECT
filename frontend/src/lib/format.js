export const ACTS = ["RESTING", "WALKING", "RUNNING"];
export const ACT_NAME = { RESTING: "Resting", WALKING: "Walking", RUNNING: "Running" };

export const ALERT_TYPES = ["zone_entered", "dog_running_at_person", "dog_pack"];
export const ALERT_NAME = {
  zone_entered: "Entered a zone",
  dog_running_at_person: "Ran towards a person",
  dog_pack: "Dogs gathering",
};
export const isAlert = (e) => ALERT_TYPES.includes(e?.type);

/** 42 -> "42s", 135 -> "2m 15s", 7200 -> "2.0h" */
export function duration(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) {
    const m = Math.floor(s / 60), r = Math.round(s % 60);
    return r ? `${m}m ${r}s` : `${m}m`;
  }
  return `${(s / 3600).toFixed(1)}h`;
}

/** Unix seconds -> "14:05:09" (24-hour, so the column lines up). */
export function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
}

/** Unix seconds -> "just now", "4 min ago", "2 h ago", or the date. */
export function ago(ts, now = Date.now() / 1000) {
  const d = now - ts;
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short" });
}

export const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
export const pct = (x) => `${Math.round(100 * (Number(x) || 0))}%`;

/** Unix seconds -> "Today 14:05", "Yesterday 09:12" or "25 Nov 18:40". */
export function dayTime(ts, now = Date.now() / 1000) {
  const d = new Date(ts * 1000), today = new Date(now * 1000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const days = Math.round((new Date(today).setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

/** Dog speed is measured in the dog's own box heights per second. */
export const speedText = (v) => `${(Number(v) || 0).toFixed(1)} body heights a second`;
