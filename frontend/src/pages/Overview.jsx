import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ActivitySplit, AlertItem, DogTag, EmptyState, LiveFrame } from "../components/bits.jsx";
import { useLive, usePoll } from "../hooks/live.jsx";
import { plural } from "../lib/format.js";

// "What is happening right now?" in one screen: one camera live, the dogs on every camera,
// today's numbers and the latest alerts. Everything else lives on its own page.

function NoCameras() {
  return (
    <section className="stage on-asphalt">
      <EmptyState dark title="No camera is watching yet"
        actions={<>
          <Link className="btn primary" to="/welcome">Set up DogWatch</Link>
          <Link className="btn quiet" to="/cameras">Add a camera</Link>
        </>}>
        Connect the laptop webcam, a phone or a video file. Every dog it sees gets a box, a number and an activity,
        and you get an alert when one walks into a place you mark.
      </EmptyState>
    </section>
  );
}

export default function Overview() {
  const { sources, live } = useLive();
  const [picked, setPicked] = useState(null);
  const summary = usePoll("/api/stats/summary?minutes=1440", { every: 15000, onEvent: true });
  const alerts = usePoll("/api/alerts?limit=3", { onEvent: true });

  // Show the camera you picked, otherwise the first one that is running.
  useEffect(() => {
    if (!sources?.length) { setPicked(null); return; }
    if (!sources.some((s) => s.id === picked)) {
      setPicked((sources.find((s) => s.status === "running") || sources[0]).id);
    }
  }, [sources, picked]);

  if (sources && !sources.length) return <NoCameras />;

  const names = Object.fromEntries((sources || []).map((s) => [s.id, s.name]));
  const cur = picked && live[picked];
  const watching = (sources || []).filter((s) => (live[s.id]?.status || s.status) === "running").length;
  const dogsNow = Object.entries(live).flatMap(([id, l]) => (l.dogs || []).map((d) => ({ ...d, cam: id })));
  const many = (sources || []).length > 1;
  const s = summary.data;

  return (
    <div className="overview">
      <div className="stack">
        <section className="stage on-asphalt" aria-label="Live camera">
          {many ? (
            <div className="cam-chips" role="group" aria-label="Camera">
              {sources.map((c) => (
                <button key={c.id} className="cam-chip" aria-pressed={c.id === picked} onClick={() => setPicked(c.id)}>
                  <span className={`dot ${(live[c.id]?.status || c.status) === "running" ? "ok" : "bad"}`} />{c.name}
                </button>
              ))}
            </div>
          ) : null}
          <LiveFrame sourceId={picked} />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "end", gap: 12, flexWrap: "wrap" }}>
            <div className="readout">
              <span><b>{cur ? cur.dogs.length : "–"}</b>dogs</span>
              <span><b>{cur ? cur.people : "–"}</b>people</span>
              <span><b>{cur ? cur.inference_fps : "–"}</b>detections per second</span>
            </div>
            <Link className="btn quiet small" to={picked ? `/live?camera=${encodeURIComponent(picked)}` : "/live"}>Open in Live</Link>
          </div>
          {cur?.error ? <p className="small" style={{ color: "#FF9A80", marginTop: 8 }}>{cur.error}</p> : null}
        </section>

        <section className="figures" aria-label="Today">
          <div><b>{sources ? watching : "–"}</b>{sources ? `of ${plural(sources.length, "camera")} watching` : "cameras"}</div>
          <div><b>{s ? s.dogs_seen : "–"}</b>dogs seen today</div>
          <div><b>{s ? s.alerts : "–"}</b>alerts today</div>
          <div><b>{s ? (s.busiest_hour != null ? `${String(s.busiest_hour).padStart(2, "0")}:00` : "None yet") : "–"}</b>busiest hour</div>
        </section>

        <section className="sheet">
          <div className="sheet-head"><h2>How dogs spent today</h2><Link to="/activity">See the charts</Link></div>
          {s ? <ActivitySplit seconds={s.activity_seconds} /> : <p className="muted small">Loading…</p>}
        </section>
      </div>

      <div className="rail">
        <section className="sheet">
          <div className="sheet-head"><h2>On camera now</h2></div>
          <ul className="tags">
            {dogsNow.length
              ? dogsNow.map((d) => <DogTag key={`${d.cam}-${d.dog_id}`} d={d} camera={many ? names[d.cam] : null} />)
              : <li className="muted">No dogs in view right now.</li>}
          </ul>
        </section>
        <section className="sheet">
          <div className="sheet-head"><h2>Latest alerts</h2><Link to="/alerts">All alerts</Link></div>
          {alerts.error ? <p className="error small">{alerts.error}</p> : null}
          <ul className="alert-list">
            {alerts.data?.length
              ? alerts.data.map((a) => <AlertItem key={a.id} a={a} cameraName={many ? names[a.source_id] : null} />)
              : <li className="muted small">{alerts.loading ? "Loading…" : "No alerts yet. Mark a zone on the Live page to get one when a dog walks in."}</li>}
          </ul>
        </section>
      </div>
    </div>
  );
}
