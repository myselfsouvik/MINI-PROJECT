"""
FastAPI web server for the Street Dog Monitoring System.

Start it with:  python -m backend.server --source 0
Then open http://127.0.0.1:8000 (test page) or http://127.0.0.1:8000/docs (API docs).

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
    GET    /api/stats/activity                seconds per activity
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
import itertools
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.cameras import PHONE_APPS, CameraSource, PushCameraSource, list_local_cameras, phone_url
from backend.phone import lan_ips, qr_svg
from backend.db import Database
from backend.pipeline import Pipeline, PipelineSettings
from backend.security import check_source, is_local_client, token_ok

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass
class AppSettings:
    model_path: str = str(ROOT / "models" / "yolo11n.pt")
    storage_dir: str = str(ROOT / "backend" / "storage")
    confidence: float = 0.5
    max_fps: float = 0.0
    # Video files added through the API must be inside this folder.
    media_dir: str = str(ROOT / "recordings")
    # Other devices on the network must send this token. None = only this computer.
    access_token: str | None = None
    # Port of the HTTPS server for phones (None = phone browser connection off).
    phone_port: int | None = None


PUBLIC_PAGES = {"/", "/phone"}   # pages with no data in them; the API still needs the token
MAX_PHONES = 4


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
    draw_people: bool | None = None
    draw_trails: bool | None = None


# ----------------------------------------------------------------------------
# Source manager
# ----------------------------------------------------------------------------

class SourceManager:
    def __init__(self, settings: AppSettings, db: Database):
        self.settings = settings
        self.db = db
        self.storage = Path(settings.storage_dir)
        self.pipeline_settings = PipelineSettings(
            model_path=settings.model_path, confidence=settings.confidence, max_fps=settings.max_fps)
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
        }

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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        servers_running["n"] += 1
        if servers_running["n"] == 1:
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
                await asyncio.to_thread(manager.stop_all)
                db.close()

    app = FastAPI(title="Street Dog Monitoring System", version="0.3.0", lifespan=lifespan)
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
        # The two pages hold no data; everything else needs access.
        if request.url.path not in PUBLIC_PAGES:
            client = request.client.host if request.client else None
            if not is_local_client(client):
                given = request.headers.get("x-access-token") or request.query_params.get("token")
                if not token_ok(settings.access_token, given):
                    return JSONResponse({"detail": "Access token required"}, status_code=401)
        return await call_next(request)

    def validate_source(source: str, request: Request) -> None:
        client = request.client.host if request.client else None
        try:
            check_source(source, Path(settings.media_dir), is_local_client(client))
        except ValueError as e:
            raise HTTPException(400, str(e))

    # -- general ---------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
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

    @app.get("/api/health")
    def health():
        return {"ok": True, "sources": len(manager.pipelines), "model": Path(settings.model_path).name}

    @app.get("/api/settings")
    def get_settings():
        ps = manager.pipeline_settings
        return {"model": Path(ps.model_path).name, "confidence": ps.confidence, "max_fps": ps.max_fps,
                "draw_people": ps.draw_people, "draw_trails": ps.draw_trails}

    @app.patch("/api/settings")
    def patch_settings(body: SettingsPatch):
        ps = manager.pipeline_settings
        for key, value in body.model_dump(exclude_none=True).items():
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

    # -- dogs / events / stats -------------------------------------------------

    @app.get("/api/dogs")
    def list_dogs(limit: int = Query(100, le=1000), source_id: str | None = None,
                  min_seconds: float = 1.0):
        dogs = db.list_dogs(limit, source_id, min_seconds)
        for d in dogs:
            d["snapshot_url"] = f"/media/{d['snapshot']}" if d["snapshot"] else None
            d["seconds_visible"] = round(d["last_seen"] - d["first_seen"], 1)
        return dogs

    @app.get("/api/dogs/{dog_id}")
    def get_dog(dog_id: int):
        dog = db.get_dog(dog_id)
        if dog is None:
            raise HTTPException(404, f"No dog {dog_id}")
        dog["snapshot_url"] = f"/media/{dog['snapshot']}" if dog["snapshot"] else None
        dog["observations"] = db.observations(dog_id=dog_id)
        return dog

    @app.get("/api/events")
    def list_events(limit: int = Query(100, le=1000), type: str | None = None, after_id: int = 0):
        events = db.list_events(limit, type, after_id)
        for e in events:
            e["snapshot_url"] = f"/media/{e['snapshot']}" if e["snapshot"] else None
        return events

    @app.get("/api/stats/activity")
    def activity_stats(minutes: float = Query(60, gt=0)):
        since = time.time() - minutes * 60
        return {"minutes": minutes, "seconds": db.activity_summary(since)}

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

    return app
