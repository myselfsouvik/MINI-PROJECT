"""
Detection pipeline: one per camera.

    CameraSource ──► YOLO detect + track ──► BehaviourTracker ──► Database
                                       └──► annotated JPEG for the live stream

Runs on its own thread. The web server only reads its latest results, so a
slow model never blocks the API.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from backend.behaviour import RESTING, RUNNING, WALKING, BehaviourTracker, TrackState
from backend.cameras import CameraSource
from backend.db import Database

PERSON_CLASS = 0
DOG_CLASS = 16

# BGR colours per activity
COLOURS = {
    RESTING: (220, 160, 40),   # blue
    WALKING: (60, 190, 60),    # green
    RUNNING: (40, 70, 235),    # red
}
PERSON_COLOUR = (170, 170, 170)

ANNOUNCE_AFTER = 1.0       # seconds a dog must be tracked before "dog appeared" (filters flicker)
OBSERVATION_EVERY = 1.0    # seconds between stored observations per dog
SNAPSHOT_EVERY = 2.0       # min seconds between best-crop updates per dog


@dataclass
class PipelineSettings:
    model_path: str
    confidence: float = 0.5
    tracker: str = "bytetrack.yaml"
    jpeg_quality: int = 80
    max_fps: float = 0.0          # 0 = as fast as the computer allows
    draw_people: bool = True
    draw_trails: bool = True


@dataclass
class _DogRecord:
    db_id: int
    announced: bool = False
    last_obs: float = 0.0
    last_snap: float = 0.0
    best_conf: float = 0.0
    max_speed: float = 0.0


@dataclass
class LiveState:
    status: str = "starting"           # starting | running | finished | error | stopped
    error: str = ""
    frame_width: int = 0
    frame_height: int = 0
    camera_fps: float = 0.0
    inference_fps: float = 0.0
    dogs: list = field(default_factory=list)
    people: int = 0
    updated: float = 0.0


class Pipeline:
    def __init__(self, source_id: str, camera: CameraSource, settings: PipelineSettings,
                 db: Database, storage_dir: Path):
        self.source_id = source_id
        self.camera = camera
        self.settings = settings
        self.db = db
        self.storage_dir = Path(storage_dir)
        (self.storage_dir / "dogs").mkdir(parents=True, exist_ok=True)

        self.behaviour = BehaviourTracker()
        self._records: dict[int, _DogRecord] = {}
        self._model = None

        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._jpeg_id = 0
        self._raw_jpeg: bytes | None = None
        self.live = LiveState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "Pipeline":
        from ultralytics import YOLO   # imported here so the module loads fast

        self._model = YOLO(self.settings.model_path)
        if not self.camera.is_running:
            self.camera.start()
        self._thread = threading.Thread(target=self._run, name=f"pipe-{self.source_id}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self.camera.stop()
        self._flush_all(time.time())
        if self.live.status in ("running", "starting"):
            self.live.status = "stopped"

    # -- results for the API -------------------------------------------------

    def latest_jpeg(self, annotated: bool = True) -> tuple[int, bytes | None]:
        with self._lock:
            return self._jpeg_id, (self._jpeg if annotated else self._raw_jpeg)

    def snapshot_live(self) -> dict:
        with self._lock:
            s = self.live
            return {
                "status": s.status, "error": s.error,
                "frame_width": s.frame_width, "frame_height": s.frame_height,
                "camera_fps": round(s.camera_fps, 1), "inference_fps": round(s.inference_fps, 1),
                "dogs": list(s.dogs), "people": s.people, "updated": s.updated,
            }

    # -- main loop -----------------------------------------------------------

    def _run(self) -> None:
        self.live.status = "running"
        last_id = 0
        infer_fps = 0.0
        try:
            while not self._stop.is_set():
                frame = self.camera.wait_frame(timeout=1.0, after_id=last_id)
                if frame is None:
                    if self.camera.finished:
                        self.live.status = "finished"
                        break
                    continue
                last_id = self.camera.frame_id

                t0 = time.perf_counter()
                result = self._model.track(
                    frame, persist=True, classes=[PERSON_CLASS, DOG_CLASS],
                    conf=self.settings.confidence, tracker=self.settings.tracker, verbose=False,
                )[0]
                dt = time.perf_counter() - t0
                infer_fps = (1 / dt) if infer_fps == 0 else 0.85 * infer_fps + 0.15 * (1 / max(dt, 1e-6))

                self._process(frame, result, time.time(), infer_fps)

                if self.settings.max_fps > 0:
                    spare = 1 / self.settings.max_fps - (time.perf_counter() - t0)
                    if spare > 0:
                        self._stop.wait(spare)
        except Exception as e:  # keep the server alive, show the error on the dashboard
            self.live.status = "error"
            self.live.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    def _process(self, frame: np.ndarray, result, now: float, infer_fps: float) -> None:
        raw = frame.copy()
        annotated = frame
        dogs_live, people = [], 0

        boxes = result.boxes
        if boxes is not None and len(boxes):
            xyxy = boxes.xyxy.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            conf = boxes.conf.cpu().numpy()
            ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(cls)

            for box, c, p, tid in zip(xyxy, cls, conf, ids):
                # Plain Python numbers: numpy types break JSON and SQLite.
                box = tuple(float(v) for v in box)
                c, p = int(c), float(p)
                if c == PERSON_CLASS:
                    people += 1
                    if self.settings.draw_people:
                        x1, y1, x2, y2 = map(int, box)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), PERSON_COLOUR, 1)
                    continue
                if tid is None:      # tracker hasn't confirmed this dog yet
                    continue
                state, is_new = self.behaviour.update(int(tid), box, now, float(p))
                rec = self._record_for(state, is_new, now)
                self._store(state, rec, raw, box, now)
                self._draw_dog(annotated, state, rec, box)
                dogs_live.append(self._dog_json(state, rec, box))

        for gone in self.behaviour.expire(now):
            self._dog_left(gone, now)

        self._draw_hud(annotated, len(dogs_live), people, infer_fps)
        q = [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality]
        ok1, jpg = cv2.imencode(".jpg", annotated, q)
        ok2, raw_jpg = cv2.imencode(".jpg", raw, q)

        h, w = frame.shape[:2]
        with self._lock:
            if ok1:
                self._jpeg = jpg.tobytes()
            if ok2:
                self._raw_jpeg = raw_jpg.tobytes()
            self._jpeg_id += 1
            self.live.frame_width, self.live.frame_height = w, h
            self.live.camera_fps = self.camera.stats.fps
            self.live.inference_fps = infer_fps
            self.live.dogs = dogs_live
            self.live.people = people
            self.live.updated = now

    # -- per-dog bookkeeping ---------------------------------------------------

    def _record_for(self, state: TrackState, is_new: bool, now: float) -> _DogRecord:
        rec = self._records.get(state.track_id)
        if rec is None or is_new:
            db_id = self.db.add_dog(self.source_id, state.track_id, now, state.confidence)
            rec = _DogRecord(db_id=db_id)
            self._records[state.track_id] = rec
        return rec

    def _store(self, state: TrackState, rec: _DogRecord, raw: np.ndarray, box, now: float) -> None:
        rec.max_speed = max(rec.max_speed, state.speed)
        snapshot = None
        best = None
        if (state.confidence > rec.best_conf + 0.03 and now - rec.last_snap >= SNAPSHOT_EVERY) \
                or rec.last_snap == 0:
            snapshot = self._save_crop(raw, box, f"dogs/dog_{rec.db_id}.jpg")
            if snapshot:
                rec.best_conf = max(rec.best_conf, state.confidence)
                best = rec.best_conf
                rec.last_snap = now

        if not rec.announced and state.duration >= ANNOUNCE_AFTER:
            rec.announced = True
            self.db.add_event(self.source_id, "dog_appeared",
                              f"Dog #{rec.db_id} appeared", dog_id=rec.db_id,
                              snapshot=f"dogs/dog_{rec.db_id}.jpg", ts=now)

        if now - rec.last_obs >= OBSERVATION_EVERY:
            rec.last_obs = now
            self.db.add_observation(rec.db_id, now, state.center, state.speed,
                                    state.activity, state.confidence)
            self.db.update_dog(rec.db_id, last_seen=now, seconds_in=state.seconds_in,
                               max_speed=rec.max_speed, best_confidence=best, snapshot=snapshot)
        elif snapshot:
            self.db.update_dog(rec.db_id, last_seen=now, seconds_in=state.seconds_in,
                               max_speed=rec.max_speed, best_confidence=best, snapshot=snapshot)

    def _dog_left(self, state: TrackState, now: float) -> None:
        rec = self._records.pop(state.track_id, None)
        if rec is None:
            return
        self.db.update_dog(rec.db_id, last_seen=state.last_seen, seconds_in=state.seconds_in,
                           max_speed=rec.max_speed)
        if rec.announced:
            self.db.add_event(self.source_id, "dog_left",
                              f"Dog #{rec.db_id} left after {state.duration:.0f}s",
                              dog_id=rec.db_id, ts=now)

    def _flush_all(self, now: float) -> None:
        for state in list(self.behaviour.tracks.values()):
            self._dog_left(state, now)
        self.behaviour.tracks.clear()

    def _save_crop(self, frame: np.ndarray, box, rel_path: str) -> str | None:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        pad_x, pad_y = (x2 - x1) * 0.1, (y2 - y1) * 0.1
        x1, y1 = int(max(0, x1 - pad_x)), int(max(0, y1 - pad_y))
        x2, y2 = int(min(w, x2 + pad_x)), int(min(h, y2 + pad_y))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        path = self.storage_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return rel_path if cv2.imwrite(str(path), crop) else None

    # -- drawing ---------------------------------------------------------------

    def _draw_dog(self, img: np.ndarray, state: TrackState, rec: _DogRecord, box) -> None:
        colour = COLOURS[state.activity]
        x1, y1, x2, y2 = map(int, box)
        if self.settings.draw_trails and len(state.trail) > 1:
            pts = np.array(state.trail, np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, colour, 2, cv2.LINE_AA)
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2)
        label = f"Dog #{rec.db_id}  {state.activity}  {state.speed:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        ty = max(th + 6, y1)
        cv2.rectangle(img, (x1, ty - th - 6), (x1 + tw + 6, ty), colour, -1)
        cv2.putText(img, label, (x1 + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 1, cv2.LINE_AA)

    def _draw_hud(self, img: np.ndarray, dogs: int, people: int, fps: float) -> None:
        text = f"{self.camera.name}  |  dogs {dogs}  people {people}  |  {fps:.1f} fps"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        x2, y2 = min(img.shape[1], tw + 20), th + 16
        strip = img[0:y2, 0:x2]
        img[0:y2, 0:x2] = (strip * 0.35).astype(img.dtype)     # darken behind the text
        cv2.putText(img, text, (10, th + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)

    @staticmethod
    def _dog_json(state: TrackState, rec: _DogRecord, box) -> dict:
        x1, y1, x2, y2 = (round(float(v), 1) for v in box)
        return {
            "dog_id": rec.db_id,
            "track_id": state.track_id,
            "box": [x1, y1, x2, y2],
            "activity": state.activity,
            "speed": round(state.speed, 3),
            "confidence": round(state.confidence, 3),
            "seconds_visible": round(state.duration, 1),
            "trail": list(state.trail)[-15:],
        }
