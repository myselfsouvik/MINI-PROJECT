"""
Tests for backend/cameras.py. Run with:  python -m pytest tests -q

No real camera is needed: a video file is generated on the fly, and a tiny
local HTTP server imitates a phone running IP Webcam (MJPEG stream).
"""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.cameras import CameraSource, parse_source, phone_url

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def make_video(path: Path, frames: int = 20, size=(320, 240), fps: int = 20, image=None) -> Path:
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert writer.isOpened(), "OpenCV can't write mp4 on this machine"
    for i in range(frames):
        if image is not None:
            frame = cv2.resize(image, (w, h))
        else:
            frame = np.zeros((h, w, 3), np.uint8)
            cv2.rectangle(frame, (10 + i * 5, 50), (60 + i * 5, 100), (0, 255, 0), -1)
        writer.write(frame)
    writer.release()
    return path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakePhone:
    """Serves an MJPEG stream at /video, like the IP Webcam app."""

    def __init__(self, size=(640, 480)):
        self.size = size
        self.port = free_port()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output quiet
                pass

            def do_GET(self):
                if self.path != "/video":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                w, h = fake.size
                i = 0
                try:
                    while not fake.stopped.is_set():
                        img = np.full((h, w, 3), (i * 7) % 255, np.uint8)
                        ok, jpg = cv2.imencode(".jpg", img)
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode())
                        self.wfile.write(jpg.tobytes() + b"\r\n")
                        i += 1
                        time.sleep(1 / 30)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.stopped = threading.Event()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/video"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stopped.set()
        self.server.shutdown()
        self.server.server_close()


# ----------------------------------------------------------------------------
# parse_source / phone_url
# ----------------------------------------------------------------------------

def test_parse_webcam_numbers():
    assert parse_source("0") == ("webcam", 0)
    assert parse_source(" 1 ") == ("webcam", 1)
    assert parse_source(2) == ("webcam", 2)


def test_parse_stream_urls():
    for url in ["http://192.168.1.5:8080/video", "https://x/y", "rtsp://cam/stream"]:
        assert parse_source(url) == ("stream", url)


def test_parse_existing_file(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    assert parse_source(str(f)) == ("file", str(f))


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_source("not_a_real_file.mp4")


def test_phone_url():
    assert phone_url("192.168.1.5") == "http://192.168.1.5:8080/video"
    assert phone_url("192.168.1.5", "droidcam") == "http://192.168.1.5:4747/video"
    assert phone_url("10.0.0.2", port=9000) == "http://10.0.0.2:9000/video"
    with pytest.raises(ValueError):
        phone_url("1.2.3.4", "unknown-app")


# ----------------------------------------------------------------------------
# CameraSource with a video file
# ----------------------------------------------------------------------------

def test_video_file_reads_all_frames_then_finishes(tmp_path):
    video = make_video(tmp_path / "clip.mp4", frames=20)
    cam = CameraSource(str(video), loop=False, realtime=False).start()
    try:
        deadline = time.monotonic() + 10
        while not cam.finished and time.monotonic() < deadline:
            time.sleep(0.02)
        assert cam.finished
        assert cam.stats.frames_read == 20
        assert (cam.stats.width, cam.stats.height) == (320, 240)
        assert cam.read().shape == (240, 320, 3)
    finally:
        cam.stop()


def test_video_file_loops(tmp_path):
    video = make_video(tmp_path / "clip.mp4", frames=10)
    with CameraSource(str(video), loop=True, realtime=False) as cam:
        deadline = time.monotonic() + 10
        while cam.stats.frames_read < 35 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert cam.stats.frames_read >= 35
        assert not cam.finished


def test_realtime_playback_respects_video_fps(tmp_path):
    video = make_video(tmp_path / "clip.mp4", frames=200, fps=20)
    with CameraSource(str(video), realtime=True) as cam:
        time.sleep(1.5)
        assert 12 <= cam.stats.fps <= 26, cam.stats.fps


def test_wait_frame_returns_newer_frames(tmp_path):
    video = make_video(tmp_path / "clip.mp4", frames=50)
    with CameraSource(str(video)) as cam:
        first_id = cam.frame_id
        assert cam.wait_frame(timeout=3, after_id=first_id) is not None
        assert cam.frame_id > first_id


def test_bad_webcam_index_gives_clear_error():
    with pytest.raises(RuntimeError, match="Could not open webcam"):
        CameraSource("9").start(timeout=2)


# ----------------------------------------------------------------------------
# CameraSource with a (fake) phone over Wi-Fi
# ----------------------------------------------------------------------------

def test_phone_mjpeg_stream():
    with FakePhone(size=(640, 480)) as phone:
        with CameraSource(phone.url) as cam:
            assert cam.kind == "stream"
            frame = cam.read()
            assert frame.shape == (480, 640, 3)
            time.sleep(1.0)
            assert cam.stats.frames_read > 10
            info = cam.info()
            assert info["running"] and info["width"] == 640


def test_unreachable_phone_gives_clear_error():
    url = f"http://127.0.0.1:{free_port()}/video"   # nothing listening there
    with pytest.raises(RuntimeError, match="Could not open stream"):
        CameraSource(url).start(timeout=3)


# ----------------------------------------------------------------------------
# End to end: camera_test script with detection on a video of a real dog
# ----------------------------------------------------------------------------

def test_camera_test_script_detects_dog(tmp_path, capsys):
    dog = cv2.imread(str(ROOT / "legacy" / "dog_images" / "dog_ID_5_002.jpg"))
    assert dog is not None
    video = make_video(tmp_path / "dog.mp4", frames=10, size=(dog.shape[1], dog.shape[0]), image=dog)

    from backend import camera_test
    code = camera_test.main(["--source", str(video), "--detect", "--headless",
                             "--frames", "25", "--conf", "0.5"])
    out = capsys.readouterr().out
    assert code == 0
    assert "dogs: 1" in out, out
