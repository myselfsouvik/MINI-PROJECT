"""
FastAPI web server for the Street Dog Monitoring System.

Start it with:  python -m backend.server --source 0
Then open http://127.0.0.1:8000 (dashboard) or http://127.0.0.1:8000/docs (API docs).

Pages: "/" is the React dashboard once it's built (frontend/dist), otherwise
the test console. The test console is always at /console, the phone camera
page at /phone.

Main endpoints (all JSON unless noted)

    GET    /api/health
    GET    /api/cameras/local                 webcams on this computer (switches each on briefly)
    GET    /api/sources                       cameras being watched + live status
    POST   /api/sources                       {"source": "0" | url | file, "name": "..."}
    POST   /api/sources/phone                 {"ip": "192.168.1.5", "app": "ipwebcam"}
    DELETE /api/sources/{id}
    GET    /api/sources/{id}/stream.mjpg      live annotated video (use in <img src>)
    GET    /api/sources/{id}/snapshot.jpg     single annotated frame (?raw=1 for clean frame)
    GET    /api/sources/{id}/live             dogs visible right now
    GET    /api/dogs                          dogs seen (newest first)
    GET    /api/dogs/{id}                     one dog + its observations
    GET    /api/events                        dog appeared / left / alerts
    GET    /api/alerts                        only alerts (zone entered, running at person, pack)
    GET    /api/sources/{id}/zones            zones drawn on this camera
    POST   /api/sources/{id}/zones            {"name": "School gate", "points": [[x, y], ...]} (0..1)
    DELETE /api/zones/{zone_id}
    GET    /api/stats/activity                seconds per activity
    GET    /api/stats/timeline                activity over time (for a stacked chart)
    GET    /api/stats/speeds                  speed histogram
    GET    /api/stats/heatmap                 where dogs spend time (grid over the frame)
    GET    /api/stats/summary                 dogs seen, events by type, busiest hour
    GET    /api/uploads  POST /api/uploads    videos in the media folder / upload one
    GET    /api/uploads/{path}                download / play one of those videos
    POST   /api/sources/{id}/recording        start recording a camera   DELETE = stop, GET = status
    GET    /api/models   POST /api/models/select   which model is loaded, switch model
    POST   /api/models/behaviour/reload       load a newly trained behaviour classifier
    GET    /api/settings  PATCH /api/settings detection confidence etc.
    WS     /ws/live                           pushes live status + new events twice a second
    GET    /api/phone-link                    link + QR code for phones (server started with --phone)
    GET    /api/phone-link/qr.svg
    WS     /ws/phone                          a phone's browser sends JPEG frames here (page: /phone)
    GET    /media/...                         saved dog snapshots

Access: requests from this computer are always allowed. Other devices must
send the access token (X-Access-Token header or ?token=), see security.py.
"""

from __future__ import annotations

import asyncio
import csv
import io
import itertools
import json
import mimetypes
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.alerts import ALERT_TYPES
from backend.cameras import PHONE_APPS, CameraSource, PushCameraSource, list_local_cameras, phone_url
from backend.phone import lan_ips, qr_svg
from backend.db import Database
from backend.features import BehaviourModel
from backend.housekeeping import MIN_DAYS, AutoCleaner, cleanup as clean_storage, usage as storage_usage
from backend.insights import InsightsCache
from backend.report import build_report
from backend.pipeline import Pipeline, PipelineSettings, class_ids
from backend.security import check_source, is_local_client, token_ok

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Windows takes file types from the registry, where .js is often "text/plain"; browsers then refuse
# to run the dashboard's scripts. Register the web types ourselves so every laptop serves them right.
for _type, _ext in [("text/javascript", ".js"), ("text/javascript", ".mjs"), ("text/css", ".css"),
                    ("image/svg+xml", ".svg"), ("font/woff2", ".woff2"), ("font/woff", ".woff"),
                    ("application/json", ".json"), ("application/manifest+json", ".webmanifest")]:
    mimetypes.add_type(_type, _ext)


@dataclass
class AppSettings:
    model_path: str = str(ROOT / "models" / "yolo11n.pt")
    storage_dir: str = str(ROOT / "backend" / "storage")
    confidence: float = 0.5
    max_fps: float = 0.0
    imgsz: int = 640               # detector input size (multiple of 32); see backend/benchmark.py
    # Video files added through the API must be inside this folder.
    media_dir: str = str(ROOT / "recordings")
    # Other devices on the network must send this token. None = only this computer.
    access_token: str | None = None
    # Port of the HTTPS server for phones (None = phone browser connection off).
    phone_port: int | None = None
    # Models that can be picked from the dashboard (weights files in this folder).
    models_dir: str = str(ROOT / "models")
    # The built React dashboard (npm run build). Served at "/" when it exists.
    frontend_dir: str = str(ROOT / "frontend" / "dist")
    # Trained behaviour classifier; used if the file exists (see training/behaviour).
    behaviour_model_path: str = str(ROOT / "models" / "behaviour.joblib")
    # Animal-bites dataset for the Insights page.
    bites_csv: str = str(ROOT / "data" / "tabular" / "Health_AnimalBites.csv")
    # Delete dogs, positions, events and their photos/clips older than this many
    # days (checked at start and every hour). None = keep everything.
    keep_days: float | None = None


