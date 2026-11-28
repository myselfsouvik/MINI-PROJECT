import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, withToken } from "../lib/api.js";
import { plural } from "../lib/format.js";
import { resetSetup } from "../lib/setup.js";

// Everything you can change, grouped by what it affects. Changes apply at once and last until
// the server restarts (start it with other flags to change the defaults).

const SIZES = [320, 416, 512, 640];

function Toggle({ label, hint, checked, onChange, disabled }) {
  return (
    <label className={`toggle${disabled ? " off" : ""}`}>
      <input type="checkbox" role="switch" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-text"><b>{label}</b>{hint ? <span className="small muted">{hint}</span> : null}</span>
    </label>
  );
}

function Section({ title, note, children }) {
  return (
    <section className="sheet settings-group">
      <div className="sheet-head"><h2>{title}</h2></div>
      {note ? <p className="small muted">{note}</p> : null}
      <div className="settings-rows">{children}</div>
    </section>
  );
}

function useSettings() {
  const [s, setS] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);
  useEffect(() => { api("/api/settings").then(setS).catch((e) => setError(e.message)); }, []);
  const save = async (patch) => {
    setS((old) => ({ ...old, ...patch }));               // show the change straight away
    try {
      setS(await api("/api/settings", { method: "PATCH", body: patch }));
      setError(null); setSaved(Date.now());
    } catch (e) { setError(e.message); api("/api/settings").then(setS).catch(() => {}); }
  };
  return { s, error, saved, save };
}

function Detection({ s, save }) {
  const [conf, setConf] = useState(s.confidence);
  const [models, setModels] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  useEffect(() => setConf(s.confidence), [s.confidence]);
  const loadModels = () => api("/api/models").then(setModels).catch((e) => setMsg(e.message));
  useEffect(() => { loadModels(); }, []);

  const onConf = (v) => {
    setConf(v);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => save({ confidence: v }), 400);
  };
  const pickModel = async (name) => {
    setBusy(true); setMsg("Loading the model…");
    try { await api("/api/models/select", { method: "POST", body: { name } }); setMsg(`Now using ${name}.`); }
    catch (e) { setMsg(e.message); }
    await loadModels(); setBusy(false);
  };
  const reload = async () => {
    setBusy(true);
    try { await api("/api/models/behaviour/reload", { method: "POST" }); setMsg("Behaviour classifier loaded again."); }
    catch (e) { setMsg(e.message); }
    await loadModels(); setBusy(false);
  };
  const met = models?.current_info?.metrics;
  const b = models?.behaviour;
  const sizes = SIZES.includes(s.imgsz) ? SIZES : [...SIZES, s.imgsz].sort((x, y) => x - y);

  return (
    <Section title="Detection" note="How carefully DogWatch looks at each frame.">
      <div className="setting">
        <label htmlFor="conf"><b>Confidence</b><span className="small muted">Lower finds more dogs but also more mistakes. 0.5 is a good start.</span></label>
        <div className="row slider">
          <input id="conf" type="range" min="0.05" max="0.95" step="0.05" value={conf} onChange={(e) => onConf(Number(e.target.value))} />
          <output htmlFor="conf" className="num">{conf.toFixed(2)}</output>
        </div>
      </div>
      <div className="setting">
        <label htmlFor="imgsz"><b>Image size</b><span className="small muted">Bigger sees small, far-away dogs but is slower.</span></label>
        <select id="imgsz" value={s.imgsz} onChange={(e) => save({ imgsz: Number(e.target.value) })}>
          {sizes.map((n) => <option key={n} value={n}>{n} px</option>)}
        </select>
      </div>
      <div className="setting">
        <label htmlFor="model"><b>Detector model</b>
          <span className="small muted">{met
            ? `Test results: ${Object.entries(met).filter(([, v]) => typeof v !== "object").slice(0, 4).map(([k, v]) => `${k} ${v}`).join(", ")}`
            : "No test results saved for this model yet."}</span></label>
        {models ? (
          <select id="model" value={models.current} disabled={busy} onChange={(e) => pickModel(e.target.value)}>
            {models.available.map((m) => <option key={m.name} value={m.name}>{m.name} ({m.size_mb} MB)</option>)}
            {!models.available.some((m) => m.current) ? <option value={models.current}>{models.current}</option> : null}
          </select>
        ) : <span className="muted small">Loading…</span>}
      </div>
      <Toggle label="Use the behaviour classifier"
        hint={!b ? "Loading…" : b.loaded
          ? `A trained model tells resting, walking and running apart (knows ${b.labels.join(", ")}${b.metrics ? `, accuracy ${b.metrics.accuracy}` : ""}).`
          : "Not trained yet, so activity comes from how fast a dog moves. See training/behaviour."}
        checked={s.use_behaviour_model && b?.loaded} disabled={!b?.loaded || busy}
        onChange={async (v) => { await save({ use_behaviour_model: v }); loadModels(); }} />
      {b?.exists ? <p><button className="btn quiet small" onClick={reload} disabled={busy}>Load the classifier again</button>
        <span className="small muted"> after training a new one</span></p> : null}
      {msg ? <p className="small" role="status">{msg}</p> : null}
    </Section>
  );
}

