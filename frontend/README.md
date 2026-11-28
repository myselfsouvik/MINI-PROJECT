# frontend

The DogWatch dashboard: a React app with one page per job and a guided first-run setup.
The backend serves the built app at `http://127.0.0.1:8000/`. The older one-page console stays at `/console` as a fallback.

## Pages

| Address | What it is for |
|---|---|
| `/` Overview | What is happening right now: one camera live, the dogs in view, today's numbers, the latest alerts |
| `/live` | One camera, big. Dogs on camera now, draw zones on the picture, record clips |
| `/alerts` | Alerts only (zone, running towards a person, dogs gathering), filter by type, photo and clip |
| `/dogs`, `/dogs/:id` | Every dog with a photo; a profile per dog with its path, time spent resting/walking/running and events |
| `/activity` | Charts for the last hour, day or week: when dogs were around, where in the picture, how fast; session report |
| `/bites` | What the public animal-bite records say about dogs |
| `/cameras` | Add a laptop webcam, a phone (QR code), a video file or the demo video; remove cameras; recordings |
| `/settings` | Alert switches, detection confidence, image size, model, what is drawn on the video, storage clean-up, CSV export |
| `/help` | The tour, restart setup, what each page is for, fixes for common problems |
| `/welcome` | Guided setup: add a camera, see a dog, mark a zone, a short tour |
| `/present` | Presentation view for a class or demo: full-screen video, big numbers, new alerts pop in |

**Guided setup.** It opens by itself when a browser visits `/` with no cameras connected and hasn't finished the setup before
(remembered in that browser's `localStorage`). Every step can be skipped. Settings and Help have a "Restart setup" button.

**Presentation view.** Open it from the sidebar ("Presentation view") or at `/present`. "Full screen" hides the browser; the
buttons fade away when the mouse is still. With several cameras, pick one in the top right or use `/present?camera=cam2`.

## Running it

You don't need Node.js to *use* the dashboard: the built app is kept in git (`frontend/dist`) and the server serves it.
Node.js is only needed to change it:

```bash
python -m backend.server --demo     # the backend on :8000, with the demo video
cd frontend
npm install
npm run dev                         # http://localhost:5173, changes show up straight away
npm test                            # unit tests (Vitest)
npm run build                       # writes frontend/dist (commit it too), served on the next page load
```

`npm run build` also writes `dist/source.sha256`, a fingerprint of the code it was built from. A test
(`tests/test_build_frontend.py`) fails when `frontend/` changed but `dist` wasn't rebuilt, and `start.bat` rebuilds it
by itself on computers that have Node.js.

`vite.config.js` forwards `/api`, `/media` and `/ws` to the backend on port 8000, so the code only uses relative URLs.

## How it is put together

```
src/
  main.jsx, App.jsx        routes; Welcome and Present are full-screen, the rest share the sidebar layout
  tokens.css, app.css      colours (light and dark), type, every component's styles
  hooks/live.jsx           one WebSocket for the whole app: live dogs per camera, new events, unseen alerts; usePoll()
  lib/api.js               fetch with the access token, withToken() for <img>/<video>/links
  lib/format.js            durations, times, activity and alert names
  lib/charts.js            Chart.js theme read from the CSS colours
  lib/timeline.js          time ranges and filling quiet gaps in the activity timeline
  lib/zoneGeometry.js      clicks on the video -> zone corners (handles letterboxing)
  lib/setup.js             whether the guided setup should open
  components/              Layout (sidebar, top bar, phone tab bar), AddCamera, ZoneDrawer, Tour, shared bits
  pages/                   one file per page
  tests/                   Vitest unit tests for lib/
```

- **Other devices** (a phone, a teammate's laptop) open the dashboard with `?token=...` (the server prints it). `lib/api.js`
  keeps it for the tab and sends it as `X-Access-Token`, or as `?token=` on images, video and the WebSocket.
- **Charts** load only when the Activity or Bites page is opened, so the first page stays small.
- **Settings** change the running server straight away and reset when it restarts (start flags set the defaults).
- **API reference:** [backend/README.md](../backend/README.md) and the live docs at `http://127.0.0.1:8000/docs`.
