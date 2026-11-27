import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useLive, usePoll } from "../hooks/live.jsx";
import { withToken } from "../lib/api.js";
import { ALERT_NAME, ALERT_TYPES, ago, dayTime, plural } from "../lib/format.js";

// Only the alerts, newest first, with their photo and clip. Filter by kind.

const PAGE = 60;
const HELP = {
  zone_entered: "A dog walked into a zone you marked on the Live page.",
  dog_running_at_person: "A running dog was heading towards a person.",
  dog_pack: "Several dogs were close together.",
};

function AlertCard({ a, camera }) {
  const [playing, setPlaying] = useState(false);
  return (
    <li className={`alert-card ${a.type}`}>
      <div className="alert-media">
        {playing && a.clip_url
          ? <video src={withToken(a.clip_url)} controls autoPlay muted playsInline />
          : a.snapshot_url
            ? <a href={withToken(a.snapshot_url)} target="_blank" rel="noreferrer"><img src={withToken(a.snapshot_url)} alt="" loading="lazy" /></a>
            : <span className="no-pic">No photo</span>}
      </div>
      <div className="alert-body">
        <p className="alert-kind">{ALERT_NAME[a.type] || a.type}</p>
        <p>{a.message}</p>
        <p className="small muted" title={new Date(a.ts * 1000).toLocaleString()}>
          {dayTime(a.ts)} ({ago(a.ts)}){camera ? `, ${camera}` : ""}
        </p>
        <div className="row" style={{ marginTop: 6 }}>
          {a.clip_url ? (
            <button className="btn quiet small" onClick={() => setPlaying((p) => !p)}>{playing ? "Show the photo" : "Play the clip"}</button>
          ) : null}
          {a.dog_id ? <Link className="btn quiet small" to={`/dogs/${a.dog_id}`}>Dog #{a.dog_id}</Link> : null}
        </div>
      </div>
    </li>
  );
}

export default function Alerts() {
  const { sources, markAlertsSeen } = useLive();
  const [type, setType] = useState("all");
  const [limit, setLimit] = useState(PAGE);
  // The API has no type filter, so fetch a generous batch and filter here.
  const fetchN = type === "all" ? limit : Math.min(1000, limit * 4);
  const { data, error, loading } = usePoll(`/api/alerts?limit=${fetchN}`, { onEvent: true });
  useEffect(() => { if (data) markAlertsSeen(); }, [data, markAlertsSeen]);   // new ones arrive while you look
  const names = Object.fromEntries((sources || []).map((s) => [s.id, s.name]));
  const many = (sources || []).length > 1;
  const all = data || [];
  const shown = (type === "all" ? all : all.filter((a) => a.type === type)).slice(0, limit);
  const more = all.length >= fetchN ? "+" : "";          // there are older ones we haven't loaded
  const count = (t) => all.filter((a) => a.type === t).length;

  return (
    <div className="alerts-page">
      <div className="toolbar">
        <div className="filter-chips" role="group" aria-label="Kind of alert">
          <button className="chip" aria-pressed={type === "all"} onClick={() => { setType("all"); setLimit(PAGE); }}>
            All {data ? <span>{all.length}{more}</span> : null}
          </button>
          {ALERT_TYPES.map((t) => (
            <button key={t} className={`chip ${t}`} aria-pressed={type === t} onClick={() => { setType(t); setLimit(PAGE); }} title={HELP[t]}>
              {ALERT_NAME[t]} {data ? <span>{count(t)}{count(t) ? more : ""}</span> : null}
            </button>
          ))}
        </div>
        <Link className="small" to="/settings">Choose which alerts fire</Link>
      </div>
      {type !== "all" ? <p className="muted small" style={{ marginBottom: 12 }}>{HELP[type]}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {shown.length ? (
        <>
          <ul className="alert-cards">
            {shown.map((a) => <AlertCard key={a.id} a={a} camera={many ? names[a.source_id] : null} />)}
          </ul>
          {all.length >= fetchN && fetchN < 1000 ? (
            <div style={{ textAlign: "center", marginTop: 20 }}>
              <button className="btn quiet" onClick={() => setLimit((n) => n + PAGE)}>Show older alerts</button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="sheet empty">
          <h2>{loading ? "Loading…" : type === "all" ? "No alerts yet" : `No “${ALERT_NAME[type].toLowerCase()}” alerts`}</h2>
          {!loading ? (
            <>
              <p>Alerts come when a dog walks into a zone, runs towards a person, or dogs gather.
                {" "}Mark a zone on the Live page to get the first one.</p>
              <Link className="btn primary" to="/live">Go to Live</Link>
            </>
          ) : null}
        </div>
      )}
      {shown.length ? <p className="muted small" style={{ marginTop: 16 }}>Showing {plural(shown.length, "alert")}.</p> : null}
    </div>
  );
}
