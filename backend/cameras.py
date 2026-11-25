"""
Camera sources for the Street Dog Monitoring System.

One class, ``CameraSource``, opens any kind of video input and always hands
back the *latest* frame:

    "0", "1", ...                      laptop webcam, or a phone connected over
                                       USB with DroidCam / Iriun (it shows up as
                                       an extra webcam, usually index 1)
    "http://192.168.1.5:8080/video"    phone over Wi-Fi (IP Webcam, DroidCam)
    "rtsp://..."                       IP / CCTV cameras
    "clip.mp4"                         a recorded video (loops by default)

Frames are read on a background thread, so a slow network camera never makes
the detector fall behind: it always works on the newest frame and old ones are
dropped. Network cameras reconnect automatically if the Wi-Fi drops.
"""

from __future__ import annotations

import os
import platform
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

IS_WINDOWS = platform.system() == "Windows"

# Default stream paths of popular phone-camera apps.
PHONE_APPS = {
    "ipwebcam": {"port": 8080, "path": "/video"},   # IP Webcam (Android)
    "droidcam": {"port": 4747, "path": "/video"},   # DroidCam (Android / iPhone)
}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def phone_url(ip: str, app: str = "ipwebcam", port: int | None = None) -> str:
    """Build the stream URL for a phone camera app, e.g. phone_url("192.168.1.5")."""
    if app not in PHONE_APPS:
        raise ValueError(f"Unknown app {app!r}. Choose from: {', '.join(PHONE_APPS)}")
    cfg = PHONE_APPS[app]
    return f"http://{ip}:{port or cfg['port']}{cfg['path']}"


def parse_source(source: str | int) -> tuple[str, str | int]:
    """
    Work out what kind of source a string is.

    Returns (kind, value) where kind is "webcam", "stream" or "file".
    """
    if isinstance(source, int):
        return "webcam", source
    s = str(source).strip()
    if s.isdigit():
        return "webcam", int(s)
    if s.lower().startswith(("http://", "https://", "rtsp://", "rtmp://", "udp://")):
        return "stream", s
    if Path(s).expanduser().exists():
        return "file", str(Path(s).expanduser())
    raise ValueError(
        f"Can't use source {s!r}: not a webcam number, a stream URL or an existing video file."
    )


def _open_capture(kind: str, value: str | int) -> cv2.VideoCapture:
    if kind == "webcam":
        # DirectShow opens USB / virtual webcams (DroidCam, Iriun) faster and
        # more reliably than the default backend on Windows.
        if IS_WINDOWS:
            cap = cv2.VideoCapture(value, cv2.CAP_DSHOW)
            if cap.isOpened():
                return cap
            cap.release()
        return cv2.VideoCapture(value)
    if kind == "stream":
        # Keep the network buffer tiny so we don't show old frames.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        cap = cv2.VideoCapture(value, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return cv2.VideoCapture(value)


def list_local_cameras(max_index: int = 6) -> list[dict]:
    """
    Probe webcam indexes 0..max_index-1 and return the ones that give a frame.

    A phone connected with DroidCam / Iriun appears here as an extra camera.
    Note: this briefly switches each camera on.
    """
    found = []
    for i in range(max_index):
        cap = _open_capture("webcam", i)
        try:
            if not cap.isOpened():
                continue
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                found.append({"index": i, "width": w, "height": h})
        finally:
            cap.release()
    return found


# ----------------------------------------------------------------------------
# CameraSource
# ----------------------------------------------------------------------------

@dataclass
class CameraStats:
    frames_read: int = 0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    reconnects: int = 0
    last_error: str = ""
    _fps_window: deque = field(default_factory=deque, repr=False)


