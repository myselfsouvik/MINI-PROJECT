import { describe, expect, it } from "vitest";
import { markSetupDone, resetSetup, setupDone, shouldOpenSetup } from "../lib/setup.js";

const memory = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }; };

describe("guided setup", () => {
  it("remembers that it was done, and can be restarted", () => {
    const s = memory();
    expect(setupDone(s)).toBe(false);
    markSetupDone(s);
    expect(setupDone(s)).toBe(true);
    resetSetup(s);
    expect(setupDone(s)).toBe(false);
  });

  it("survives blocked storage", () => {
    const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
    expect(setupDone(broken)).toBe(false);
    expect(() => markSetupDone(broken)).not.toThrow();
    expect(setupDone(null)).toBe(false);
  });

  it("opens only on the home page, with no cameras, the first time", () => {
    expect(shouldOpenSetup({ sources: [], pathname: "/", done: false })).toBe(true);
    expect(shouldOpenSetup({ sources: null, pathname: "/", done: false })).toBe(false);     // still loading
    expect(shouldOpenSetup({ sources: [{ id: "cam1" }], pathname: "/", done: false })).toBe(false);
    expect(shouldOpenSetup({ sources: [], pathname: "/cameras", done: false })).toBe(false);
    expect(shouldOpenSetup({ sources: [], pathname: "/", done: true })).toBe(false);
  });
});
