// Adding a camera: laptop webcam, phone, video file or the demo video.
// Used by the Cameras page and by the guided setup. onAdded(source) gets the new camera.
import { useEffect, useRef, useState } from "react";
import { api, withToken } from "../lib/api.js";
import { useLive } from "../hooks/live.jsx";

const CHOICES = [
  { key: "webcam", title: "Laptop webcam", text: "The camera built into this laptop, or one plugged in by USB." },
  { key: "phone", title: "Phone", text: "Scan a code with the phone. Its camera streams over Wi-Fi." },
  { key: "file", title: "Video file", text: "A clip you recorded of street dogs. Plays like a live camera." },
  { key: "demo", title: "Demo video", text: "Three dogs resting, walking and running. Good for trying things out." },
];

export default function AddCamera({ onAdded, initial = null, compact = false }) {
  const [choice, setChoice] = useState(initial);
  const { refreshSources } = useLive();
  const done = async (source) => { await refreshSources(); onAdded?.(source); };

  return (
    <div className="add-camera">
      <div className={`choices${compact ? " compact" : ""}`} role="group" aria-label="Kind of camera">
        {CHOICES.map((c) => (
          <button key={c.key} type="button" className="choice" aria-pressed={choice === c.key} onClick={() => setChoice(c.key)}>
            <b>{c.title}</b><span>{c.text}</span>
          </button>
        ))}
      </div>
      {choice === "webcam" ? <Webcam onAdded={done} /> : null}
      {choice === "phone" ? <Phone onAdded={done} /> : null}
      {choice === "file" ? <VideoFile onAdded={done} /> : null}
      {choice === "demo" ? <Demo onAdded={done} /> : null}
    </div>
  );
}

function useAdding() {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const run = async (label, fn) => {
    setBusy(label); setError(null);
    try { return await fn(); } catch (e) { setError(e.message); return null; } finally { setBusy(null); }
  };
  return { busy, error, run, setError };
}

function Status({ busy, error }) {
  return (
    <p className="add-status" aria-live="polite">
      {busy ? <span className="muted">{busy}</span> : error ? <span className="error">{error}</span> : null}
    </p>
  );
}

function Webcam({ onAdded }) {
  const [cams, setCams] = useState(null);
  const { busy, error, run } = useAdding();
  const scan = () => run("Looking for webcams…", async () => setCams(await api("/api/cameras/local")));
  useEffect(() => { scan(); }, []);                          // eslint-disable-line react-hooks/exhaustive-deps
  const add = (c) => run(`Opening webcam ${c.index}…`, async () => {
    const s = await api("/api/sources", { method: "POST", body: { source: String(c.index), name: c.index ? `Webcam ${c.index}` : "Laptop webcam" } });
    onAdded(s);
  });
  return (
    <div className="add-panel">
      <h3>Pick a webcam</h3>
      {cams?.length ? (
        <div className="row">
          {cams.map((c) => (
            <button key={c.index} type="button" className="btn quiet" disabled={c.in_use || !!busy} onClick={() => add(c)}>
              {c.index ? `Webcam ${c.index}` : "Built-in webcam"}{c.width ? ` (${c.width}×${c.height})` : ""}{c.in_use ? ", already added" : ""}
            </button>
          ))}
          <button type="button" className="link-btn" onClick={scan} disabled={!!busy}>Look again</button>
        </div>
      ) : cams ? (
        <p>No webcam found. Plug one in (or close apps like Zoom that may be using it) and <button type="button" className="link-btn" onClick={scan}>look again</button>.</p>
      ) : null}
      <Status busy={busy} error={error} />
    </div>
  );
}

