import { Link, useParams } from "react-router-dom";
import { ActivitySplit } from "../components/bits.jsx";
import { useLive, usePoll } from "../hooks/live.jsx";
import { withToken } from "../lib/api.js";
import { pathRuns } from "../lib/dogPath.js";
import { ACT_NAME, ACTS, clock, dayTime, duration, isAlert, speedText } from "../lib/format.js";

// One dog: its photo, how long it stayed, what it did, where it went on the camera picture.

const W = 160, H = 90;                       // path drawn in a 16:9 box

function DogPath({ path }) {
  if (!path.length) return <p className="muted small">No positions were saved for this dog.</p>;
  const first = path[0], last = path[path.length - 1];
  return (
    <figure className="dog-path">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Where the dog went on the camera picture, coloured by activity">
        <rect width={W} height={H} className="bg" />
        {[1, 2, 3].map((i) => <line key={`v${i}`} className="grid" x1={(W * i) / 4} x2={(W * i) / 4} y1="0" y2={H} />)}
        {[1, 2].map((i) => <line key={`h${i}`} className="grid" y1={(H * i) / 3} y2={(H * i) / 3} x1="0" x2={W} />)}
        {pathRuns(path).map((r, i) => (
          <polyline key={i} className={`run ${r.activity}`} points={r.points.map((p) => `${p.x * W},${p.y * H}`).join(" ")} />
        ))}
        <circle className="start" cx={first.x * W} cy={first.y * H} r="2.6" />
        <circle className="end" cx={last.x * W} cy={last.y * H} r="2.6" />
      </svg>
      <figcaption className="legend">
        <span style={{ "--c": "#fff" }}>First seen</span>
        <span style={{ "--c": "var(--marigold)" }}>Last seen</span>
        {ACTS.map((a) => <span key={a} style={{ "--c": `var(--${a === "RESTING" ? "rest" : a === "WALKING" ? "walk" : "run"})` }}>{ACT_NAME[a]}</span>)}
      </figcaption>
    </figure>
  );
}

/** The visit from first to last sighting as one strip, coloured by activity. */
function VisitStrip({ path }) {
  if (path.length < 2) return null;
  const t0 = path[0].ts, span = path[path.length - 1].ts - t0 || 1;
  return (
    <div>
      <div className="visit-strip" role="img" aria-label="Activity during the visit, from first to last sighting">
        {path.slice(1).map((p, i) => (
          <i key={i} className={p.activity} style={{ left: `${(100 * (path[i].ts - t0)) / span}%`, width: `${(100 * (p.ts - path[i].ts)) / span}%` }} />
        ))}
      </div>
      <div className="strip-ends small muted"><span>{clock(path[0].ts)}</span><span>{clock(path[path.length - 1].ts)}</span></div>
    </div>
  );
}

export default function DogProfile() {
  const { id } = useParams();
  const { sources } = useLive();
  const { data: d, error, loading } = usePoll(`/api/dogs/${encodeURIComponent(id)}?observations=false`, { every: 10000 });

  if (!d) {
    return (
      <div className="sheet empty">
        <h2>{loading ? "Loading…" : `No dog #${id}`}</h2>
        {!loading ? <p>{error || "It may have been cleaned up with old data."}</p> : null}
        <Link className="btn quiet" to="/dogs">All dogs</Link>
      </div>
    );
  }

  // Camera ids (cam1, cam2...) start again after a restart, so only name the camera for a dog
  // seen in the last few minutes; older ones may have been on a different camera with the same id.
  const recent = Date.now() / 1000 - d.last_seen < 600;
  const camName = recent ? sources?.find((s) => s.id === d.source_id)?.name : null;
  const alerts = d.events.filter(isAlert).length;

  return (
    <div className="profile-page">
      <p><Link to="/dogs">← All dogs</Link></p>
      <section className="profile-head sheet">
        {d.snapshot_url ? <img className="profile-pic" src={withToken(d.snapshot_url)} alt={`Dog #${d.id}`} /> : <span className="profile-pic no-pic">No photo</span>}
        <div className="profile-text">
          <h2 className="dog-name">Dog #{d.id}</h2>
          <p className="muted">Seen {dayTime(d.first_seen)} to {clock(d.last_seen)}{camName ? ` on ${camName}` : ""}</p>
          {d.main_activity ? <p>Mostly <span className={`act ${d.main_activity}`}>{ACT_NAME[d.main_activity].toLowerCase()}</span></p> : null}
          <div className="facts">
            <div><b>{duration(d.seconds_visible)}</b>in view</div>
            <div><b>{(d.max_speed || 0).toFixed(1)}</b>top speed<span className="muted small"> (body heights a second)</span></div>
            <div><b>{Math.round(d.best_confidence * 100)}%</b>best detection</div>
            <div><b>{alerts}</b>{alerts === 1 ? "alert" : "alerts"}</div>
          </div>
        </div>
      </section>

      <div className="profile-grid">
        <section className="sheet">
          <div className="sheet-head"><h2>Where it went</h2></div>
          <DogPath path={d.path} />
        </section>
        <div className="stack">
          <section className="sheet">
            <div className="sheet-head"><h2>How it spent its time</h2></div>
            <ActivitySplit share={d.activity_share} />
            <h3 style={{ margin: "16px 0 8px" }}>During the visit</h3>
            <VisitStrip path={d.path} />
            <p className="small muted" style={{ marginTop: 8 }} title={speedText(d.max_speed)}>
              Resting {duration(d.resting_s)}, walking {duration(d.walking_s)}, running {duration(d.running_s)}.
            </p>
          </section>
          <section className="sheet">
            <div className="sheet-head"><h2>What it did</h2></div>
            <ul className="feed">
              {d.events.length ? d.events.slice(0, 12).map((e) => (
                <li key={e.id} className={isAlert(e) ? "is-alert" : ""}>
                  <time>{clock(e.ts)}</time>
                  <span>{e.message}
                    {e.snapshot_url ? <> <a href={withToken(e.snapshot_url)} target="_blank" rel="noreferrer">Photo</a></> : null}
                    {e.clip_url ? <> <a href={withToken(e.clip_url)} target="_blank" rel="noreferrer">Clip</a></> : null}
                  </span>
                </li>
              )) : <li className="muted small">No events for this dog.</li>}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
