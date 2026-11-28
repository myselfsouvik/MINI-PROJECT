import { Link, useNavigate } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { TOUR } from "../components/Tour.jsx";
import { withToken } from "../lib/api.js";
import { resetSetup } from "../lib/setup.js";

// Where things are, and what to try when something doesn't work.

const MORE = [
  { icon: "cameras", title: "Cameras", to: "/cameras", text: "Add a laptop webcam, a phone, a video file or the demo video. Remove cameras and see recordings." },
  { icon: "settings", title: "Settings", to: "/settings", text: "Which alerts to send, how carefully to look, what to draw on the video, and deleting old data." },
  { icon: "present", title: "Presentation view", to: "/present", text: "A full-screen view for showing DogWatch to a class: the live picture and big numbers." },
];

const TIPS = [
  ["No dog is found", "Make sure the whole dog is in the picture and not too small. Lower the confidence in Settings, or try the demo video to check everything else works."],
  ["The video is black or frozen", "Another app may be using the webcam. Close it, then remove the camera and add it again on the Cameras page."],
  ["A phone won't connect", "The phone and the laptop must be on the same Wi-Fi. Start the server with the phone option, then scan the QR code on the Cameras page."],
  ["Too many alerts", "Turn off the alert types you don't need in Settings, or make zones smaller so they cover only the place you care about."],
  ["It is slow", "Choose a smaller image size in Settings. 320 or 416 px is much faster on a laptop without a graphics card."],
];

export default function Help() {
  const navigate = useNavigate();
  return (
    <div className="help">
      <section className="sheet help-start">
        <div>
          <h2>New here?</h2>
          <p className="muted">The guided setup adds a camera, checks a dog is seen and marks a first zone. The tour shows where everything is.</p>
        </div>
        <div className="row wrap">
          <Link className="btn primary" to="/welcome?step=tour">Take the tour</Link>
          <button className="btn quiet" onClick={() => { resetSetup(); navigate("/welcome"); }}>Restart setup</button>
        </div>
      </section>

      <section aria-labelledby="pages-h">
        <h2 id="pages-h" className="help-h">What each page is for</h2>
        <ul className="page-list">
          {[...TOUR, ...MORE].map((p) => (
            <li key={p.title}>
              <Link to={p.to}><span className="tour-icon"><Icon name={p.icon} /></span>
                <span><b>{p.title}</b><span className="small muted">{p.text}</span></span></Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="sheet" aria-labelledby="tips-h">
        <h2 id="tips-h">When something isn't working</h2>
        <dl className="tips-list">
          {TIPS.map(([q, a]) => <div key={q}><dt>{q}</dt><dd className="muted">{a}</dd></div>)}
        </dl>
      </section>

      <p className="small muted">
        The <a href={withToken("/console")}>classic console</a> is the older one-page version of this app. It still works if this one doesn't load.
      </p>
    </div>
  );
}
