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
| `pipeline.py` | One thread per camera: YOLO detect + ByteTrack → behaviour → database, draws the annotated frame |
| `db.py` | SQLite tables `dogs`, `observations` (1 per dog per second), `events` |
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
| GET | `/api/sources/{id}/live` | dogs visible now: `dog_id, box, activity, speed, confidence, trail` |
| GET | `/api/dogs?limit=&source_id=&min_seconds=` | dogs seen, newest first, with `snapshot_url` and seconds per activity |
| GET | `/api/dogs/{id}` | one dog + all its observations (for charts) |
| GET | `/api/events?limit=&type=&after_id=` | `source_added`, `dog_appeared`, `dog_left`, … |
| GET | `/api/stats/activity?minutes=60` | seconds spent RESTING / WALKING / RUNNING |
| GET / PATCH | `/api/settings` | `confidence`, `max_fps`, `draw_people`, `draw_trails` |
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

## Notes

- A looping video makes the dog "jump" back to the start, so it gets a new ID each loop. That's expected.
- Activity thresholds (`REST_BELOW`, `RUN_FROM` in `behaviour.py`) are first guesses; tune them on real footage. The trained behaviour classifier will replace them later.

See [PLAN.md](../PLAN.md) for the full roadmap.
