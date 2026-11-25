"""
Per-dog movement tracking and activity labels.

Speed is measured in **box heights per second** instead of pixels per second:
the pixel distance moved is divided by the height of the dog's bounding box.
A dog far from the camera (small box) and one close up (big box) moving at the
same real speed therefore get roughly the same number, and the result doesn't
change with camera resolution. This fixes the main weakness of the legacy
script (fixed 20 / 80 px/s thresholds).

Speed is measured over the last second of movement (so frame-to-frame box
jitter cancels out) and then smoothed with a moving average, so
the activity label doesn't flicker between frames.

These rule-based labels are the baseline; the trained behaviour classifier
(training/behaviour) will replace ``classify`` later.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

RESTING = "RESTING"
WALKING = "WALKING"
RUNNING = "RUNNING"
ACTIVITIES = (RESTING, WALKING, RUNNING)

# Thresholds in box heights per second (tune with real footage).
REST_BELOW = 0.25
RUN_FROM = 1.5

SPEED_WINDOW = 1.0        # seconds of movement used for each speed measurement
MAX_INSTANT_SPEED = 6.0   # box heights / second; anything faster is a tracker glitch
SMOOTHING_SECONDS = 0.5   # time constant of the moving average
TRAIL_LENGTH = 40         # points kept for the motion trail


def classify(speed_bh: float) -> str:
    """Activity label for a smoothed speed in box heights per second."""
    if speed_bh < REST_BELOW:
        return RESTING
    if speed_bh < RUN_FROM:
        return WALKING
    return RUNNING


@dataclass
class TrackState:
    """Everything we know about one tracked dog."""

    track_id: int
    first_seen: float
    last_seen: float
    center: tuple[float, float]
    box_h: float
    speed: float = 0.0               # smoothed, box heights / second
    activity: str = RESTING
    confidence: float = 0.0
    trail: deque = field(default_factory=lambda: deque(maxlen=TRAIL_LENGTH))
    seconds_in: dict = field(default_factory=lambda: {a: 0.0 for a in ACTIVITIES})

    # (t, center_x, center_y, box_h) for roughly the last SPEED_WINDOW seconds
    history: deque = field(default_factory=deque)

    def update(self, center: tuple[float, float], box_h: float, t: float, confidence: float) -> None:
        dt = t - self.last_seen
        if dt > 0:
            self.history.append((t, center[0], center[1], box_h))
            # Keep the oldest point at least SPEED_WINDOW seconds old.
            while len(self.history) > 2 and t - self.history[1][0] >= SPEED_WINDOW:
                self.history.popleft()
            t0, x0, y0, h0 = self.history[0]
            span = t - t0
            if span > 0:
                # Distance over the whole window, not frame to frame: box
                # jitter cancels out instead of adding up. Average box height
                # keeps it stable when the dog walks towards / away from us.
                scale = max(1.0, (box_h + h0) / 2)
                dist = math.hypot(center[0] - x0, center[1] - y0)
                instant = min(dist / scale / span, MAX_INSTANT_SPEED)
                alpha = 1 - math.exp(-dt / SMOOTHING_SECONDS)
                self.speed += alpha * (instant - self.speed)
            # Time is credited to the activity the dog was doing during dt.
            self.seconds_in[self.activity] += dt
            self.activity = classify(self.speed)
        self.center = center
        self.box_h = box_h
        self.last_seen = t
        self.confidence = confidence
        self.trail.append((int(center[0]), int(center[1])))

    @property
    def duration(self) -> float:
        return self.last_seen - self.first_seen


class BehaviourTracker:
    """Keeps a TrackState for every dog the detector is tracking."""

    def __init__(self, forget_after: float = 3.0):
        self.forget_after = forget_after
        self.tracks: dict[int, TrackState] = {}

    def update(self, track_id: int, box_xyxy, t: float, confidence: float) -> tuple[TrackState, bool]:
        """Feed one detection. Returns (state, is_new)."""
        x1, y1, x2, y2 = box_xyxy
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        box_h = max(1.0, y2 - y1)
        state = self.tracks.get(track_id)
        if state is None:
            state = TrackState(track_id, t, t, center, box_h, confidence=confidence)
            state.trail.append((int(center[0]), int(center[1])))
            state.history.append((t, center[0], center[1], box_h))
            self.tracks[track_id] = state
            return state, True
        state.update(center, box_h, t, confidence)
        return state, False

    def expire(self, now: float) -> list[TrackState]:
        """Remove dogs not seen for ``forget_after`` seconds and return them."""
        gone = [s for s in self.tracks.values() if now - s.last_seen > self.forget_after]
        for s in gone:
            del self.tracks[s.track_id]
        return gone

    def visible(self, now: float, within: float = 0.5) -> list[TrackState]:
        """Dogs seen in the last ``within`` seconds."""
        return [s for s in self.tracks.values() if now - s.last_seen <= within]
