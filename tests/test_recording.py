"""
Tests for recording (checkpoint 9): frame timing, the recorder, alert clips,
the recording API and old-database migration.
"""

from __future__ import annotations

import sqlite3
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.cameras import CameraSource
from backend.db import Database
from backend.demo import DEMO_ZONE, make_demo_video
from backend.recording import FrameTimer, VideoRecorder, write_clip
from tests.test_api import LOCAL, wait_for


def frame(i=0, size=(320, 240)):
    f = np.full((size[1], size[0], 3), (i * 7) % 255, np.uint8)
    cv2.putText(f, str(i), (20, 120), 0, 2, (255, 255, 255), 3)
    return f


def video_info(path):
    cap = cv2.VideoCapture(str(path))
    info = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return info


# -- timing ---------------------------------------------------------------------------

def test_frame_timer_keeps_real_speed():
    t = FrameTimer(10)
    assert [t.copies(x / 10) for x in range(5)] == [1, 1, 1, 1, 1]        # steady
    assert t.copies(0.8) == 4                                              # late frame repeated
    assert t.copies(0.82) == 0 and t.copies(0.84) == 0                     # too fast: skipped
    assert t.seconds == pytest.approx(0.9)


def test_frame_timer_does_not_fill_long_gaps():
    t = FrameTimer(10)
    t.copies(0)
    assert t.copies(60) == 1          # a minute without frames doesn't become 600 copies
    assert t.copies(60.1) == 1


# -- recorder and clips ---------------------------------------------------------------------

def test_recorder_writes_real_time_video(tmp_path):
    rec = VideoRecorder(tmp_path / "r.mp4", fps=10)
    for i in range(30):                       # 3 s of frames at 10 fps, with a stall in the middle
        rec.feed(frame(i), i / 10 + (0.5 if i >= 15 else 0))
    status = rec.stop()
    assert not status["active"] and status["error"] is None
    assert status["seconds"] == pytest.approx(3.4, abs=0.15)
    count, fps = video_info(tmp_path / "r.mp4")
    assert fps == 10 and count == pytest.approx(34, abs=1)


def test_recorder_stops_at_time_limit_and_handles_resize(tmp_path):
    rec = VideoRecorder(tmp_path / "r.mp4", fps=10, max_seconds=1.0)
    for i in range(40):
        rec.feed(frame(i, size=(320, 240) if i < 5 else (640, 480)), i / 10)
    assert wait_for(lambda: not rec.active, timeout=10)
    status = rec.status()
    assert status["seconds"] == pytest.approx(1.0, abs=0.1) and (status["width"], status["height"]) == (320, 240)


def test_write_clip_is_browser_video(tmp_path):
    frames = [(i / 20, cv2.imencode(".jpg", frame(i))[1].tobytes()) for i in range(80)]   # 4 s
    path = write_clip(frames, tmp_path / "c.webm", fps=10)
    assert path and path.suffix == ".webm"
    count, fps = video_info(path)
    assert fps == 10 and count == pytest.approx(40, abs=1)
    assert write_clip([], tmp_path / "empty.webm") is None


# -- camera listener and database ---------------------------------------------------------------

def test_camera_listener_sees_frames_and_cannot_break_camera(tmp_path):
    video = make_demo_video(tmp_path / "v.mp4", seconds=2)
    seen = []
    cam = CameraSource(str(video), loop=True)
    cam.add_listener(lambda f, t: 1 / 0)                       # a broken listener
    cam.add_listener(lambda f, t: seen.append(t))
    cam.start()
    try:
        assert wait_for(lambda: len(seen) >= 10, timeout=10)
        assert cam.read() is not None and "listener" in cam.stats.last_error
    finally:
        cam.stop()


def test_old_database_gets_clip_column(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, "
                "source_id TEXT NOT NULL, type TEXT NOT NULL, dog_id INTEGER, message TEXT NOT NULL, snapshot TEXT)")
    con.execute("INSERT INTO events (ts, source_id, type, message) VALUES (1, 'cam1', 'dog_appeared', 'old')")
    con.commit()
    con.close()
    db = Database(path)
    eid = db.add_event("cam1", "zone_entered", "new")
    db.set_event_clip(eid, "alerts/x.webm")
    events = {e["message"]: e for e in db.list_events()}
    assert events["old"]["clip"] is None and events["new"]["clip"] == "alerts/x.webm"
    db.close()


# -- API ------------------------------------------------------------------------------------

@pytest.fixture()
def demo(tmp_path):
    media = tmp_path / "media"
    video = make_demo_video(media / "demo.mp4", seconds=8)
    app = create_app(AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(media)),
                     initial_sources=[str(video)])
    with TestClient(app, client=LOCAL) as c:
        yield c, media


def test_record_camera_and_download(demo):
    c, media = demo
    assert c.get("/api/sources/cam1/recording").status_code == 404
    assert c.delete("/api/sources/cam1/recording").status_code == 404

    r = c.post("/api/sources/cam1/recording", json={"max_minutes": 1})
    assert r.status_code == 201 and r.json()["active"]
    assert c.post("/api/sources/cam1/recording").status_code == 409          # already recording
    assert c.get("/api/sources").json()[0]["recording"]["active"]
    time.sleep(2.5)
    saved = c.delete("/api/sources/cam1/recording").json()
    assert saved["seconds"] == pytest.approx(2.5, abs=0.8) and saved["size_mb"] > 0
    assert saved["file"].endswith(".mp4") and (media / "captures" / saved["file"]).exists()
    assert (saved["width"], saved["height"]) == (960, 600)                    # clean camera frames

    video = c.get(saved["url"])
    assert video.status_code == 200 and len(video.content) > 1000
    assert saved["file"] in [v["name"] for v in c.get("/api/uploads").json()]
    assert any(e["type"] == "recording_saved" for e in c.get("/api/events").json())

    # The recording can be watched as a camera (e.g. to test detection on it).
    assert c.post("/api/sources", json={"source": saved["source"]}).status_code == 201


def test_annotated_recording(demo):
    c, media = demo
    assert c.post("/api/sources/cam1/recording", json={"annotated": True}).status_code == 201
    time.sleep(1.5)
    saved = c.delete("/api/sources/cam1/recording").json()
    assert saved["seconds"] > 0.5 and (media / "captures" / saved["file"]).exists()


def test_video_download_stays_in_media_folder(demo, tmp_path):
    c, _ = demo
    (tmp_path / "secret.mp4").write_bytes(b"secret")
    for path in ["/api/uploads/../secret.mp4", "/api/uploads/..%2Fsecret.mp4", "/api/uploads/nope.mp4"]:
        assert c.get(path).status_code == 404, path
    assert c.get("/api/uploads/demo.mp4").status_code == 200


def test_alert_gets_a_video_clip(tmp_path):
    media = tmp_path / "media"
    video = make_demo_video(media / "demo.mp4", seconds=20)
    app = create_app(AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(media)),
                     initial_sources=[str(video)])
    with TestClient(app, client=LOCAL) as c:
        assert c.get("/api/settings").json()["alert_clips"] is True
        c.post("/api/sources/cam1/zones", json=DEMO_ZONE)
        alert = wait_for(lambda: [a for a in c.get("/api/alerts").json() if a["clip_url"]], timeout=60)
        assert alert, "no alert clip was saved"
        clip = c.get(alert[0]["clip_url"])
        assert clip.status_code == 200
        path = tmp_path / "clip.webm"
        path.write_bytes(clip.content)
        count, fps = video_info(path)
        assert fps == 10 and count >= 40          # ~4 s after (+ up to 4 s before) at 10 fps
