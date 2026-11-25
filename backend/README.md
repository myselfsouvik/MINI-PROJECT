# backend

FastAPI server, camera manager, inference worker and SQLite storage. Owner: Jagrit.

## Run it

```bash
python -m backend.server --source 0                 # laptop webcam
python -m backend.server --source 1                 # phone over USB (DroidCam / Iriun)
python -m backend.server --source recordings/clip.mp4
python -m backend.server                            # start empty, add cameras from the page
python -m backend.server --phone                    # + phones connect from their browser via QR code
```

Open **http://127.0.0.1:8000** for the test console and **http://127.0.0.1:8000/docs** for interactive API docs.

Options: `--phone` (HTTPS server on port 8443 for phones, see [docs/PHONE_CAMERA.md](../docs/PHONE_CAMERA.md)), `--host 0.0.0.0` (reachable from other devices on the Wi-Fi), `--port`, `--model` (swap in a fine-tuned model), `--conf`, `--max-fps` (save CPU).

## Files

| File | What it does |
|---|---|
| `cameras.py` | `CameraSource`: webcam / USB phone / Wi-Fi phone / video file, always returns the newest frame, auto-reconnects |
| `behaviour.py` | Per-dog speed in **box heights per second** (independent of distance and resolution) and RESTING / WALKING / RUNNING labels |
| `pipeline.py` | One thread per camera: YOLO detect + ByteTrack → behaviour → alerts → database, draws the annotated frame |
| `alerts.py` | Alert rules: dog enters a zone, running dog closing in on a person, 3+ dogs together |
| `db.py` | SQLite tables `dogs`, `observations` (1 per dog per second), `events`, `zones` |
| `app.py` | FastAPI routes, MJPEG stream, WebSocket |
| `server.py` | Command-line entry point |
| `static/index.html` | Temporary test console (the real dashboard is `frontend/`) |
| `static/phone.html` | Page the phone opens: streams its camera to the laptop |
| `phone.py` | Wi-Fi address, self-signed HTTPS certificate, QR code |
| `security.py` | Access token and checks on what can be opened as a camera |
| `camera_test.py` | Quick camera check without the server |

Runtime data (database + dog snapshots) is written to `backend/storage/` and is not committed.

## API for the frontend

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{ok, sources, model}` |
| GET | `/api/cameras/local` | webcams on this computer `[{index, width, height, in_use}]` |
| GET | `/api/sources` | cameras being watched, with status, FPS, dogs visible, `stream_url` |
| POST | `/api/sources` | body `{source, name?, loop?}`: add a webcam number, URL or video file |
| POST | `/api/sources/phone` | body `{ip, app: "ipwebcam" \| "droidcam", port?, name?}` |
| DELETE | `/api/sources/{id}` | stop watching |
| GET | `/api/sources/{id}/stream.mjpg` | live annotated video. Use as `<img src="…">`; `?raw=1` for the clean frame |
| GET | `/api/sources/{id}/snapshot.jpg` | one frame |
| GET | `/api/sources/{id}/live` | dogs visible now: `dog_id, box, activity, speed, confidence, trail, zones` |
| GET | `/api/dogs?limit=&source_id=&min_seconds=` | dogs seen, newest first, with `snapshot_url` and seconds per activity |
| GET | `/api/dogs/{id}` | one dog + all its observations (for charts) |
| GET | `/api/events?limit=&type=&after_id=` | `source_added`, `dog_appeared`, `dog_left`, … |
| GET | `/api/stats/activity?minutes=60` | seconds spent RESTING / WALKING / RUNNING |
| GET | `/api/stats/timeline?minutes=60&bucket=60&source_id=` | `buckets: [{start, RESTING, WALKING, RUNNING}]` dog-seconds per time bucket (stacked chart) |
| GET | `/api/stats/speeds?minutes=60&bin_width=0.25&max_speed=4&source_id=` | `{edges, counts}` speed histogram; last bin = max_speed and above |
| GET | `/api/stats/heatmap?minutes=60&cols=16&rows=9&source_id=` | `{grid, max}` dog-seconds per cell over the camera view (row 0 = top) |
| GET | `/api/stats/summary?minutes=1440` | `{dogs_seen, alerts, events: {type: n}, busiest_hour, activity_seconds}` for dashboard cards |
| GET | `/api/uploads` | videos in `recordings/`, each with a `source` to pass to `POST /api/sources` |
| POST | `/api/uploads?filename=clip.mp4&start=1` | body = the video file itself (not a form). `start=1` also starts watching it |
| GET | `/api/models` | `{current, current_info, available: [{name, size_mb, metrics, current}]}` |
| POST | `/api/models/select` | body `{name}`: switch every camera to another model from `models/` |
| GET / PATCH | `/api/settings` | `confidence`, `max_fps`, `draw_people`, `draw_trails`, `draw_zones`, `alert_zone`, `alert_approach`, `alert_pack`, `pack_size` |
| GET | `/api/sources/{id}/zones` | zones drawn on this camera `[{id, name, points}]` |
| POST | `/api/sources/{id}/zones` | body `{name, points: [[x, y], …]}`: 3–20 corners as fractions of the frame (0–1) |
| DELETE | `/api/zones/{zone_id}` | remove a zone |
| GET | `/api/alerts?limit=&after_id=` | only alerts, newest first, each with `snapshot_url` (the frame when it happened) |
| WS | `/ws/live` | every 0.5 s: `{ts, sources: {id: live state}, events: [new events]}` |
| GET | `/media/dogs/dog_<id>.jpg` | saved dog photo |
| GET | `/api/phone-link` | `{enabled, urls, qr_url, phones_connected}` |
| GET | `/api/phone-link/qr.svg` | QR code image for the phone link |
| WS | `/ws/phone?token=&name=` | phone sends JPEG frames (binary); server answers each with `{type: "ack", dogs, people}` |

CORS is open for the Vite dev server on `http://localhost:5173`.

