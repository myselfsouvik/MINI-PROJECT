import { describe, expect, it } from "vitest";
import { ago, duration, isAlert, pct, plural } from "../lib/format.js";

describe("formatting", () => {
  it("durations", () => {
    expect(duration(42)).toBe("42s");
    expect(duration(120)).toBe("2m");
    expect(duration(135)).toBe("2m 15s");
    expect(duration(7200)).toBe("2.0h");
    expect(duration(-3)).toBe("0s");
  });

  it("relative times", () => {
    expect(ago(1000, 1010)).toBe("just now");
    expect(ago(1000, 1000 + 600)).toBe("10 min ago");
    expect(ago(1000, 1000 + 7200)).toBe("2 h ago");
  });

  it("alerts and small helpers", () => {
    expect(isAlert({ type: "dog_pack" })).toBe(true);
    expect(isAlert({ type: "dog_appeared" })).toBe(false);
    expect(plural(1, "dog")).toBe("1 dog");
    expect(plural(3, "dog")).toBe("3 dogs");
    expect(pct(0.456)).toBe("46%");
  });
});
