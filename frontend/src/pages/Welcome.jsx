import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import AddCamera from "../components/AddCamera.jsx";
import { DogTag, LiveFrame } from "../components/bits.jsx";
import { Logo } from "../components/Icon.jsx";
import Tour from "../components/Tour.jsx";
import ZoneDrawer from "../components/ZoneDrawer.jsx";
import { useLive } from "../hooks/live.jsx";
import { api } from "../lib/api.js";
import { STEPS, markSetupDone } from "../lib/setup.js";

// First-run setup: add a camera, see a dog, mark a zone, a short tour. Every step can be skipped.

const TIPS_AFTER = 20;   // seconds without a dog before we offer help

function StepCamera({ onDone }) {
  const { sources } = useLive();
  return (
    <>
      <h2>Add a camera</h2>
      <p className="lead">Where should DogWatch look for dogs? You can add more cameras later.</p>
      {sources?.length ? (
        <div className="have-cams">
          <p>Already watching: <b>{sources.map((s) => s.name).join(", ")}</b>.</p>
          <button className="btn" onClick={() => onDone(sources[0])}>Use {sources[0].name}</button>
          <p className="small muted">Or add another one:</p>
        </div>
      ) : null}
      <AddCamera compact onAdded={onDone} />
      <p className="small muted" style={{ marginTop: 12 }}>No dog nearby right now? Pick the <b>Demo video</b>.</p>
    </>
  );
}

function StepDog({ camId, onCamera, onDone }) {
  const { live } = useLive();
  const [first, setFirst] = useState(null);
  const [waited, setWaited] = useState(0);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const l = live[camId];

  useEffect(() => { setFirst(null); setWaited(0); }, [camId]);
  useEffect(() => {
    if (!first && l?.dogs?.length) setFirst(l.dogs[0]);
  }, [l, first]);
  useEffect(() => {
    if (first) return undefined;
    const t = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(t);
  }, [first]);

  const lowerConfidence = async () => {
    setBusy("conf");
    try { await api("/api/settings", { method: "PATCH", body: { confidence: 0.35 } }); setMsg("Confidence lowered to 0.35. Change it back in Settings later."); }
    catch (e) { setMsg(e.message); }
    setBusy(null);
  };
  const useDemo = async () => {
    setBusy("demo");
    try { onCamera(await api("/api/sources/demo", { method: "POST" })); setMsg(null); }
    catch (e) { setMsg(e.message); }
    setBusy(null);
  };

  return (
    <>
      <h2>{first ? "DogWatch found a dog" : "Waiting for a dog…"}</h2>
      <p className="lead">
        {first ? "Each dog gets a box, a number and what it is doing: resting, walking or running."
          : "Point the camera at a dog, or hold up a dog photo on a phone. The first one shows up here."}
      </p>
      <div className="stage on-asphalt">
        <LiveFrame sourceId={camId} />
        <div className="readout">
          <span><b>{l ? l.dogs.length : "–"}</b>dogs now</span>
          <span><b>{l ? l.inference_fps : "–"}</b>detections per second</span>
          {!first ? <span><b>{waited}s</b>waiting</span> : null}
        </div>
      </div>
      {first ? (
        <ul className="tags found" aria-live="polite"><DogTag d={first} /></ul>
      ) : waited >= TIPS_AFTER ? (
        <div className="tips sheet" aria-live="polite">
          <h3>No dog yet. Try one of these:</h3>
          <ul>
            <li>Make sure the dog is fully in the picture and not too far away.</li>
            <li><button className="link-btn" onClick={lowerConfidence} disabled={!!busy}>Lower the detection confidence</button> so less certain dogs count too.</li>
            <li><button className="link-btn" onClick={useDemo} disabled={!!busy}>Use the demo video</button>, which always has three dogs.</li>
          </ul>
          {busy === "demo" ? <p className="small muted">Starting the demo video…</p> : null}
          {msg ? <p className="small">{msg}</p> : null}
        </div>
      ) : null}
      <div className="row step-nav">
        <button className="btn primary" onClick={onDone} disabled={!first}>Next: mark a zone</button>
        {!first ? <button className="btn quiet" onClick={onDone}>Skip this step</button> : null}
      </div>
    </>
  );
}

function StepZone({ camId, onDone }) {
  const [saved, setSaved] = useState(null);
  return (
    <>
      <h2>Mark a place to watch</h2>
      <p className="lead">
        Click the corners of an area on the video, like a school gate or a shop front. When a dog walks in,
        you get an alert with a photo. This step is optional.
      </p>
      <div className="stage on-asphalt">
        {saved ? (
          <>
            <LiveFrame sourceId={camId} />
            <p className="stage-note" role="status">Saved “{saved.name}”. It is outlined on the video; alerts start now.</p>
          </>
        ) : (
          <ZoneDrawer sourceId={camId} drawing defaultName="School gate" onSaved={setSaved} onCancel={onDone} />
        )}
      </div>
      <div className="row step-nav">
        {saved ? <button className="btn primary" onClick={onDone}>Next: a quick tour</button>
          : <button className="btn quiet" onClick={onDone}>Skip this step</button>}
      </div>
    </>
  );
}

export default function Welcome() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { sources } = useLive();
  const [step, setStep] = useState(params.get("step") === "tour" ? 3 : 0);
  const [cam, setCam] = useState(null);
  const heading = useRef(null);
  const camId = cam?.id || sources?.[0]?.id;

  useEffect(() => { document.title = "Set up | DogWatch"; }, []);
  useEffect(() => { heading.current?.querySelector("h2")?.focus(); }, [step]);

  const finish = () => { markSetupDone(); navigate("/"); };
  const pickCamera = (s) => { setCam(s); setStep(1); };

  return (
    <div className="welcome">
      <header className="welcome-top">
        <span className="brand-inline"><Logo /><b>DogWatch</b></span>
        <button className="link-btn" onClick={finish}>Skip setup</button>
      </header>

      <ol className="steps" aria-label="Setup steps">
        {STEPS.map((s, i) => (
          <li key={s} className={i === step ? "now" : i < step ? "done" : ""} aria-current={i === step ? "step" : undefined}>
            <span className="num">{i < step ? "✓" : i + 1}</span>{s}
          </li>
        ))}
      </ol>
      <div className="progress" aria-hidden="true"><i style={{ width: `${(100 * (step + 1)) / STEPS.length}%` }} /></div>

      <main className="welcome-body" ref={heading}>
        {step === 0 ? <StepCamera onDone={pickCamera} /> : null}
        {step === 1 && camId ? <StepDog camId={camId} onCamera={setCam} onDone={() => setStep(2)} /> : null}
        {step === 2 && camId ? <StepZone camId={camId} onDone={() => setStep(3)} /> : null}
        {(step === 1 || step === 2) && !camId ? (
          <div className="sheet empty"><h2>No camera yet</h2><p>Add a camera first.</p>
            <button className="btn primary" onClick={() => setStep(0)}>Add a camera</button></div>
        ) : null}
        {step === 3 ? (
          <>
            <h2>Where things are</h2>
            <p className="lead">Five pages, one job each. You can see this again from Help.</p>
            <Tour onDone={finish} doneLabel="Go to Overview" />
          </>
        ) : null}
      </main>
      {step > 0 && step < 3 ? (
        <p className="welcome-back"><button className="link-btn" onClick={() => setStep(step - 1)}>Back</button></p>
      ) : null}
      <p className="small muted welcome-foot">Everything here can be changed later on the <Link to="/cameras" onClick={markSetupDone}>Cameras</Link> and <Link to="/settings" onClick={markSetupDone}>Settings</Link> pages.</p>
    </div>
  );
}