class CameraSource:
    """
    A camera that keeps reading in the background.

    Usage:
        with CameraSource("0") as cam:
            frame = cam.read()          # newest frame (numpy BGR) or None

    Args:
        source: webcam index, stream URL or video file path.
        name:   label shown on the dashboard.
        loop:   restart video files when they end.
        realtime: play video files at their own FPS instead of as fast as possible.
        width/height: ask a webcam for this resolution (it may ignore it).
    """

    RECONNECT_DELAY = 2.0     # seconds between reconnect attempts for streams
    MAX_FAILED_READS = 30     # consecutive failed reads before reconnecting

    def __init__(
        self,
        source: str | int,
        name: str | None = None,
        loop: bool = True,
        realtime: bool = True,
        width: int | None = None,
        height: int | None = None,
    ):
        self.kind, self.value = parse_source(source)
        self.name = name or self._default_name()
        self.loop = loop
        self.realtime = realtime
        self.req_width = width
        self.req_height = height

        self.stats = CameraStats()
        self._cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._frame_id = 0
        self._lock = threading.Lock()
        self._new_frame = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._finished = False
        self._listeners: list = []

    # -- public API ----------------------------------------------------------

    def add_listener(self, fn) -> None:
        """Call ``fn(frame, t)`` for every new frame (t = perf_counter seconds). Must be fast."""
        self._listeners.append(fn)

    def remove_listener(self, fn) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def start(self, timeout: float = 10.0) -> "CameraSource":
        """Open the source and start reading. Raises RuntimeError if it can't open."""
        self._connect()
        if not self._cap or not self._cap.isOpened():
            raise RuntimeError(self._open_error_message())
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, name=f"cam-{self.name}", daemon=True)
        self._thread.start()
        # Wait for the first frame so callers can rely on read() straight away.
        if self.wait_frame(timeout) is None:
            self.stop()
            raise RuntimeError(f"Opened {self.name} but no frames arrived within {timeout:.0f}s.")
        return self

    def read(self) -> np.ndarray | None:
        """Return a copy of the newest frame (BGR), or None if none yet."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def wait_frame(self, timeout: float = 5.0, after_id: int = 0) -> np.ndarray | None:
        """Block until a frame newer than ``after_id`` arrives (or timeout)."""
        deadline = time.monotonic() + timeout
        with self._new_frame:
            while self._frame_id <= after_id and not self._finished:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._new_frame.wait(remaining)
            return None if self._frame is None else self._frame.copy()

    @property
    def frame_id(self) -> int:
        """Increases by one for every new frame. Use it to skip frames you've seen."""
        return self._frame_id

    @property
    def finished(self) -> bool:
        """True when a non-looping video file has ended."""
        return self._finished

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def info(self) -> dict:
        """Summary for the dashboard / logs."""
        return {
            "name": self.name,
            "kind": self.kind,
            "source": str(self.value),
            "running": self.is_running,
            "fps": round(self.stats.fps, 1),
            "width": self.stats.width,
            "height": self.stats.height,
            "frames": self.stats.frames_read,
            "reconnects": self.stats.reconnects,
            "error": self.stats.last_error,
        }

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "CameraSource":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- internals -----------------------------------------------------------

    def _default_name(self) -> str:
        if self.kind == "webcam":
            return f"Webcam {self.value}"
        if self.kind == "stream":
            return f"Stream {self.value}"
        return f"Video {Path(str(self.value)).name}"

    def _open_error_message(self) -> str:
        if self.kind == "webcam":
            return (f"Could not open webcam {self.value}. Check it isn't used by another app; "
                    f"for a USB phone, make sure the DroidCam/Iriun PC client is running.")
        if self.kind == "stream":
            return (f"Could not open stream {self.value}. Check the phone and laptop are on the "
                    f"same Wi-Fi and the URL opens in a browser.")
        return f"Could not open video file {self.value}."

    def _connect(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = _open_capture(self.kind, self.value)
        if self.kind == "webcam" and self._cap.isOpened():
            if self.req_width:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.req_width)
            if self.req_height:
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.req_height)

    def _reader(self) -> None:
        file_fps = 0.0
        if self.kind == "file" and self._cap is not None:
            file_fps = self._cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_gap = 1.0 / file_fps if (self.realtime and file_fps > 0) else 0.0
        failed = 0

        while not self._stop.is_set():
            t0 = time.monotonic()
            ok, frame = (self._cap.read() if self._cap is not None else (False, None))

            if not ok or frame is None:
                failed += 1
                if self.kind == "file":
                    if self.loop and self.stats.frames_read > 0:
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    self._mark_finished()
                    return
                if failed >= self.MAX_FAILED_READS:
                    self._reconnect()
                    failed = 0
                else:
                    time.sleep(0.01)
                continue

            failed = 0
            self._publish(frame)

            if frame_gap:
                spare = frame_gap - (time.monotonic() - t0)
                if spare > 0:
                    self._stop.wait(spare)

    def _publish(self, frame: np.ndarray) -> None:
        # perf_counter: time.monotonic() only ticks every ~15 ms on Windows, so
        # two fast frames could get the same timestamp.
        now = time.perf_counter()
        st = self.stats
        st.frames_read += 1
        st.height, st.width = frame.shape[:2]
        window = st._fps_window
        window.append(now)
        while window and now - window[0] > 2.0:
            window.popleft()
        span = window[-1] - window[0]
        if len(window) > 1 and span > 0:
            st.fps = (len(window) - 1) / span
        with self._new_frame:
            self._frame = frame
            self._frame_id += 1
            self._new_frame.notify_all()
        for fn in list(self._listeners):
            try:
                fn(frame, now)
            except Exception as e:      # a listener must never stop the camera
                self.stats.last_error = f"listener: {e}"

    def _mark_finished(self) -> None:
        with self._new_frame:
            self._finished = True
            self._new_frame.notify_all()

    def _reconnect(self) -> None:
        self.stats.last_error = "Lost connection, reconnecting…"
        while not self._stop.is_set():
            self.stats.reconnects += 1
            self._connect()
            if self._cap is not None and self._cap.isOpened():
                self.stats.last_error = ""
                return
            self._stop.wait(self.RECONNECT_DELAY)


# ----------------------------------------------------------------------------
# PushCameraSource: frames sent to us (phone browser over WebSocket)
# ----------------------------------------------------------------------------

class PushCameraSource(CameraSource):
    """
    A camera whose frames are *pushed* to the server instead of read from a
    device. Used for phones that open the /phone page in their browser: the
    page sends JPEG frames over a WebSocket and the server calls ``push_jpeg``.

    It behaves like ``CameraSource`` (read / wait_frame / frame_id / info), so
    the detection pipeline doesn't need to know the difference.
    """

    MAX_JPEG_BYTES = 2_000_000   # ignore anything bigger than ~2 MB per frame

    def __init__(self, name: str):
        # Skip CameraSource.__init__'s parse_source: there's no device to open.
        self.kind, self.value = "phone", name
        self.name = name
        self.loop = False
        self.realtime = True
        self.req_width = self.req_height = None
        self.stats = CameraStats()
        self._cap = None
        self._frame = None
        self._frame_id = 0
        self._lock = threading.Lock()
        self._new_frame = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread = None
        self._finished = False
        self._connected = False
        self._listeners = []

    def start(self, timeout: float = 0.0) -> "PushCameraSource":
        self._connected = True
        self._stop.clear()
        return self

    def stop(self) -> None:
        self._connected = False
        self._stop.set()
        self._mark_finished()

    @property
    def is_running(self) -> bool:
        return self._connected

    def push_jpeg(self, data: bytes) -> bool:
        """Decode one JPEG frame from the phone. Returns False if it isn't a valid image."""
        if not self._connected or not data or len(data) > self.MAX_JPEG_BYTES:
            return False
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        self._publish(frame)
        return True