function Phone({ onAdded }) {
  const [info, setInfo] = useState(null);
  const [ip, setIp] = useState("");
  const [app, setApp] = useState("ipwebcam");
  const { busy, error, run } = useAdding();
  const { sources } = useLive();
  const phones = (sources || []).filter((s) => s.kind === "phone").map((s) => s.id).join(",");
  const first = useRef(phones);

  useEffect(() => { run("Getting the phone link…", async () => setInfo(await api("/api/phone-link"))); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A phone that connects through its browser appears as a new camera: hand it over.
  useEffect(() => {
    const before = new Set(first.current.split(",").filter(Boolean));
    const added = (sources || []).find((s) => s.kind === "phone" && !before.has(s.id));
    if (added) onAdded(added);
  }, [phones]);                                              // eslint-disable-line react-hooks/exhaustive-deps

  const addApp = (e) => {
    e.preventDefault();
    run("Connecting to the phone…", async () => onAdded(await api("/api/sources/phone", { method: "POST", body: { ip: ip.trim(), app } })));
  };

  return (
    <div className="add-panel">
      <h3>Connect a phone</h3>
      {info && info.enabled && info.urls.length ? (
        <div className="qr">
          <img src={withToken(info.qr_url)} alt="QR code that opens the phone camera page" width="168" height="168" />
          <div>
            <ol>
              <li>Join the phone to the same Wi-Fi as this laptop.</li>
              <li>Scan the code with the phone camera.</li>
              <li>Accept the security warning. The laptop uses its own certificate.</li>
              <li>Tap <b>Start camera</b>. It shows up here by itself.</li>
            </ol>
            <p className="muted small">Or type <code>{info.urls[0]}</code> in the phone browser.</p>
          </div>
        </div>
      ) : info && info.enabled ? (
        <p className="error">This laptop has no Wi-Fi address. Connect it to Wi-Fi or a phone hotspot, then reload.</p>
      ) : info ? (
        <p className="muted">{info.hint} (<code>start.bat</code> does this already.)</p>
      ) : null}
      <details className="more">
        <summary>Use a camera app instead (IP Webcam, DroidCam)</summary>
        <form className="row" onSubmit={addApp}>
          <label className="sr-only" htmlFor="phone-ip">Phone IP address</label>
          <input id="phone-ip" value={ip} onChange={(e) => setIp(e.target.value)} placeholder="Phone IP, e.g. 192.168.1.5" required />
          <label className="sr-only" htmlFor="phone-app">App</label>
          <select id="phone-app" value={app} onChange={(e) => setApp(e.target.value)}>
            <option value="ipwebcam">IP Webcam</option>
            <option value="droidcam">DroidCam</option>
          </select>
          <button className="btn" disabled={!!busy}>Connect</button>
        </form>
      </details>
      <Status busy={busy} error={error} />
    </div>
  );
}

function VideoFile({ onAdded }) {
  const [videos, setVideos] = useState(null);
  const { busy, error, run } = useAdding();
  const input = useRef(null);
  useEffect(() => { api("/api/uploads").then(setVideos).catch(() => setVideos([])); }, []);

  const upload = (file) => run(`Uploading ${file.name}…`, async () => {
    const r = await api(`/api/uploads?start=1&filename=${encodeURIComponent(file.name)}`, { method: "POST", body: file, raw: true });
    onAdded({ id: r.source_id, name: file.name });
  });
  const play = (v) => run(`Opening ${v.name}…`, async () => {
    onAdded(await api("/api/sources", { method: "POST", body: { source: v.source, name: v.name } }));
  });

  return (
    <div className="add-panel">
      <h3>Play a video as a camera</h3>
      <div className="row">
        <button type="button" className="btn" disabled={!!busy} onClick={() => input.current?.click()}>Upload a video…</button>
        <span className="muted small">MP4, AVI, MOV or MKV. It plays on a loop.</span>
        <input ref={input} type="file" accept="video/*" hidden
               onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} />
      </div>
      {videos?.length ? (
        <>
          <p className="small muted" style={{ marginTop: 12 }}>Or pick one already on this laptop:</p>
          <ul className="file-list">
            {videos.slice(0, 8).map((v) => (
              <li key={v.source}>
                <span><b>{v.name}</b> <span className="muted small">{v.size_mb} MB</span></span>
                <button type="button" className="btn quiet small" disabled={!!busy} onClick={() => play(v)}>Play</button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <Status busy={busy} error={error} />
    </div>
  );
}

function Demo({ onAdded }) {
  const { busy, error, run } = useAdding();
  const start = () => run("Starting the demo video (the first time it is made, a few seconds)…",
    async () => onAdded(await api("/api/sources/demo", { method: "POST" })));
  return (
    <div className="add-panel">
      <h3>Demo video</h3>
      <p>A short made-up street with three dogs: one resting, one walking and one running. It has a zone on the right,
        so you also see zone and pack alerts.</p>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn primary" disabled={!!busy} onClick={start}>Start the demo video</button>
      </div>
      <Status busy={busy} error={error} />
    </div>
  );
}
