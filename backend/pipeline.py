"""
Detection pipeline: one per camera.

    CameraSource ──► YOLO detect + track ──► BehaviourTracker ──► Database
                                       ├──► AlertEngine (zones, running at person, pack)
                                       └──► annotated JPEG for the live stream

Runs on its own thread. The web server only reads its latest results, so a
slow model never blocks the API.
"""

from __future__ import annotations

import threading
from collections import deque
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from backend.alerts import AlertEngine, AlertRules, DogView, Zone
from backend.behaviour import RESTING, RUNNING, WALKING, BehaviourTracker, TrackState
from backend.cameras import CameraSource
from backend.db import Database
from backend.recording import VideoRecorder, write_clip

CLIP_BEFORE = 4.0    # seconds of video kept from before an alert
CLIP_AFTER = 4.0     # and recorded after it
CLIP_FPS = 10.0

PERSON_CLASS = 0     # COCO numbers, used by the stock model
DOG_CLASS = 16


def class_ids(names: dict[int, str]) -> tuple[int, int | None]:
    """
    Find the dog and person class numbers in a model. The stock COCO model has
    dog = 16, person = 0; our fine-tuned model may have only "dog" (= 0).
    """
    by_name = {str(n).lower(): i for i, n in names.items()}
    dog = by_name.get("dog")
    if dog is None:
        if len(names) == 1:                 # single-class model: that class is the dog
            dog = next(iter(names))
        else:
            raise ValueError(f"Model has no 'dog' class (classes: {list(names.values())[:10]})")
    return int(dog), by_name.get("person")