PUBLIC_PAGES = {"/", "/phone", "/console"}   # pages with no data in them; the API still needs the token
# Paths that hold data. With a built dashboard, everything else is its static
# files (JS/CSS/images), which other devices must be able to load before they
# can send the token with their API requests.
PROTECTED_PREFIXES = ("/api", "/ws", "/media", "/docs", "/redoc", "/openapi.json")
MAX_PHONES = 4
VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
MODEL_TYPES = {".pt", ".onnx"}
MAX_UPLOAD_MB = 500


# ----------------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------------

class AddSource(BaseModel):
    source: str = Field(..., examples=["0", "http://192.168.1.5:8080/video", "clip.mp4"])
    name: str | None = None
    loop: bool = True


class AddPhone(BaseModel):
    ip: str = Field(..., examples=["192.168.1.5"])
    app: str = Field("ipwebcam", examples=list(PHONE_APPS))
    port: int | None = None
    name: str | None = None


class SettingsPatch(BaseModel):
    confidence: float | None = Field(None, ge=0.05, le=0.95)
    max_fps: float | None = Field(None, ge=0)
    imgsz: int | None = Field(None, ge=160, le=1280, multiple_of=32)
    draw_people: bool | None = None
    draw_trails: bool | None = None
    draw_zones: bool | None = None
    alert_zone: bool | None = None
    alert_approach: bool | None = None
    alert_pack: bool | None = None
    pack_size: int | None = Field(None, ge=2, le=20)
    use_behaviour_model: bool | None = None
    alert_clips: bool | None = None


class Cleanup(BaseModel):
    days: float = Field(..., ge=MIN_DAYS, description="delete data older than this many days (at least 1 hour)")
    dry_run: bool = Field(False, description="only report what would be deleted")
    vacuum: bool = Field(False, description="also shrink the database file (takes a few seconds)")


class StartRecording(BaseModel):
    annotated: bool = Field(False, description="record the view with boxes instead of the clean camera image")
    max_minutes: float = Field(10, gt=0, le=60)
    fps: float = Field(15, ge=1, le=30)


class SelectModel(BaseModel):
    name: str = Field(..., examples=["yolo11n.pt"])


class AddZone(BaseModel):
    name: str = Field(..., min_length=1, max_length=40, examples=["School gate"])
    # Corners as fractions of the frame: [0, 0] is top-left, [1, 1] bottom-right.
    points: list[tuple[float, float]] = Field(..., min_length=3, max_length=20,
                                              examples=[[[0.1, 0.6], [0.5, 0.6], [0.5, 1.0], [0.1, 1.0]]])


# ----------------------------------------------------------------------------
# Source manager
# ----------------------------------------------------------------------------

