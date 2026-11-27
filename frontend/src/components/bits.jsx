// Small shared pieces used on several pages.
import { useState } from "react";
import { withToken } from "../lib/api.js";
import { ACT_NAME, ACTS, ALERT_NAME, ago, clock, duration, pct } from "../lib/format.js";

const ACT_VAR = { RESTING: "var(--rest)", WALKING: "var(--walk)", RUNNING: "var(--run)" };

/** A dog on camera right now, as a collar tag. `d` is one dog from the live WebSocket. */
export function DogTag({ d, camera }) {
  const zone = (d.zones || []).join(", ");
  const model = d.behaviour && d.behaviour !== d.activity ? `, model says ${String(d.behaviour).toLowerCase()}` : "";
  return (
    <li className={`tag ${d.activity}`}>
      <span className="id">#{d.dog_id}</span>
      <span><span className={`act ${d.activity}`}>{ACT_NAME[d.activity] || d.activity}</span>{model}</span>
      <span className="meta">
        {duration(d.seconds_visible)} in view{camera ? ` on ${camera}` : ""}, {Math.round(d.confidence * 100)}% sure
      </span>
      {zone ? <span className="zone">In {zone}</span> : null}
    </li>
  );
}

/** One alert with its photo. */
export function AlertItem({ a, cameraName }) {
  return (
    <li className="alert-item">
      {a.snapshot_url
        ? <a href={withToken(a.snapshot_url)} target="_blank" rel="noreferrer"><img className="thumb" src={withToken(a.snapshot_url)} alt="" loading="lazy" /></a>
        : <span className="thumb" />}
      <div>
        <b>{ALERT_NAME[a.type] || a.type}</b>
        <p>{a.message}</p>
        <p className="when" title={new Date(a.ts * 1000).toLocaleString()}>
          {ago(a.ts)}, {clock(a.ts)}{cameraName ? `, ${cameraName}` : ""}
        </p>
        {a.clip_url ? <p className="small"><a href={withToken(a.clip_url)} target="_blank" rel="noreferrer">Watch the clip</a></p> : null}
      </div>
    </li>
  );
}

/** Resting / walking / running as one bar with a legend. `seconds` or `share` per activity. */
export function ActivitySplit({ seconds, share }) {
  const total = seconds ? ACTS.reduce((t, a) => t + (seconds[a] || 0), 0) : 1;
  if (seconds && !total) return <p className="muted small">No dogs seen in this period.</p>;
  const frac = (a) => (share ? share[a] || 0 : (seconds[a] || 0) / total);
  return (
    <div>
      <div className="split" role="img" aria-label={ACTS.map((a) => `${ACT_NAME[a]} ${pct(frac(a))}`).join(", ")}>
        {ACTS.map((a) => <div key={a} className={a} style={{ width: `${100 * frac(a)}%` }} />)}
      </div>
      <div className="legend">
        {ACTS.map((a) => (
          <span key={a} style={{ "--c": ACT_VAR[a] }}>
            {ACT_NAME[a]} {seconds ? duration(seconds[a] || 0) : pct(frac(a))}
          </span>
        ))}
      </div>
    </div>
  );
}

/** The live annotated video of one camera, inside the asphalt frame. */
export function LiveFrame({ sourceId, alt = "Live camera with dog boxes", children }) {
  const [failed, setFailed] = useState(null);
  const src = sourceId ? withToken(`/api/sources/${sourceId}/stream.mjpg`) : null;
  return (
    <div className="frame">
      {src && failed !== src
        ? <img key={src} src={src} alt={alt} onError={() => setFailed(src)} />
        : (
          <div className="frame-msg">
            {src ? <><b>The picture stopped.</b><span>The camera may have been unplugged or the video ended.</span></>
                 : <span>No camera picked.</span>}
          </div>
        )}
      {children}
    </div>
  );
}

export function EmptyState({ title, children, actions, dark }) {
  return (
    <div className={`empty${dark ? " on-asphalt" : ""}`}>
      <h2>{title}</h2>
      {children ? <p>{children}</p> : null}
      {actions ? <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>{actions}</div> : null}
    </div>
  );
}
