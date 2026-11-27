import { describe, expect, it } from "vitest";
import { pathRuns } from "../lib/dogPath.js";

const pt = (x, activity) => ({ x, y: 0.5, ts: x, activity });

describe("dog path", () => {
  it("splits by activity and joins the pieces", () => {
    const runs = pathRuns([pt(0, "RESTING"), pt(1, "RESTING"), pt(2, "WALKING"), pt(3, "WALKING"), pt(4, "RUNNING")]);
    expect(runs.map((r) => r.activity)).toEqual(["RESTING", "WALKING", "RUNNING"]);
    expect(runs[1].points.map((p) => p.x)).toEqual([1, 2, 3]);       // starts where the last run ended
    expect(runs[2].points.map((p) => p.x)).toEqual([3, 4]);
  });

  it("a single point draws no line", () => {
    expect(pathRuns([pt(0, "RESTING")])).toEqual([]);
    expect(pathRuns([])).toEqual([]);
  });
});