class SourceManager:
    def __init__(self, settings: AppSettings, db: Database):
        self.settings = settings
        self.db = db
        self.storage = Path(settings.storage_dir)
        self.pipeline_settings = PipelineSettings(
            model_path=settings.model_path, confidence=settings.confidence, max_fps=settings.max_fps,
            imgsz=settings.imgsz,
            behaviour_model=BehaviourModel.load_if_exists(settings.behaviour_model_path))
        self.pipelines: dict[str, Pipeline] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, source: str, name: str | None = None, loop: bool = True) -> str:
        cam = CameraSource(source, name=name, loop=loop)   # raises ValueError for bad input
        for p in self.pipelines.values():
            if p.camera.kind == cam.kind and str(p.camera.value) == str(cam.value):
                raise ValueError(f"{cam.name} is already being watched.")
        cam.start()                                          # raises RuntimeError if it can't open
        return self.add_camera(cam)

    def add_camera(self, cam: CameraSource) -> str:
        """Start a detection pipeline for a camera that is already open."""
        with self._lock:
            source_id = f"cam{next(self._ids)}"
        # Each pipeline gets its own copy of the settings object reference so
        # PATCH /api/settings changes all of them at once.
        pipe = Pipeline(source_id, cam, self.pipeline_settings, self.db, self.storage)
        try:
            pipe.start()
        except Exception:
            cam.stop()
            raise
        with self._lock:
            self.pipelines[source_id] = pipe
        self.db.add_event(source_id, "source_added", f"Started watching {cam.name}")
        return source_id

    def get(self, source_id: str) -> Pipeline:
        pipe = self.pipelines.get(source_id)
        if pipe is None:
            raise HTTPException(404, f"No source {source_id!r}")
        return pipe

    def remove(self, source_id: str) -> None:
        with self._lock:
            pipe = self.pipelines.pop(source_id, None)
        if pipe is None:
            raise HTTPException(404, f"No source {source_id!r}")
        pipe.stop()
        self.db.add_event(source_id, "source_removed", f"Stopped watching {pipe.camera.name}")

    def describe(self, source_id: str) -> dict:
        pipe = self.get(source_id)
        live = pipe.snapshot_live()
        return {
            "id": source_id,
            **pipe.camera.info(),
            "status": live["status"],
            "error": live["error"] or pipe.camera.stats.last_error,
            "inference_fps": live["inference_fps"],
            "dogs_visible": len(live["dogs"]),
            "people_visible": live["people"],
            "stream_url": f"/api/sources/{source_id}/stream.mjpg",
            "recording": pipe.recording_status(),
        }

    def reload_zones(self, camera_key: str | None = None) -> None:
        for pipe in list(self.pipelines.values()):
            if camera_key is None or pipe.camera_key == camera_key:
                pipe.reload_zones()

    def stop_all(self) -> None:
        for sid in list(self.pipelines):
            with self._lock:
                pipe = self.pipelines.pop(sid, None)
            if pipe:
                pipe.stop()


# ----------------------------------------------------------------------------
# App factory
# ----------------------------------------------------------------------------