## Access and safety

- **This computer** (127.0.0.1) can always use everything.
- **Other devices** (phones, teammates' laptops on the Wi-Fi) need the access token the server prints when started with `--host 0.0.0.0`. Open `http://<laptop-IP>:8000/?token=<token>`, or send it as an `X-Access-Token` header. Without `--host 0.0.0.0` the server isn't reachable from other devices at all.
- **Video files** added from the page must be inside `recordings/` (change with `--media-dir`). Files given with `--source` on the command line can be anywhere.
- **Stream URLs** can't point at link-local or multicast addresses, and other devices can't point a "camera" at the laptop itself. This stops the camera feature being misused to read files or reach other services on the laptop.

## Alerts

| Type | When |
|---|---|
| `zone_entered` | A dog's feet (bottom centre of its box) are inside a zone for 3 frames in a row. Once per dog per zone every 30 s. |
| `dog_running_at_person` | A RUNNING dog gets at least 1 body length closer to a person within about 1 s and is within 4 body lengths. Once per dog every 20 s. |
| `dog_pack` | 3 or more dogs in view at once (`pack_size`). At most once a minute. |

Alerts are saved as events with a photo in `backend/storage/alerts/`. Zones are stored per camera (webcam number, file path, stream URL or phone name), so they come back after a restart. These are simple, explainable rules on top of the detector; we don't claim to detect "aggression".

To draw a zone on the test page: pick a camera, press **Draw a zone**, click the corners on the video, name it and save.

## Models

Put weights files (`.pt` or `.onnx`) in `models/` and pick one on the test page or with `POST /api/models/select`. The server reads the class names from the model, so both the stock COCO model (dog = class 16) and our fine-tuned model (only "dog", class 0) work without code changes. Switching model restarts tracking, so dogs on screen get new IDs.

To show test results for a model, save them next to it as `models/<name>.json`, e.g. `models/dog_v1.json`:

```json
{"mAP50": 0.86, "mAP50-95": 0.61, "precision": 0.9, "recall": 0.82, "test_images": 240}
```

## Notes

- Dog positions in `observations` are fractions of the frame (0–1), so heat maps work for any camera resolution.
- A looping video makes the dog "jump" back to the start, so it gets a new ID each loop. That's expected.
- Activity thresholds (`REST_BELOW`, `RUN_FROM` in `behaviour.py`) are first guesses; tune them on real footage. The trained behaviour classifier will replace them later.

See [PLAN.md](../PLAN.md) for the full roadmap.
