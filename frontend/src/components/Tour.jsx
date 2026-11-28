// A short tour of the main pages: one card each, Back / Next. Last step of the setup,
// and opened again from Help.
import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

export const TOUR = [
  { icon: "overview", title: "Overview", to: "/",
    text: "What is happening right now: one camera live, the dogs in view, today's numbers and the latest alerts. Start here." },
  { icon: "live", title: "Live", to: "/live",
    text: "One camera, big. Draw zones on the picture (a school gate, a shop front) and record clips." },
  { icon: "alerts", title: "Alerts", to: "/alerts",
    text: "A dog walked into a zone, ran towards a person, or several gathered. Each alert has a photo and a short clip. The bell counts new ones." },
  { icon: "dogs", title: "Dogs", to: "/dogs",
    text: "Every dog the cameras followed, with a photo. Open one to see where it went and how it spent its time." },
  { icon: "activity", title: "Activity and Bites data", to: "/activity",
    text: "Charts of when dogs are around and where they gather, plus what public bite records say about dogs. Download a report for the class." },
];

export default function Tour({ onDone, doneLabel = "Finish" }) {
  const [i, setI] = useState(0);
  const heading = useRef(null);
  const card = TOUR[i];
  const last = i === TOUR.length - 1;
  useEffect(() => { heading.current?.focus(); }, [i]);

  return (
    <div className="tour">
      <div className="tour-card" aria-live="polite">
        <span className="tour-icon"><Icon name={card.icon} /></span>
        <p className="small muted">Page {i + 1} of {TOUR.length}</p>
        <h3 ref={heading} tabIndex={-1}>{card.title}</h3>
        <p>{card.text}</p>
      </div>
      <div className="tour-dots" aria-hidden="true">
        {TOUR.map((t, j) => <i key={t.title} className={j === i ? "on" : ""} />)}
      </div>
      <div className="row tour-nav">
        <button className="btn quiet" onClick={() => setI(i - 1)} disabled={i === 0}>Back</button>
        {last
          ? <button className="btn primary" onClick={onDone}>{doneLabel}</button>
          : <button className="btn primary" onClick={() => setI(i + 1)}>Next</button>}
      </div>
    </div>
  );
}
