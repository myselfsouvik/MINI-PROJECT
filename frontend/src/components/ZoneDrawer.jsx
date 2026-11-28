// The live picture of one camera, with zone drawing on top: click corners on the
// video, name the zone, save. Used by the Live page and by the guided setup.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { pictureRect, toBox, toFrame } from "../lib/zoneGeometry.js";
import { LiveFrame } from "./bits.jsx";

const MAX_CORNERS = 20;

/** Zones of one camera, with delete. `version` bumps when a zone was added elsewhere. */
export function useZones(sourceId) {
  const [zones, setZones] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(async () => {
    if (!sourceId) { setZones([]); return; }
    try { setZones(await api(`/api/sources/${sourceId}/zones`)); setError(null); }
    catch (e) { setError(e.message); setZones((z) => z ?? []); }
  }, [sourceId]);
  useEffect(() => { setZones(null); load(); }, [load]);
  const remove = async (id) => {
    try { await api(`/api/zones/${id}`, { method: "DELETE" }); } catch (e) { setError(e.message); }
    load();
  };
  return { zones, error, reload: load, remove };
}

/**
 * Live frame + zone drawing.
 *   drawing   : show the corner-picking layer and the name form
 *   onSaved   : called with the new zone after it is saved
 *   onCancel  : drawing was cancelled
 *   zoneCount : how many zones the camera has (for the default name)
 *   defaultName: name put in the box when drawing starts
 */
export default function ZoneDrawer({ sourceId, drawing, onSaved, onCancel, zoneCount = 0, defaultName = "",
                                     overlay, alt }) {
  const wrap = useRef(null);
  const [draft, setDraft] = useState([]);
  const [name, setName] = useState(defaultName);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [, redraw] = useState(0);

  // Start each drawing fresh.
  useEffect(() => {
    if (drawing) { setDraft([]); setName(defaultName); setError(null); }
  }, [drawing, defaultName]);

  // The overlay follows the picture when the window or the video size changes.
  useEffect(() => {
    if (!drawing) return undefined;
    const onResize = () => redraw((n) => n + 1);
    window.addEventListener("resize", onResize);
    const t = setInterval(onResize, 1000);          // first frame decides the picture size
    return () => { window.removeEventListener("resize", onResize); clearInterval(t); };
  }, [drawing]);

  const measure = () => {
    const box = wrap.current?.querySelector(".frame");
    const img = box?.querySelector("img");
    if (!box) return null;
    const r = box.getBoundingClientRect();
    return { r, rect: pictureRect(r, { width: img?.naturalWidth, height: img?.naturalHeight }) };
  };

  const onPick = (e) => {
    const m = measure();
    if (!m || draft.length >= MAX_CORNERS) return;
    const pt = toFrame(e.clientX - m.r.left, e.clientY - m.r.top, m.rect);
    if (pt) setDraft((d) => [...d, pt]);
  };

  const save = async (e) => {
    e.preventDefault();
    if (draft.length < 3 || saving) return;
    setSaving(true);
    try {
      const zone = await api(`/api/sources/${sourceId}/zones`, {
        method: "POST", body: { name: name.trim() || `Zone ${zoneCount + 1}`, points: draft },
      });
      setDraft([]);
      onSaved?.(zone);
    } catch (err) { setError(err.message); }
    setSaving(false);
  };

  const m = drawing ? measure() : null;
  const pts = m ? draft.map((p) => toBox(p, m.rect)) : [];
  const left = 3 - draft.length;
  const hint = left > 0
    ? `Click ${left} more corner${left === 1 ? "" : "s"} on the video.`
    : `${draft.length} corners. Name the zone and save it, or keep clicking to add corners.`;

  return (
    <div ref={wrap}>
      <LiveFrame sourceId={sourceId} alt={alt}>
        {overlay}
        {drawing ? (
          <div className="draw-layer" onClick={onPick}>
            {m ? (
              <svg viewBox={`0 0 ${m.r.width} ${m.r.height}`}>
                {pts.length > 1 ? <polygon points={pts.map((p) => p.join(",")).join(" ")} /> : null}
                {pts.map(([cx, cy], i) => <circle key={i} cx={cx} cy={cy} r="6" />)}
              </svg>
            ) : null}
          </div>
        ) : null}
      </LiveFrame>
      {drawing ? (
        <form className="zone-form" onSubmit={save}>
          <div className="row">
            <label className="sr-only" htmlFor="zone-name">Zone name</label>
            <input id="zone-name" className="grow" value={name} maxLength={40} onChange={(e) => setName(e.target.value)}
                   placeholder="Zone name, e.g. School gate" />
            <button className="btn primary" disabled={draft.length < 3 || saving}>{saving ? "Saving…" : "Save zone"}</button>
            <button type="button" className="btn quiet" disabled={!draft.length} onClick={() => setDraft((d) => d.slice(0, -1))}>
              Undo corner
            </button>
            <button type="button" className="btn quiet" onClick={() => { setDraft([]); onCancel?.(); }}>Cancel</button>
          </div>
          <p aria-live="polite">{error ? <span className="error">{error}</span> : hint}</p>
        </form>
      ) : null}
    </div>
  );
}
