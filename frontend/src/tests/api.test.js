import { describe, expect, it } from "vitest";
import { readToken, setToken, withToken, wsUrl } from "../lib/api.js";

const memory = () => {
  const m = new Map();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
};

describe("access token", () => {
  it("is read from the URL and remembered for the tab", () => {
    const store = memory();
    expect(readToken("?token=abc", store)).toBe("abc");
    expect(readToken("", store)).toBe("abc"); // later pages without ?token= still have it
    expect(readToken("", memory())).toBe(null);
  });

  it("survives blocked storage", () => {
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(readToken("?token=x", broken)).toBe("x");
  });

  it("is added to URLs only when present", () => {
    expect(withToken("/api/a.jpg", null)).toBe("/api/a.jpg");
    expect(withToken("/api/a.jpg", "s e")).toBe("/api/a.jpg?token=s%20e");
    expect(withToken("/api/a?x=1", "t")).toBe("/api/a?x=1&token=t");
  });

  it("builds WebSocket URLs for http and https", () => {
    setToken(null);
    expect(wsUrl("/ws/live", { protocol: "http:", host: "127.0.0.1:8000" })).toBe("ws://127.0.0.1:8000/ws/live");
    setToken("t");
    expect(wsUrl("/ws/live", { protocol: "https:", host: "10.0.0.2:8443" })).toBe("wss://10.0.0.2:8443/ws/live?token=t");
    setToken(null);
  });
});
