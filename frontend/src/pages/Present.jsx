import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { LiveFrame } from "../components/bits.jsx";
import { Logo } from "../components/Icon.jsx";
import { useLive, usePoll } from "../hooks/live.jsx";
import { withToken } from "../lib/api.js";
import { ACT_NAME, ACTS, ALERT_NAME, clock } from "../lib/format.js";

// For showing DogWatch to a room: the live picture as big as it goes, a few numbers you can read
// from the back row, and each new alert popping in with its photo. Controls hide when the mouse is still.

const POP_SECONDS = 10;
const IDLE_MS = 3000;

function useIdle(ms) {
  const [idle, setIdle] = useState(false);
  useEffect(() => {
    let t;
    const wake = () => { setIdle(false); clearTimeout(t); t = setTimeout(() => setIdle(true), ms); };
    wake();
    const evs = ["mousemove", "keydown", "touchstart"];
    evs.forEach((e) => window.addEventListener(e, wake));
    return () => { clearTimeout(t); evs.forEach((e) => window.removeEventListener(e, wake)); };
  }, [ms]);
  return idle;
}

export default function Present() {
  const [params, setParams] = useSearchParams();
  const { sources, live, connected } = useLive();
  const summary = usePoll("/api/stats/summary?minutes=1440", { every: 15000, onEvent: true });
  const latest = usePoll("/api/alerts?limit=1", { onEvent: true });
  const [pop, setPop] = useState(null);
  const lastId = useRef(null);
  const idle = useIdle(IDLE_MS);
  const [full, setFull] = useState(false);

  const wanted = params.get("camera");
  const cam = sources?.find((s) => s.id === wanted) || sources?.find((s) => s.status === "running") || sources?.[0];
  const l = cam ? live[cam.id] : null;
  const s = summary.data;
  const counts = Object.fromEntries(ACTS.map((a) => [a, (l?.dogs || []).filter((d) => d.activity === a).length]));

  useEffect(() => { document.title = "Presentation | DogWatch"; }, []);
  useEffect(() => {
    const on = () => setFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  // Pop the newest alert in, but not the one that was already there when the page opened.
  useEffect(() => {
    const a = latest.data?.[0];
    if (!a) return undefined;
    if (lastId.current === null) { lastId.current = a.id; return undefined; }
    if (a.id === lastId.current) return undefined;
    lastId.current = a.id;
    setPop(a);
    const t = setTimeout(() => setPop(null), POP_SECONDS * 1000);
    return () => clearTimeout(t);
  }, [latest.data]);

  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else document.documentElement.requestFullscreen?.().catch(() => {});
  };

  return (
    <div className={`present${idle ? " idle" : ""}`}>
      <header className="present-top">
        <span className="brand-inline"><Logo /><b>DogWatch</b></span>
        <span className="present-sub">Street dog monitoring{cam ? ` · ${cam.name}` : ""}</span>
        <span className="present-live"><span className={`dot ${connected ? "ok" : connected === false ? "bad" : "wait"}`} />
          {connected ? "Live" : connected === false ? "Reconnecting…" : "Connecting…"}</span>
        <div className="present-controls">
          {sources?.length > 1 ? (
            <select aria-label="Camera" value={cam?.id || ""} onChange={(e) => setParams({ camera: e.target.value }, { replace: true })}>
              {sources.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          ) : null}
          {document.fullscreenEnabled ? <button className="btn quiet small" onClick={toggleFull}>{full ? "Leave full screen" : "Full screen"}</button> : null}
          <Link className="btn quiet small" to="/">Close</Link>
        </div>
      </header>

      <main className="present-body">
        <section className="present-stage" aria-label="Live camera">
          {sources && !sources.length ? (
            <div className="frame"><div className="frame-msg"><b>No camera is watching yet.</b>
              <span>Add one on the <Link to="/cameras">Cameras</Link> page, or start the demo video.</span></div></div>
          ) : <LiveFrame sourceId={cam?.id} />}
        </section>

        <aside className="present-side" aria-label="Numbers">
          <div className="big"><b className="num">{l ? l.dogs.length : "–"}</b><span>dogs on camera now</span></div>
          <ul className="present-acts">
            {ACTS.map((a) => <li key={a} className={a}><b className="num">{l ? counts[a] : "–"}</b>{ACT_NAME[a].toLowerCase()}</li>)}
          </ul>
          <div className="present-today">
            <div><b className="num">{s ? s.dogs_seen : "–"}</b>dogs seen today</div>
            <div><b className="num">{s ? s.alerts : "–"}</b>alerts today</div>
          </div>
          {latest.data?.[0] && !pop ? (
            <p className="present-last">Last alert: {ALERT_NAME[latest.data[0].type] || latest.data[0].type}, {clock(latest.data[0].ts)}</p>
          ) : null}
        </aside>
      </main>

      {pop ? (
        <div className="present-pop" role="alert" key={pop.id}>
          {pop.snapshot_url ? <img src={withToken(pop.snapshot_url)} alt="" /> : null}
          <div>
            <span className="kicker">New alert · {clock(pop.ts)}</span>
            <b>{ALERT_NAME[pop.type] || pop.type}</b>
            <p>{pop.message}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
