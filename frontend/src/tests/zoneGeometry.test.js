import { describe, expect, it } from "vitest";
import { pictureRect, toBox, toFrame } from "../lib/zoneGeometry.js";

describe("zone geometry", () => {
  // A 4:3 picture in a 16:9 box gets bars on the left and right.
  const rect = pictureRect({ width: 1600, height: 900 }, { width: 1200, height: 900 });

  it("finds the picture inside the letterbox", () => {
    expect(rect).toEqual({ left: 200, top: 0, w: 1200, h: 900 });
  });

  it("converts clicks to frame fractions and back", () => {
    expect(toFrame(800, 450, rect)).toEqual([0.5, 0.5]);
    expect(toFrame(100, 450, rect)).toBe(null); // on the black bar
    expect(toBox([0.25, 1], rect)).toEqual([500, 900]);
  });
});
