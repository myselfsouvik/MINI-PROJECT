import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DogTag, EmptyState } from "../components/bits.jsx";
import ZoneDrawer, { useZones } from "../components/ZoneDrawer.jsx";
import { useLive, usePoll } from "../hooks/live.jsx";
import { api, withToken } from "../lib/api.js";
import { clock, duration, isAlert, plural } from "../lib/format.js";

// One camera, big: its dogs, its zones (draw and delete) and recording.

export default function Live() {
  const { sources, live, refreshSources } = useLive();
  const [params, setParams] = useSearchParams();
  const [drawing, setDrawing] = useState(false);
  const [note, setNote] = useState(null);         // { text, href? } after saving a zone or a recording
  const [recBusy, setRecBusy] = useState(false);
  const wanted = params.get("camera");
  const cam = sources?.find((s) => s.id === wanted) || sources?.find((s) => s.status === "running") || sources?.[0];
  const id = cam?.id;
  const { zones, error: zoneError, reload, remove } = useZones(id);
  const events = usePoll("/api/events?limit=80", { onEvent: true });

  useEffect(() => { setDrawing(false); setNote(null); }, [id]);

  // Keep the recording timer moving while this camera records.
  const recording = cam?.recording?.active ? cam.recording : null;
  useEffect(() => {
    if (!recording) return undefined;
    const t = setInterval(refreshSources, 1000);
    return () => clearInterval(t);
  }, [!!recording, refreshSources]);                         // eslint-disable-line react-hooks/exhaustive-deps

  if (sources && !sources.length) {
    return (
      <section className="stage on-asphalt">
        <EmptyState dark title="No camera to watch yet"
          actions={<Link className="btn primary" to="/cameras">Add a camera</Link>}>
          Add the laptop webcam, a phone, a video file or the demo video. It shows up here.
        </EmptyState>
      </section>
    );
  }

  const l = (id && live[id]) || null;
  const pick = (sid) => setParams(sid ? { camera: sid } : {}, { replace: true });

  const toggleRecording = async () => {
    setRecBusy(true);
    try {
      if (recording) {
        const r = await api(`/api/sources/${id}/recording`, { method: "DELETE" });
        setNote({ text: `Saved ${r.file} (${duration(r.seconds)}, ${r.size_mb} MB).`, href: withToken(r.url), link: "Download it" });
      } else {
        await api(`/api/sources/${id}/recording`, { method: "POST", body: {} });
        setNote(null);
      }
    } catch (e) { setNote({ text: e.message, error: true }); }
    await refreshSources();
    setRecBusy(false);
  };

  const camEvents = (events.data || []).filter((e) => e.source_id === id && !e.type.startsWith("source_")).slice(0, 8);

  return (
    <div className="overview">
      <div className="stack">
        <section className="stage on-asphalt" aria-label="Live camera">
          {sources?.length > 1 ? (
            <div className="cam-chips" role="group" aria-label="Camera">
              {sources.map((c) => (
                <button key={c.id} className="cam-chip" aria-pressed={c.id === id} onClick={() => pick(c.id)}>
                  <span className={`dot ${(live[c.id]?.status || c.status) === "running" ? "ok" : "bad"}`} />{c.name}
                </button>
              ))}
            </div>
          ) : null}
          <ZoneDrawer sourceId={id} drawing={drawing} zoneCount={zones?.length || 0}
            onCancel={() => setDrawing(false)}
            onSaved={(z) => { setDrawing(false); reload(); setNote({ text: `Saved the zone "${z.name}". You get an alert when a dog walks in.` }); }}
            overlay={recording ? <div className="rec-badge"><i />Recording {duration(recording.seconds)}</div> : null} />
          {!drawing ? (
            <div className="stage-foot">
              <div className="readout">
                <span><b>{l ? l.dogs.length : "–"}</b>dogs</span>
                <span><b>{l ? l.people : "–"}</b>people</span>
                <span><b>{l ? l.inference_fps : "–"}</b>detections per second</span>
                <span><b>{l ? l.camera_fps : "–"}</b>camera frames per second</span>
              </div>
              <div className="row">
                <button className="btn primary small" onClick={() => { setNote(null); setDrawing(true); }} disabled={!id}>Draw a zone</button>
                <button className="btn quiet small" onClick={toggleRecording} disabled={!id || recBusy}
                        title="Saves the clean camera video, for training clips or the report">
                  {recording ? "Stop recording" : "Record"}
                </button>
              </div>
            </div>
          ) : null}
          {l?.error ? <p className="small" style={{ color: "#FF9A80", marginTop: 8 }}>{l.error}</p> : null}
          {note ? (
            <p className={`stage-note${note.error ? " bad" : ""}`} role="status">
              {note.text} {note.href ? <a href={note.href}>{note.link}</a> : null}
            </p>
          ) : null}
        </section>
      </div>

      <div className="rail">
        <section className="sheet">
          <div className="sheet-head"><h2>On this camera now</h2></div>
          <ul className="tags">
            {l?.dogs?.length ? l.dogs.map((d) => <DogTag key={d.dog_id} d={d} />) : <li className="muted">No dogs in view right now.</li>}
          </ul>
        </section>

        <section className="sheet">
          <div className="sheet-head"><h2>Zones</h2>{zones?.length ? <span className="muted small">{plural(zones.length, "zone")}</span> : null}</div>
          {zoneError ? <p className="error small">{zoneError}</p> : null}
          {zones?.length ? (
            <ul className="file-list">
              {zones.map((z) => (
                <li key={z.id}>
                  <span><b>{z.name}</b> <span className="muted small">{z.points.length} corners</span></span>
                  <button className="btn danger small" onClick={() => { if (confirm(`Delete the zone "${z.name}"?`)) remove(z.id); }}>Delete</button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">
              {zones ? "No zones yet. Use Draw a zone to mark a school gate or a shop front. You get an alert when a dog walks in." : "Loading…"}
            </p>
          )}
        </section>

        <section className="sheet">
          <div className="sheet-head"><h2>What happened here</h2><Link to="/alerts">All alerts</Link></div>
          <ul className="feed">
            {camEvents.length ? camEvents.map((e) => (
              <li key={e.id} className={isAlert(e) ? "is-alert" : ""}>
                <time>{clock(e.ts)}</time><span>{e.message}</span>
              </li>
            )) : <li className="muted small">{events.loading ? "Loading…" : "Nothing has happened on this camera yet."}</li>}
          </ul>
        </section>
      </div>
    </div>
  );
}