def create_app(settings: AppSettings | None = None, initial_sources: list[str] | None = None) -> FastAPI:
    settings = settings or AppSettings()
    storage = Path(settings.storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    db = Database(storage / "dogwatch.db")
    manager = SourceManager(settings, db)

    # The same app can be served twice (HTTP for this laptop + HTTPS for
    # phones), and each server runs the lifespan. Only the first start and the
    # last stop do any work.
    servers_running = {"n": 0}
    cleaner = {"auto": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        servers_running["n"] += 1
        if servers_running["n"] == 1:
            if settings.keep_days is not None:
                cleaner["auto"] = AutoCleaner(db, storage, settings.keep_days).start()
            for s in initial_sources or []:
                try:
                    sid = await asyncio.to_thread(manager.add, s)
                    print(f"[startup] watching {s} as {sid}")
                except (ValueError, RuntimeError) as e:
                    print(f"[startup] could not open {s}: {e}")
        try:
            yield
        finally:
            servers_running["n"] -= 1
            if servers_running["n"] == 0:
                if cleaner["auto"]:
                    await asyncio.to_thread(cleaner["auto"].stop)
                await asyncio.to_thread(manager.stop_all)
                db.close()

    app = FastAPI(title="Street Dog Monitoring System", version="0.6.0", lifespan=lifespan)
    app.state.manager = manager
    app.state.db = db

    # The React dev server (Vite) runs on port 5173.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/media", StaticFiles(directory=str(storage)), name="media")

    @app.middleware("http")
    async def access_control(request: Request, call_next):
        if not is_public(request.url.path):
            client = request.client.host if request.client else None
            if not is_local_client(client):
                given = request.headers.get("x-access-token") or request.query_params.get("token")
                if not token_ok(settings.access_token, given):
                    return JSONResponse({"detail": "Access token required"}, status_code=401)
        return await call_next(request)

    frontend = Path(settings.frontend_dir).resolve()

    def frontend_built() -> bool:
        return (frontend / "index.html").is_file()

    def is_public(path: str) -> bool:
        if path in PUBLIC_PAGES:
            return True
        return frontend_built() and not path.startswith(PROTECTED_PREFIXES)

    def validate_source(source: str, request: Request) -> None:
        client = request.client.host if request.client else None
        try:
            check_source(source, Path(settings.media_dir), is_local_client(client))
        except ValueError as e:
            raise HTTPException(400, str(e))

    # -- general ---------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
        if frontend_built():
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-store"})
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/console", include_in_schema=False)
    def console():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/phone", include_in_schema=False)
    def phone_page():
        return FileResponse(STATIC_DIR / "phone.html")

    # -- phone connected through its browser -----------------------------------

    def phone_links() -> list[str]:
        if not settings.phone_port:
            return []
        token = f"?token={settings.access_token}" if settings.access_token else ""
        return [f"https://{ip}:{settings.phone_port}/phone{token}" for ip in lan_ips()]

    @app.get("/api/phone-link")
    def phone_link():
        links = phone_links()
        return {
            "enabled": bool(settings.phone_port),
            "urls": links,
            "qr_url": "/api/phone-link/qr.svg" if links else None,
            "phones_connected": sum(1 for p in manager.pipelines.values() if p.camera.kind == "phone"),
            "hint": None if settings.phone_port else
                    "Start the server with --phone to connect phones from their browser.",
        }

    @app.get("/api/phone-link/qr.svg")
    def phone_link_qr(index: int = Query(0, ge=0)):
        links = phone_links()
        if index >= len(links):
            raise HTTPException(404, "Phone connection is not enabled or no Wi-Fi address found.")
        return Response(qr_svg(links[index]), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})

    @app.websocket("/ws/phone")
    async def ws_phone(ws: WebSocket):
        """
        A phone's browser sends JPEG frames as binary messages. After each
        frame we answer with what the detector currently sees, so the phone
        can show it and knows it may send the next frame (no backlog builds up).
        """
        client = ws.client.host if ws.client else None
        if not is_local_client(client) and not token_ok(settings.access_token, ws.query_params.get("token")):
            await ws.close(code=1008)
            return
        phones = sum(1 for p in manager.pipelines.values() if p.camera.kind == "phone")
        if phones >= MAX_PHONES:
            await ws.accept()
            await ws.send_json({"type": "error", "message": f"Already {MAX_PHONES} phones connected."})
            await ws.close()
            return

        await ws.accept()
        raw_name = (ws.query_params.get("name") or "").strip()[:40]
        name = raw_name or f"Phone {phones + 1}"
        cam = PushCameraSource(name).start()
        try:
            sid = await asyncio.to_thread(manager.add_camera, cam)
        except Exception as e:
            await ws.send_json({"type": "error", "message": f"Could not start detection: {e}"})
            await ws.close()
            return
        await ws.send_json({"type": "ready", "id": sid, "name": name})

        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if data is None:
                    continue                     # text messages (pings) are ignored
                ok = cam.push_jpeg(data)
                live = manager.pipelines[sid].snapshot_live() if sid in manager.pipelines else {}
                await ws.send_json({
                    "type": "ack", "ok": ok,
                    "dogs": [{"dog_id": d["dog_id"], "activity": d["activity"]} for d in live.get("dogs", [])],
                    "people": live.get("people", 0),
                    "detector_fps": live.get("inference_fps", 0),
                })
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if sid in manager.pipelines:
                await asyncio.to_thread(manager.remove, sid)

    # -- session report ----------------------------------------------------------

    @app.get("/api/report", response_class=HTMLResponse)
    def session_report(minutes: float = Query(60, gt=0, le=60 * 24 * 365), download: bool = False):
        """One printable HTML page about the last N minutes (photos embedded, works offline)."""
        now = time.time()
        current = Path(manager.pipeline_settings.model_path)
        models = {"Detector": model_info(current) if current.exists() else {"name": current.name},
                  "Behaviour classifier": behaviour_info() if Path(settings.behaviour_model_path).is_file() else None}
        html = build_report(db, storage, now - minutes * 60, now, models=models)
        headers = {}
        if download:
            stamp = datetime.now().strftime("%Y%m%d_%H%M")
            headers["Content-Disposition"] = f'attachment; filename="dogwatch_report_{stamp}.html"'
        return HTMLResponse(html, headers=headers)

    # -- storage ---------------------------------------------------------------

    @app.get("/api/storage")
    def get_storage():
        """Disk use of the database, photos, alert clips and recordings."""
        out = storage_usage(db, storage, Path(settings.media_dir))
        auto = cleaner["auto"]
        out["keep_days"] = settings.keep_days
        out["last_auto_cleanup"] = auto.last if auto else None
        out["auto_cleanup_error"] = auto.last_error if auto else None
        return out

    @app.post("/api/storage/cleanup")
    def cleanup_storage(body: Cleanup):
        """Delete old dogs, positions, events and their photos/clips. Zones and videos are kept."""
        result = clean_storage(db, storage, body.days, body.dry_run, body.vacuum)
        if not body.dry_run:
            db.add_event("system", "storage_cleaned",
                         f"Deleted data older than {body.days:g} days: {result['dogs']} dogs, "
                         f"{result['events']} events, {result['files']} files ({result['freed_mb']} MB)")
        return result

    @app.get("/api/health")
    def health():
        return {"ok": True, "sources": len(manager.pipelines), "model": Path(settings.model_path).name}

    @app.get("/api/settings")
    def get_settings():
        ps = manager.pipeline_settings
        return {"model": Path(ps.model_path).name, "confidence": ps.confidence, "max_fps": ps.max_fps,
                "imgsz": ps.imgsz,
                "draw_people": ps.draw_people, "draw_trails": ps.draw_trails,
                "draw_zones": ps.draw_zones, "alert_zone": ps.alerts.zone,
                "alert_approach": ps.alerts.approach, "alert_pack": ps.alerts.pack,
                "pack_size": ps.alerts.pack_size,
                "use_behaviour_model": ps.use_behaviour_model,
                "alert_clips": ps.alert_clips,
                "behaviour_model_loaded": ps.behaviour_model is not None}

    @app.patch("/api/settings")
    def patch_settings(body: SettingsPatch):
        ps = manager.pipeline_settings
        for key, value in body.model_dump(exclude_none=True).items():
            if key.startswith("alert_"):
                setattr(ps.alerts, key.removeprefix("alert_"), value)
            elif key == "pack_size":
                ps.alerts.pack_size = value
            else:
                setattr(ps, key, value)
        return get_settings()

    # -- cameras / sources -----------------------------------------------------

    @app.get("/api/cameras/local")
    def local_cameras(max_index: int = Query(4, ge=1, le=10)):
        in_use = {p.camera.value for p in manager.pipelines.values() if p.camera.kind == "webcam"}
        found = list_local_cameras(max_index)
        # Cameras we're already using can't be opened twice; list them anyway.
        known = {c["index"] for c in found}
        for idx in sorted(in_use):
            if idx not in known:
                found.append({"index": idx, "width": None, "height": None})
        for c in found:
            c["in_use"] = c["index"] in in_use
        return sorted(found, key=lambda c: c["index"])

    @app.get("/api/sources")
    def list_sources():
        return [manager.describe(sid) for sid in list(manager.pipelines)]

    @app.post("/api/sources", status_code=201)
    def add_source(body: AddSource, request: Request):
        validate_source(body.source, request)
        try:
            sid = manager.add(body.source, body.name, body.loop)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, str(e))
        return manager.describe(sid)

    @app.post("/api/sources/phone", status_code=201)
    def add_phone(body: AddPhone, request: Request):
        try:
            url = phone_url(body.ip, body.app, body.port)
        except ValueError as e:
            raise HTTPException(400, str(e))
        validate_source(url, request)
        try:
            sid = manager.add(url, body.name or f"Phone {body.ip}")
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, str(e))
        return manager.describe(sid)

    @app.delete("/api/sources/{source_id}", status_code=204)
    def remove_source(source_id: str):
        manager.remove(source_id)
        return Response(status_code=204)

    @app.get("/api/sources/{source_id}/live")
    def source_live(source_id: str):
        return {"id": source_id, **manager.get(source_id).snapshot_live()}

    @app.get("/api/sources/{source_id}/snapshot.jpg")
    def source_snapshot(source_id: str, raw: bool = False):
        _, jpg = manager.get(source_id).latest_jpeg(annotated=not raw)
        if jpg is None:
            raise HTTPException(503, "No frame yet")
        return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/sources/{source_id}/stream.mjpg")
    async def source_stream(source_id: str, raw: bool = False):
        pipe = manager.get(source_id)

        async def frames():
            last = -1
            while source_id in manager.pipelines:
                fid, jpg = pipe.latest_jpeg(annotated=not raw)
                if jpg is not None and fid != last:
                    last = fid
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                           + f"Content-Length: {len(jpg)}\r\n\r\n".encode() + jpg + b"\r\n")
                await asyncio.sleep(0.02)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    def with_urls(events: list[dict]) -> list[dict]:
        for e in events:
            e["snapshot_url"] = f"/media/{e['snapshot']}" if e["snapshot"] else None
            e["clip_url"] = f"/media/{e['clip']}" if e.get("clip") else None
        return events

    # -- recording -------------------------------------------------------------

    @app.post("/api/sources/{source_id}/recording", status_code=201)
    def start_recording(source_id: str, body: StartRecording | None = None):
        """Record this camera to recordings/captures/ (for training clips or the report)."""
        body = body or StartRecording()
        pipe = manager.get(source_id)
        name = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", pipe.camera.name)          # "Video clip.mp4" -> "Video clip"
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:30] or source_id
        path = Path(settings.media_dir) / "captures" / f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        try:
            status = pipe.start_recording(path, body.annotated, body.max_minutes * 60, body.fps)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        db.add_event(source_id, "recording_started", f"Recording {pipe.camera.name} to {path.name}")
        return status

    @app.get("/api/sources/{source_id}/recording")
    def recording_status(source_id: str):
        status = manager.get(source_id).recording_status()
        if status is None:
            raise HTTPException(404, "Not recording")
        return status

    @app.delete("/api/sources/{source_id}/recording")
    def stop_recording(source_id: str):
        pipe = manager.get(source_id)
        status = pipe.stop_recording()
        if status is None:
            raise HTTPException(404, "Not recording")
        rel = f"captures/{status['file']}"
        status["source"] = str(Path(settings.media_dir) / rel)     # use with POST /api/sources
        status["url"] = f"/api/uploads/{rel}"
        db.add_event(source_id, "recording_saved",
                     f"Saved {status['seconds']} s recording {status['file']} ({status['size_mb']} MB)")
        return status

    # -- zones -----------------------------------------------------------------

    @app.get("/api/sources/{source_id}/zones")
    def list_zones(source_id: str):
        return db.list_zones(manager.get(source_id).camera_key)

    @app.post("/api/sources/{source_id}/zones", status_code=201)
    def add_zone(source_id: str, body: AddZone):
        pipe = manager.get(source_id)
        if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in body.points):
            raise HTTPException(400, "Zone points must be fractions of the frame (between 0 and 1).")
        points = [[round(x, 4), round(y, 4)] for x, y in body.points]
        zone_id = db.add_zone(pipe.camera_key, body.name.strip(), points)
        manager.reload_zones(pipe.camera_key)
        return db.get_zone(zone_id)

    @app.delete("/api/zones/{zone_id}", status_code=204)
    def delete_zone(zone_id: int):
        zone = db.get_zone(zone_id)
        if zone is None or not db.delete_zone(zone_id):
            raise HTTPException(404, f"No zone {zone_id}")
        manager.reload_zones(zone["camera_key"])
        return Response(status_code=204)

    # -- dogs / events / stats -------------------------------------------------

    def dog_view(d: dict) -> dict:
        d["snapshot_url"] = f"/media/{d['snapshot']}" if d["snapshot"] else None
        d["seconds_visible"] = round(d["last_seen"] - d["first_seen"], 1)
        seconds = {"RESTING": d["resting_s"], "WALKING": d["walking_s"], "RUNNING": d["running_s"]}
        total = sum(seconds.values())
        d["activity_share"] = {k: round(v / total, 3) if total else 0.0 for k, v in seconds.items()}
        d["main_activity"] = max(seconds, key=seconds.get) if total else None
        return d

    @app.get("/api/dogs")
    def list_dogs(limit: int = Query(100, le=1000), source_id: str | None = None,
                  min_seconds: float = 1.0, sort: str = "recent", minutes: float | None = Query(None, gt=0)):
        """sort: recent, longest, fastest, active (most walking + running) or oldest."""
        since = time.time() - minutes * 60 if minutes else 0.0
        try:
            dogs = db.list_dogs(limit, source_id, min_seconds, sort, since)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return [dog_view(d) for d in dogs]

    @app.get("/api/dogs/{dog_id}")
    def get_dog(dog_id: int, observations: bool = True):
        """One dog: activity split, path (for drawing on the camera view) and its events."""
        dog = db.get_dog(dog_id)
        if dog is None:
            raise HTTPException(404, f"No dog {dog_id}")
        dog = dog_view(dog)
        dog["path"] = db.dog_path(dog_id)
        dog["events"] = with_urls(db.dog_events(dog_id))
        if observations:                       # every per-second row; ?observations=false to skip
            dog["observations"] = db.observations(dog_id=dog_id)
        return dog

    @app.get("/api/events")
    def list_events(limit: int = Query(100, le=1000), type: str | None = None, after_id: int = 0):
        return with_urls(db.list_events(limit, type, after_id))

    @app.get("/api/alerts")
    def list_alerts(limit: int = Query(50, le=1000), after_id: int = 0):
        return with_urls(db.list_events(limit, after_id=after_id, types=ALERT_TYPES))

    @app.get("/api/export/{name}.csv")
    def export_csv(name: str, minutes: float | None = Query(None, gt=0)):
        """dogs, observations or events as CSV (for the report, Excel or pandas)."""
        if name not in db.EXPORTS:
            raise HTTPException(404, f"Unknown export {name!r}; use one of {', '.join(db.EXPORTS)}")
        since = time.time() - minutes * 60 if minutes else 0.0

        def lines():
            buf = io.StringIO()
            writer = csv.writer(buf)
            rows = db.export_rows(name, since)
            header = next(rows)
            time_cols = [i for i, c in enumerate(header) if c in ("ts", "first_seen", "last_seen")]
            writer.writerow(header + [f"{header[i]}_local" for i in time_cols])
            for row in rows:
                stamps = [datetime.fromtimestamp(row[i]).isoformat(sep=" ", timespec="seconds") for i in time_cols]
                writer.writerow(list(row) + stamps)
                if buf.tell() > 64_000:
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate()
            yield buf.getvalue()

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return StreamingResponse(lines(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="dogwatch_{name}_{stamp}.csv"'})

    @app.get("/api/stats/timeline")
    def stats_timeline(minutes: float = Query(60, gt=0, le=60 * 24 * 30),
                       bucket: float = Query(60, ge=5), source_id: str | None = None):
        """Dog-seconds per activity in each time bucket (bucket = seconds)."""
        if minutes * 60 / bucket > 2000:
            raise HTTPException(400, "Too many buckets: use a bigger bucket for this time range.")
        since = time.time() - minutes * 60
        return {"minutes": minutes, "bucket": bucket,
                "buckets": db.activity_timeline(since, bucket, source_id)}

    @app.get("/api/stats/speeds")
    def stats_speeds(minutes: float = Query(60, gt=0), bin_width: float = Query(0.25, gt=0),
                     max_speed: float = Query(4.0, gt=0, le=20), source_id: str | None = None):
        """Histogram of speeds (box heights per second). The last bin is 'max_speed and above'."""
        if max_speed / bin_width > 200:
            raise HTTPException(400, "Too many bins: use a bigger bin_width.")
        since = time.time() - minutes * 60
        counts = db.speed_histogram(since, bin_width, max_speed, source_id)
        return {"bin_width": bin_width,
                "edges": [round(i * bin_width, 3) for i in range(len(counts) + 1)],
                "counts": counts}

    @app.get("/api/stats/heatmap")
    def stats_heatmap(minutes: float = Query(60, gt=0), cols: int = Query(16, ge=2, le=64),
                      rows: int = Query(9, ge=2, le=64), source_id: str | None = None):
        """Dog-seconds per cell of a grid over the camera view (row 0 = top of the frame)."""
        since = time.time() - minutes * 60
        grid = db.position_grid(since, cols, rows, source_id)
        return {"cols": cols, "rows": rows, "max": max(max(r) for r in grid), "grid": grid}

    @app.get("/api/stats/summary")
    def stats_summary(minutes: float = Query(60 * 24, gt=0)):
        since = time.time() - minutes * 60
        out = db.summary(since)
        out["alerts"] = sum(n for t, n in out["events"].items() if t in ALERT_TYPES)
        out["activity_seconds"] = db.activity_summary(since)
        out["minutes"] = minutes
        return out

    insights = InsightsCache(settings.bites_csv)

    @app.get("/api/insights")
    def bite_insights():
        """Charts from the animal-bites dataset, each {title, labels, values, note}."""
        try:
            return insights.get()
        except FileNotFoundError:
            raise HTTPException(404, f"Bites dataset not found ({Path(settings.bites_csv).name})")
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(500, f"Can't read the bites dataset: {e}")

    @app.get("/api/stats/activity")
    def activity_stats(minutes: float = Query(60, gt=0)):
        since = time.time() - minutes * 60
        return {"minutes": minutes, "seconds": db.activity_summary(since)}

    # -- uploaded videos ---------------------------------------------------------

    media_dir = Path(settings.media_dir)

    @app.get("/api/uploads")
    def list_videos():
        """Videos in the media folder, ready to add as a source."""
        if not media_dir.exists():
            return []
        files = [f for f in media_dir.rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_TYPES]
        files.sort(key=lambda f: -f.stat().st_mtime)
        return [{"name": f.name, "source": str(f), "size_mb": round(f.stat().st_size / 1e6, 1),
                 "modified": f.stat().st_mtime,
                 "url": "/api/uploads/" + f.relative_to(media_dir).as_posix()} for f in files]

    @app.get("/api/uploads/{rel_path:path}")
    def get_video(rel_path: str):
        """Download or play a video from the media folder (recordings, uploads, captures)."""
        target = (media_dir / rel_path).resolve()
        if (not target.is_relative_to(media_dir.resolve()) or not target.is_file()
                or target.suffix.lower() not in VIDEO_TYPES):
            raise HTTPException(404, "No such video")
        return FileResponse(target, filename=target.name)

    @app.post("/api/uploads", status_code=201)
    async def upload_video(request: Request, filename: str = Query(..., max_length=120),
                           start: bool = False, loop: bool = True):
        """
        Upload a video. Send the file itself as the request body (not a form), e.g.
        fetch("/api/uploads?filename=clip.mp4&start=1", {method: "POST", body: file}).
        With start=1 it is added as a camera source straight away.
        """
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._") or "video.mp4"
        if Path(name).suffix.lower() not in VIDEO_TYPES:
            raise HTTPException(400, f"Only video files: {', '.join(sorted(VIDEO_TYPES))}")
        folder = media_dir / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        target, n = folder / name, 1
        while target.exists():
            target = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
            n += 1
        size, limit = 0, MAX_UPLOAD_MB * 1_000_000
        try:
            with open(target, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"Video is bigger than {MAX_UPLOAD_MB} MB.")
                    f.write(chunk)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        if size == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(400, "The upload was empty.")
        out = {"name": target.name, "source": str(target), "size_mb": round(size / 1e6, 1)}
        if start:
            try:
                sid = await asyncio.to_thread(manager.add, str(target), Path(filename).name, loop)
            except (ValueError, RuntimeError) as e:
                target.unlink(missing_ok=True)
                raise HTTPException(400, f"That file can't be opened as a video: {e}")
            out["source_id"] = sid
        return out

    # -- models -----------------------------------------------------------------

    models_dir = Path(settings.models_dir)

    def model_info(path: Path) -> dict:
        info = {"name": path.name, "size_mb": round(path.stat().st_size / 1e6, 1), "metrics": None}
        # Training scripts can save test results as <model>.json next to the weights.
        meta = path.with_suffix(".json")
        if meta.exists():
            try:
                info["metrics"] = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return info

    @app.get("/api/models")
    def list_models():
        current = Path(manager.pipeline_settings.model_path)
        files = sorted(f for f in models_dir.glob("*") if f.suffix.lower() in MODEL_TYPES) \
            if models_dir.exists() else []
        return {
            "current": current.name,
            "current_info": model_info(current) if current.exists() else None,
            "available": [model_info(f) | {"current": f.resolve() == current.resolve()} for f in files],
            "behaviour": behaviour_info(),
        }

    def behaviour_info() -> dict:
        path = Path(settings.behaviour_model_path)
        model = manager.pipeline_settings.behaviour_model
        info = {"loaded": model is not None, "file": path.name, "exists": path.is_file(),
                "in_use": model is not None and manager.pipeline_settings.use_behaviour_model,
                "labels": model.labels if model else None, "metrics": None}
        meta = path.with_suffix(".json")
        if meta.exists():
            try:
                info["metrics"] = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return info

    @app.post("/api/models/behaviour/reload")
    def reload_behaviour_model():
        """Load models/behaviour.joblib again, e.g. right after training a new one."""
        path = Path(settings.behaviour_model_path)
        if not path.is_file():
            manager.pipeline_settings.behaviour_model = None
            raise HTTPException(404, f"No {path.name} in models/ yet. Train one first (training/behaviour).")
        try:
            manager.pipeline_settings.behaviour_model = BehaviourModel(path)
        except Exception as e:
            raise HTTPException(400, f"Can't load {path.name}: {e}")
        db.add_event("system", "model_changed", f"Loaded behaviour classifier {path.name}")
        return behaviour_info()

    @app.post("/api/models/select")
    def select_model(body: SelectModel):
        path = models_dir / Path(body.name).name          # only files inside models/
        if path.suffix.lower() not in MODEL_TYPES or not path.is_file():
            raise HTTPException(404, f"No model {body.name!r} in {models_dir.name}/")
        from ultralytics import YOLO
        try:
            first = YOLO(str(path))
            dog, person = class_ids(first.names)
        except Exception as e:
            raise HTTPException(400, f"Can't use {path.name}: {e}")
        manager.pipeline_settings.model_path = str(path)
        # Each camera needs its own copy: the tracker's state lives inside the model.
        pipes = list(manager.pipelines.values())
        for i, pipe in enumerate(pipes):
            pipe.use_model(first if i == 0 else YOLO(str(path)))
        db.add_event("system", "model_changed", f"Switched detector to {path.name}")
        return {"current": path.name, "dog_class": dog, "person_class": person,
                "cameras_updated": len(pipes)}

    # -- websocket -------------------------------------------------------------

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        client = ws.client.host if ws.client else None
        if not is_local_client(client) and not token_ok(settings.access_token, ws.query_params.get("token")):
            await ws.close(code=1008)   # policy violation
            return
        await ws.accept()
        last_event = (db.list_events(limit=1) or [{"id": 0}])[0]["id"]
        try:
            while True:
                new_events = db.list_events(limit=50, after_id=last_event)
                if new_events:
                    last_event = new_events[0]["id"]
                await ws.send_json({
                    "ts": time.time(),
                    "sources": {sid: p.snapshot_live() for sid, p in list(manager.pipelines.items())},
                    "events": list(reversed(new_events)),
                })
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # -- React dashboard files (must stay the last route) ------------------------

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard_files(path: str):
        """Files of the built dashboard; any other page path gets index.html (client-side routing)."""
        if not frontend_built() or f"/{path}".startswith(PROTECTED_PREFIXES):
            raise HTTPException(404, "Not found")
        target = (frontend / path).resolve()
        if target.is_relative_to(frontend) and target.is_file():
            return FileResponse(target)
        if "." in Path(path).name:          # a missing file like /assets/x.js: real 404
            raise HTTPException(404, "Not found")
        return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-store"})

    return app