function Storage() {
  const [st, setSt] = useState(null);
  const [days, setDays] = useState(30);
  const [plan, setPlan] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api("/api/storage").then(setSt).catch((e) => setMsg(e.message));
  useEffect(() => { load(); }, []);

  const check = async () => {
    setBusy(true); setMsg(null); setPlan(null);
    try {
      const p = await api("/api/storage/cleanup", { method: "POST", body: { days, dry_run: true } });
      if (!p.dogs && !p.events && !p.files && !p.observations) setMsg(`Nothing is older than ${plural(days, "day")}.`);
      else setPlan(p);
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const run = async () => {
    setBusy(true);
    try {
      const r = await api("/api/storage/cleanup", { method: "POST", body: { days, dry_run: false } });
      setMsg(`Deleted ${r.dogs} dogs, ${r.events} events and ${r.files} files. ${r.freed_mb} MB freed.`);
      setPlan(null); load();
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };

  return (
    <Section title="Storage" note="Zones, cameras and your own videos are never deleted here.">
      {st ? (
        <>
          <div className="figures compact">
            <div><b>{st.database_mb} MB</b>database</div>
            <div><b>{st.alert_files.mb} MB</b>alert photos and clips</div>
            <div><b>{st.dog_photos.mb} MB</b>dog photos</div>
            <div><b>{st.disk_free_gb} GB</b>disk free</div>
          </div>
          <p className="small muted">{st.rows.dogs} dogs, {st.rows.observations.toLocaleString()} positions and {st.rows.events} events saved.
            {st.keep_days != null ? ` Data older than ${st.keep_days} days is deleted automatically.` : ""}</p>
        </>
      ) : <p className="muted small">Loading…</p>}
      <div className="setting">
        <label htmlFor="days"><b>Delete old data</b><span className="small muted">Dogs, positions and alerts older than this, with their photos and clips.</span></label>
        <div className="row">
          <input id="days" type="number" min="1" step="1" value={days} style={{ width: "6em" }}
            onChange={(e) => { setDays(Math.max(1, Number(e.target.value) || 1)); setPlan(null); }} />
          <span>days</span>
          <button className="btn quiet small" onClick={check} disabled={busy}>Check what would go</button>
          {busy && !plan ? <span className="small muted" role="status">Checking…</span> : null}
        </div>
      </div>
      {plan ? (
        <div className="confirm" role="alert">
          <p>Delete <b>{plan.dogs} dogs</b>, {plan.observations.toLocaleString()} positions, {plan.events} events and {plan.files} files
            ({plan.freed_mb} MB) older than {plural(days, "day")}? This can't be undone.</p>
          <div className="row">
            <button className="btn danger small" onClick={run} disabled={busy}>Delete them</button>
            <button className="btn quiet small" onClick={() => setPlan(null)} disabled={busy}>Keep them</button>
          </div>
        </div>
      ) : null}
      {msg ? <p className="small" role="status">{msg}</p> : null}
    </Section>
  );
}

export default function Settings() {
  const navigate = useNavigate();
  const { s, error, saved, save } = useSettings();
  if (!s) {
    return <div className="sheet empty"><h2>{error ? "Can't load the settings" : "Loading…"}</h2>{error ? <p>{error}</p> : null}</div>;
  }
  return (
    <div className="settings">
      <p className="muted settings-note">
        Changes apply straight away and last until the server restarts.
        {saved ? <span className="saved" key={saved} role="status"> Saved.</span> : null}
      </p>
      {error ? <p className="error" role="alert">{error}</p> : null}

      <div className="settings-grid">
        <Section title="Alerts" note="What counts as worth telling you about.">
          <Toggle label="A dog walks into a zone" hint="Draw zones on the Live page." checked={s.alert_zone} onChange={(v) => save({ alert_zone: v })} />
          <Toggle label="A dog runs towards a person" checked={s.alert_approach} onChange={(v) => save({ alert_approach: v })} />
          <Toggle label="Several dogs gather" checked={s.alert_pack} onChange={(v) => save({ alert_pack: v })} />
          <div className={`setting${s.alert_pack ? "" : " off"}`}>
            <label htmlFor="pack"><b>How many make a group</b></label>
            <input id="pack" type="number" min="2" max="20" value={s.pack_size} disabled={!s.alert_pack} style={{ width: "5em" }}
              onChange={(e) => { const n = Math.round(Number(e.target.value)); if (n >= 2 && n <= 20) save({ pack_size: n }); }} />
          </div>
          <Toggle label="Save a short clip with each alert" hint="A few seconds of video around the moment." checked={s.alert_clips} onChange={(v) => save({ alert_clips: v })} />
        </Section>

        <Detection s={s} save={save} />

        <Section title="Live picture" note="What is drawn on top of the video.">
          <Toggle label="Boxes around people" checked={s.draw_people} onChange={(v) => save({ draw_people: v })} />
          <Toggle label="Trails behind dogs" hint="Where each dog walked in the last few seconds." checked={s.draw_trails} onChange={(v) => save({ draw_trails: v })} />
          <Toggle label="Zone outlines" checked={s.draw_zones} onChange={(v) => save({ draw_zones: v })} />
        </Section>

        <Storage />

        <Section title="Download the data" note="Spreadsheet files (CSV) for your own analysis.">
          <div className="row wrap">
            <a className="btn quiet small" href={withToken("/api/export/dogs.csv")}>Dogs</a>
            <a className="btn quiet small" href={withToken("/api/export/observations.csv")}>Positions</a>
            <a className="btn quiet small" href={withToken("/api/export/events.csv")}>Alerts and events</a>
          </div>
          <p className="small muted">Building something on top? The <a href={withToken("/docs")} target="_blank" rel="noreferrer">API documentation</a> lists every endpoint.</p>
        </Section>

        <Section title="Guided setup" note="The first-run steps: add a camera, see a dog, mark a zone, a short tour.">
          <p><button className="btn quiet small" onClick={() => { resetSetup(); navigate("/welcome"); }}>Restart setup</button></p>
        </Section>
      </div>
    </div>
  );
}
