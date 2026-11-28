import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, wsUrl } from "../lib/api.js";
import { isAlert } from "../lib/format.js";

// One WebSocket for the whole app. The server sends every 0.5 s:
//   { ts, sources: { <id>: live state }, events: [new events] }
// We also keep the camera list (/api/sources) fresh, and count alerts the user hasn't looked at.

const LiveContext = createContext(null);
const SEEN_KEY = "dogwatch-alerts-seen";

// The first time this browser opens the app, older alerts don't count as new.
function readSeen() {
  const now = Date.now() / 1000;
  try {
    const stored = Number(localStorage.getItem(SEEN_KEY));
    if (stored) return stored;
    localStorage.setItem(SEEN_KEY, String(now));
  } catch { /* storage blocked: count from now */ }
  return now;
}

export function LiveProvider({ children }) {
  const [connected, setConnected] = useState(null); // null = connecting, true, false
  const [live, setLive] = useState({});             // per-camera live state
  const [sources, setSources] = useState(null);     // null until loaded
  const [sourcesError, setSourcesError] = useState(null);
  const [eventTick, setEventTick] = useState(0);    // bumps when new events arrive
  const [seenAt, setSeenAt] = useState(readSeen);
  const [unseen, setUnseen] = useState(0);
  const listeners = useRef(new Set());

  const refreshSources = useCallback(async () => {
    try {
      setSources(await api("/api/sources"));
      setSourcesError(null);
    } catch (e) {
      setSourcesError(e.message);
      setSources((s) => s ?? []);
    }
  }, []);

  // Alerts newer than the last time the Alerts page was open.
  const refreshUnseen = useCallback(async () => {
    try {
      const alerts = await api("/api/alerts?limit=50");
      setUnseen(alerts.filter((a) => a.ts > seenAt).length);
    } catch { /* keep the old count */ }
  }, [seenAt]);

  const markAlertsSeen = useCallback(() => {
    const now = Date.now() / 1000;
    try { localStorage.setItem(SEEN_KEY, String(now)); } catch { /* per-browser convenience only */ }
    setSeenAt(now);
    setUnseen(0);
  }, []);

  useEffect(() => { refreshSources(); const t = setInterval(refreshSources, 10000); return () => clearInterval(t); }, [refreshSources]);
  useEffect(() => { refreshUnseen(); }, [refreshUnseen]);

  useEffect(() => {
    let ws, retry, closed = false;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/live"));
      ws.onopen = () => setConnected(true);
      ws.onmessage = (m) => {
        const data = JSON.parse(m.data);
        setLive(data.sources || {});
        if (data.events?.length) {
          setEventTick((t) => t + 1);
          if (data.events.some(isAlert)) setUnseen((n) => n + data.events.filter(isAlert).length);
          if (data.events.some((e) => e.type.startsWith("source_"))) refreshSources();
          listeners.current.forEach((fn) => fn(data.events));
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => { closed = true; clearTimeout(retry); ws?.close(); };
  }, [refreshSources]);

  const onEvents = useCallback((fn) => {
    listeners.current.add(fn);
    return () => listeners.current.delete(fn);
  }, []);

  const value = useMemo(() => ({
    connected, live, sources, sourcesError, refreshSources, eventTick, onEvents, unseen, markAlertsSeen,
  }), [connected, live, sources, sourcesError, refreshSources, eventTick, onEvents, unseen, markAlertsSeen]);

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);

/** Fetch `path`, refetch every `every` ms and whenever new events arrive (if `onEvent`). */
export function usePoll(path, { every = 0, onEvent = false } = {}) {
  const { eventTick } = useLive();
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const tick = onEvent ? eventTick : 0;

  useEffect(() => {
    if (!path) { setState({ data: null, error: null, loading: false }); return undefined; }
    let alive = true;
    const load = () => api(path)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((e) => alive && setState((s) => ({ data: s.data, error: e.message, loading: false })));
    load();
    const t = every ? setInterval(load, every) : null;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [path, every, tick]);

  return state;
}
