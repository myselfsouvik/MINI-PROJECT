"""
Saving video: manual recordings (for collecting training clips) and short
clips around alerts.

Cameras don't deliver frames at a steady rate (Wi-Fi phones stutter, the
detector is slower than the camera), but a video file has a fixed frame rate.
The recorder therefore uses each frame's *timestamp*: if a frame arrives late
it is repeated, if frames come faster than the file's rate the extras are
skipped. A 30-second recording always plays for 30 seconds.

Formats
    .mp4 (MPEG-4)  manual recordings: opens in labelling tools (CVAT, Roboflow)
    .webm (VP8)    alert clips: plays directly in the browser (<video>)
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np

MAX_GAP_SECONDS = 2.0     # after a longer pause (e.g. phone lost Wi-Fi) don't fill the gap
CODECS = {".mp4": "mp4v", ".webm": "VP80", ".avi": "MJPG"}


def _writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    codec = CODECS.get(path.suffix.lower())
    if codec is None:
        raise ValueError(f"Unsupported video type {path.suffix}")
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
    if not w.isOpened():
        raise RuntimeError(f"Can't write video {path}")
    return w


class FrameTimer:
    """Decides how many times to write each frame so the file plays at real speed."""

    def __init__(self, fps: float):
        self.fps = fps
        self.t0: float | None = None
        self.written = 0
        self.skipped_gap = 0.0

    def copies(self, t: float) -> int:
        if self.t0 is None:
            self.t0 = t
            self.written = 1
            return 1
        due = int((t - self.t0 - self.skipped_gap) * self.fps) + 1
        n = due - self.written
        if n > self.fps * MAX_GAP_SECONDS:          # long pause: write one frame and move on
            self.skipped_gap += (n - 1) / self.fps
            n = 1
        n = max(0, n)
        self.written += n
        return n

    @property
    def seconds(self) -> float:
        return self.written / self.fps


class VideoRecorder:
    """
    Record frames fed from another thread (camera or pipeline). ``feed`` never
    blocks: frames go into a queue that a background thread writes to disk.
    """

    def __init__(self, path: str | Path, fps: float = 15.0, max_seconds: float = 600.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.max_seconds = max_seconds
        self.started = time.time()
        self.error: str | None = None
        self._timer = FrameTimer(fps)
        self._size: tuple[int, int] | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=int(fps * 4))
        self._stop = threading.Event()
        self._done = threading.Event()
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name=f"rec-{self.path.name}", daemon=True)
        self._thread.start()

    # -- called from the camera / pipeline thread ---------------------------------

    def feed(self, frame: np.ndarray, t: float) -> None:
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait((frame, t))
        except queue.Full:
            self.dropped += 1                         # disk too slow: the timer repeats the next frame

    # -- control ------------------------------------------------------------------

    def stop(self, timeout: float = 30.0) -> dict:
        self._stop.set()
        self._done.wait(timeout)
        return self.status()

    @property
    def active(self) -> bool:
        return not self._done.is_set()

    def status(self) -> dict:
        size = self.path.stat().st_size if self.path.exists() else 0
        return {"file": self.path.name, "active": self.active, "seconds": round(self._timer.seconds, 1),
                "max_seconds": self.max_seconds, "size_mb": round(size / 1e6, 2),
                "width": self._size[0] if self._size else None,
                "height": self._size[1] if self._size else None,
                "dropped_frames": self.dropped, "error": self.error}

    # -- writer thread ---------------------------------------------------------------

    def _run(self) -> None:
        writer = None
        try:
            while True:
                try:
                    frame, t = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                if writer is None:
                    h, w = frame.shape[:2]
                    self._size = (w, h)
                    writer = _writer(self.path, self.fps, self._size)
                if frame.shape[1::-1] != self._size:     # camera changed resolution
                    frame = cv2.resize(frame, self._size)
                for _ in range(self._timer.copies(t)):
                    writer.write(frame)
                if self._timer.seconds >= self.max_seconds:
                    self._stop.set()
                    break
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        finally:
            if writer is not None:
                writer.release()
            self._done.set()


def write_clip(frames: list[tuple[float, bytes]], path: str | Path, fps: float = 10.0) -> Path | None:
    """Write (timestamp, JPEG bytes) frames to a video at real speed. Returns the path, or None."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timer, writer, size = FrameTimer(fps), None, None
    try:
        for t, jpg in sorted(frames, key=lambda f: f[0]):
            frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if writer is None:
                size = (frame.shape[1], frame.shape[0])
                writer = _writer(path, fps, size)
            elif frame.shape[1::-1] != size:
                frame = cv2.resize(frame, size)
            for _ in range(timer.copies(t)):
                writer.write(frame)
    finally:
        if writer is not None:
            writer.release()
    return path if writer is not None and path.exists() and path.stat().st_size > 0 else None
