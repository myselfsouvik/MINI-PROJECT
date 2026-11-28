import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import AddCamera from "../components/AddCamera.jsx";
import { useLive, usePoll } from "../hooks/live.jsx";
import { api, withToken } from "../lib/api.js";
import { ago, plural } from "../lib/format.js";

// The cameras being watched, adding a new one, and the videos and recordings on this laptop.

const KIND = { webcam: "Webcam", phone: "Phone (browser)", stream: "Network camera or phone app", file: "Video file" };

function CameraCard({ c, l, onRemoved }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const status = l?.status || c.status;
  const ok = status === "running";
  const remove = async () => {
    if (!confirm(`Stop watching ${c.name}? Its zones are kept for next time.`)) return;
    setBusy(true);
    try { await api(`/api/sources/${c.id}`, { method: "DELETE" }); await onRemoved(); }
    catch (e) { setError(e.message); setBusy(false); }
  };
  return (
    <li className="cam-card">
      <img className="cam-thumb" src={withToken(`/api/sources/${c.id}/snapshot.jpg?t=${Math.floor(Date.now() / 10000)}`)} alt=""
           onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
      <div className="cam-info">
        <h3><span className={`dot ${ok ? "ok" : "bad"}`} /> {c.name}</h3>
        <p className="muted small">
          {KIND[c.kind] || c.kind}{c.width ? `, ${c.width}×${c.height}` : ""}{ok ? `, ${l?.inference_fps ?? c.inference_fps} detections per second` : `, ${status}`}
        </p>
        <p className="small">
          {plural(l?.dogs?.length ?? c.dogs_visible, "dog")} in view{c.recording?.active ? ", recording" : ""}
        </p>
        {(l?.error || c.error) ? <p className="error small">{l?.error || c.error}</p> : null}
        {error ? <p className="error small">{error}</p> : null}
      </div>
      <div className="cam-actions">
        <Link className="btn quiet small" to={`/live?camera=${encodeURIComponent(c.id)}`}>Watch live</Link>
        <button className="btn danger small" onClick={remove} disabled={busy}>{busy ? "Removing…" : "Remove"}</button>
      </div>
    </li>
  );
}

export default function Cameras() {
  const { sources, live, refreshSources, sourcesError } = useLive();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const videos = usePoll("/api/uploads", { every: 20000 });
  const none = sources && !sources.length;

  return (
    <div className="cameras">
      <section className="sheet">
        <div className="sheet-head">
          <h2>Cameras</h2>
          {sources?.length ? <span className="muted small">{plural(sources.length, "camera")}</span> : null}
        </div>
        {sourcesError ? <p className="error small">{sourcesError}</p> : null}
        {sources?.length ? (
          <ul className="cam-list">
            {sources.map((c) => <CameraCard key={c.id} c={c} l={live[c.id]} onRemoved={refreshSources} />)}
          </ul>
        ) : (
          <p className="muted">{sources ? "No camera is watching yet. Add one below." : "Loading…"}</p>
        )}
      </section>

      <section className="sheet" id="add">
        <div className="sheet-head"><h2>{none ? "Add your first camera" : "Add a camera"}</h2></div>
        <AddCamera initial={params.get("add")} onAdded={(s) => navigate(`/live?camera=${encodeURIComponent(s.id)}`)} />
      </section>

      <section className="sheet">
        <div className="sheet-head">
          <h2>Videos and recordings</h2>
          <span className="muted small">Saved in the recordings folder</span>
        </div>
        {videos.data?.length ? (
          <ul className="file-list">
            {videos.data.map((v) => (
              <li key={v.source}>
                <span><b>{v.name}</b> <span className="muted small">{v.size_mb} MB, {ago(v.modified)}</span></span>
                <a className="btn quiet small" href={withToken(v.url)} download>Download</a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">{videos.loading ? "Loading…" : "No videos yet. Use Record on the Live page, or upload a clip above."}</p>
        )}
      </section>
    </div>
  );
}
