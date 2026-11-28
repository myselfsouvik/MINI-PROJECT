// Time ranges on the Activity page and the activity timeline's buckets.

export const RANGES = {
  "1h": { label: "Last hour", minutes: 60, bucket: 60 },              // 60 one-minute bars
  "24h": { label: "Last 24 hours", minutes: 1440, bucket: 1800 },     // 48 half-hour bars
  "7d": { label: "Last 7 days", minutes: 10080, bucket: 21600 },      // 28 six-hour bars
};

/**
 * The API only returns buckets that have data. Lay them on a full row of buckets from `since`
 * (so quiet times show as gaps) and turn dog-seconds into dog-minutes.
 */
export function fillTimeline(buckets, since, bucket, minutes) {
  const count = Math.round((minutes * 60) / bucket);
  const rows = Array.from({ length: count }, (_, i) => ({ start: since + i * bucket, RESTING: 0, WALKING: 0, RUNNING: 0 }));
  for (const b of buckets) {
    const i = Math.min(count - 1, Math.max(0, Math.round((b.start - since) / bucket)));
    for (const a of ["RESTING", "WALKING", "RUNNING"]) rows[i][a] += (b[a] || 0) / 60;
  }
  return rows;
}

/** Axis label for a bucket start: "14:05" within a day, "Mon 18:00" for the week. */
export function bucketLabel(ts, rangeKey) {
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return rangeKey === "7d" ? `${d.toLocaleDateString([], { weekday: "short" })} ${time}` : time;
}
