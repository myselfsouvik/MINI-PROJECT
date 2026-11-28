import { describe, expect, it } from "vitest";
import { RANGES, fillTimeline } from "../lib/timeline.js";

describe("activity timeline", () => {
  it("every range has a sensible number of bars", () => {
    for (const r of Object.values(RANGES)) {
      const bars = (r.minutes * 60) / r.bucket;
      expect(bars).toBeGreaterThanOrEqual(24);
      expect(bars).toBeLessThanOrEqual(60);
    }
  });

  it("fills quiet buckets and converts to dog-minutes", () => {
    const since = 1000;
    const rows = fillTimeline([{ start: 1120, RESTING: 60, WALKING: 30, RUNNING: 0 }], since, 60, 5);
    expect(rows).toHaveLength(5);
    expect(rows[2]).toMatchObject({ start: 1120, RESTING: 1, WALKING: 0.5, RUNNING: 0 });
    expect(rows[0].RESTING + rows[4].RESTING).toBe(0);
  });

  it("keeps buckets slightly off the client clock inside the row", () => {
    const rows = fillTimeline([{ start: 990, RUNNING: 60 }, { start: 1305, WALKING: 60 }], 1000, 60, 5);
    expect(rows[0].RUNNING).toBe(1);
    expect(rows[4].WALKING).toBe(1);
  });
});