# BGR colours per activity
COLOURS = {
    RESTING: (220, 160, 40),   # blue
    WALKING: (60, 190, 60),    # green
    RUNNING: (40, 70, 235),    # red
}
PERSON_COLOUR = (170, 170, 170)
ZONE_COLOUR = (0, 200, 255)          # amber
ZONE_ACTIVE_COLOUR = (40, 40, 230)   # red while a dog is inside

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
    draw_zones: bool = True
    alert_clips: bool = True                 # save a short video with each alert
    alerts: AlertRules = field(default_factory=AlertRules)   # shared by all cameras
    behaviour_model: object | None = None    # backend.features.BehaviourModel, if trained
    use_behaviour_model: bool = True


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
        (self.storage_dir / "alerts").mkdir(parents=True, exist_ok=True)

        self.behaviour = BehaviourTracker()
        self.alerts = AlertEngine(rules=settings.alerts)
        self.reload_zones()
        self._records: dict[int, _DogRecord] = {}
        self._model = None
        self._dog_cls, self._person_cls = DOG_CLASS, PERSON_CLASS
        self._pending_model = None   # (model, dog_cls, person_cls) waiting to be swapped in

        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._jpeg_id = 0
        self._raw_jpeg: bytes | None = None
        self.live = LiveState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Alert clips: annotated JPEGs of the last CLIP_BEFORE seconds, and the
        # clips still collecting their "after" part.
        self._recent: deque = deque()
        self._clip_jobs: list[dict] = []
        # Manual recording (VideoRecorder) and whether it records the annotated view.
        self.recorder: VideoRecorder | None = None
        self._recorder_annotated = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "Pipeline":
        from ultralytics import YOLO   # imported here so the module loads fast

        self._model = YOLO(self.settings.model_path)
        self._dog_cls, self._person_cls = class_ids(self._model.names)
        if not self.camera.is_running:
            self.camera.start()
        self._thread = threading.Thread(target=self._run, name=f"pipe-{self.source_id}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self.stop_recording()
        for job in self._clip_jobs:              # save what we have of unfinished clips
            self._save_clip(job, background=False)
        self._clip_jobs = []
        self.camera.stop()
        self._flush_all(time.time())
        if self.live.status in ("running", "starting"):
            self.live.status = "stopped"

    @property
    def camera_key(self) -> str:
        """Stable name for this camera, used to keep its zones across restarts."""
        value = self.camera.value
        if self.camera.kind == "file":
            value = Path(str(value)).resolve()
        return f"{self.camera.kind}:{value}"

    def reload_zones(self) -> None:
        self.alerts.zones = [Zone(z["id"], z["name"], [tuple(p) for p in z["points"]])
                             for z in self.db.list_zones(self.camera_key)]

    def use_model(self, model) -> None:
        """Switch to another (already loaded) YOLO model at the next frame."""
        dog, person = class_ids(model.names)
        self._pending_model = (model, dog, person)
        if self._thread is None or not self._thread.is_alive():
            self._swap_model(time.time())

    def _swap_model(self, now: float) -> None:
        model, dog, person = self._pending_model
        self._pending_model = None
        # Track IDs restart with the new model's tracker, so close every current dog.
        for state in list(self.behaviour.tracks.values()):
            self._dog_left(state, now)
        self.behaviour = BehaviourTracker()
        self._model, self._dog_cls, self._person_cls = model, dog, person

    # -- manual recording ---------------------------------------------------------

    def start_recording(self, path: Path, annotated: bool = False, max_seconds: float = 600,
                        fps: float = 15.0) -> dict:
        if self.recorder and self.recorder.active:
            raise RuntimeError("Already recording this camera.")
        self.recorder = VideoRecorder(path, fps=fps, max_seconds=max_seconds)
        self._recorder_annotated = annotated
        if not annotated:            # clean frames straight from the camera, at camera speed
            self.camera.add_listener(self.recorder.feed)
        return self.recorder.status()

    def stop_recording(self) -> dict | None:
        rec = self.recorder
        if rec is None:
            return None
        self.camera.remove_listener(rec.feed)
        status = rec.stop()
        return status

    def recording_status(self) -> dict | None:
        if self.recorder is None:
            return None
        status = self.recorder.status()
        if not status["active"]:                 # finished by itself (time limit)
            self.camera.remove_listener(self.recorder.feed)
        return status

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
                if self._pending_model is not None:
                    self._swap_model(time.time())

                t0 = time.perf_counter()
                wanted = [c for c in (self._person_cls, self._dog_cls) if c is not None]
                result = self._model.track(
                    frame, persist=True, classes=wanted,
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
        h, w = frame.shape[:2]
        dogs_live, people = [], 0
        person_boxes, dog_views = [], []
        s = self.settings
        self.behaviour.classifier = s.behaviour_model if s.use_behaviour_model else None

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
                if c == self._person_cls:
                    people += 1
                    person_boxes.append(box)
                    if self.settings.draw_people:
                        x1, y1, x2, y2 = map(int, box)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), PERSON_COLOUR, 1)
                    continue
                if c != self._dog_cls:
                    continue
                if tid is None:      # tracker hasn't confirmed this dog yet
                    continue
                state, is_new = self.behaviour.update(int(tid), box, now, float(p))
                rec = self._record_for(state, is_new, now)
                self._store(state, rec, raw, box, now)
                self._draw_dog(annotated, state, rec, box)
                info = self._dog_json(state, rec, box)
                info["zones"] = [z.name for z in self.alerts.zones_containing(box, w, h)]
                dogs_live.append(info)
                dog_views.append(DogView(rec.db_id, box, state.activity))

        for gone in self.behaviour.expire(now):
            self._dog_left(gone, now)

        if self.settings.draw_zones:
            self._draw_zones(annotated, dog_views, w, h)
        self._draw_hud(annotated, len(dogs_live), people, infer_fps)

        for alert in self.alerts.evaluate(now, dog_views, person_boxes, w, h):
            self._raise_alert(alert, annotated, now)

        q = [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality]
        ok1, jpg = cv2.imencode(".jpg", annotated, q)
        ok2, raw_jpg = cv2.imencode(".jpg", raw, q)
        if ok1:
            self._collect_clip_frames(jpg.tobytes(), now)
        if self.recorder is not None and self._recorder_annotated:
            self.recorder.feed(annotated, time.perf_counter())

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
            # Positions are stored as fractions of the frame (0..1) so the
            # heat map works the same for every camera resolution.
            fh, fw = raw.shape[:2]
            centre = (round(state.center[0] / fw, 4), round(state.center[1] / fh, 4))
            self.db.add_observation(rec.db_id, now, centre, state.speed,
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

    def _raise_alert(self, alert, annotated: np.ndarray, now: float) -> None:
        self._alert_count = getattr(self, "_alert_count", 0) + 1
        rel = f"alerts/{self.source_id}_{int(now * 1000)}_{self._alert_count}.jpg"
        path = self.storage_dir / rel
        snapshot = rel if cv2.imwrite(str(path), annotated) else None
        event_id = self.db.add_event(self.source_id, alert.type, alert.message, dog_id=alert.dog_id,
                                     snapshot=snapshot, ts=now)
        if not self.settings.alert_clips:
            return
        # Alerts close together share one clip.
        for job in self._clip_jobs:
            if now - job["start"] < 1.0:
                job["events"].append(event_id)
                return
        self._clip_jobs.append({"start": now, "until": now + CLIP_AFTER, "events": [event_id],
                                "frames": list(self._recent),
                                "file": f"alerts/{self.source_id}_{int(now * 1000)}.webm"})

    def _collect_clip_frames(self, jpg: bytes, now: float) -> None:
        self._recent.append((now, jpg))
        while self._recent and now - self._recent[0][0] > CLIP_BEFORE:
            self._recent.popleft()
        if not self._clip_jobs:
            return
        still = []
        for job in self._clip_jobs:
            job["frames"].append((now, jpg))
            if now >= job["until"]:
                self._save_clip(job)
            else:
                still.append(job)
        self._clip_jobs = still

    def _save_clip(self, job: dict, background: bool = True) -> None:
        def work():
            try:
                if write_clip(job["frames"], self.storage_dir / job["file"], CLIP_FPS):
                    for event_id in job["events"]:
                        self.db.set_event_clip(event_id, job["file"])
            except Exception as e:      # a clip is a bonus: never break detection over it
                print(f"[clip] {job['file']}: {e}")

        if background:
            threading.Thread(target=work, name="alert-clip", daemon=True).start()
        else:
            work()

    # -- drawing ---------------------------------------------------------------

    def _draw_zones(self, img: np.ndarray, dogs: list[DogView], w: int, h: int) -> None:
        if not self.alerts.zones:
            return
        occupied = {z.id for d in dogs for z in self.alerts.zones_containing(d.box, w, h)}
        overlay = img.copy()
        for zone in self.alerts.zones:
            pts = np.array([(x * w, y * h) for x, y in zone.points], np.int32).reshape(-1, 1, 2)
            colour = ZONE_ACTIVE_COLOUR if zone.id in occupied else ZONE_COLOUR
            cv2.fillPoly(overlay, [pts], colour)
            cv2.polylines(img, [pts], True, colour, 2, cv2.LINE_AA)
            x, y = pts[:, 0, 0].min(), pts[:, 0, 1].min()
            cv2.putText(img, zone.name, (int(x) + 4, int(y) + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        colour, 2, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.18, img, 0.82, 0, dst=img)

    def _draw_dog(self, img: np.ndarray, state: TrackState, rec: _DogRecord, box) -> None:
        colour = COLOURS[state.activity]
        x1, y1, x2, y2 = map(int, box)
        if self.settings.draw_trails and len(state.trail) > 1:
            pts = np.array(state.trail, np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, colour, 2, cv2.LINE_AA)
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2)
        label = f"Dog #{rec.db_id}  {state.label or state.activity}  {state.speed:.2f}"
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
            "behaviour": state.label,                 # classifier label, None without a model
            "behaviour_conf": round(state.label_conf, 3) if state.label else None,
            "speed": round(state.speed, 3),
            "confidence": round(state.confidence, 3),
            "seconds_visible": round(state.duration, 1),
            "trail": list(state.trail)[-15:],
        }
