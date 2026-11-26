"""
Alert rules, evaluated on every processed frame.

    zone_entered           a dog walks into a zone drawn on the camera view
                           (e.g. "school gate"); uses the dog's feet (bottom
                           centre of its box), not the middle of the box
    dog_running_at_person  a RUNNING dog is getting closer to a person
    dog_pack               3 or more dogs in view at the same time

These are transparent rules on top of the trained models (detector + behaviour);
we don't claim to detect "aggression" without data to prove it. Each rule has
a cooldown so one situation produces one alert, not one per frame.

Zone points are stored as fractions of the frame (0..1), so a zone keeps
working if the camera resolution changes.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from backend.behaviour import RUNNING

ZONE_FRAMES_REQUIRED = 3       # consecutive frames inside before "entered" (ignores jitter)
ZONE_COOLDOWN = 30.0           # seconds before the same dog can trigger the same zone again
APPROACH_WINDOW = 1.0          # seconds over which "getting closer" is measured
APPROACH_MIN_CLOSING = 1.0     # must close the gap by >= 1 dog box height in that window
APPROACH_MAX_DISTANCE = 4.0    # and be within 4 dog box heights of the person
APPROACH_COOLDOWN = 20.0
PACK_SIZE = 3
PACK_COOLDOWN = 60.0

ALERT_TYPES = ("zone_entered", "dog_running_at_person", "dog_pack")


@dataclass
class Zone:
    id: int
    name: str
    points: list[tuple[float, float]]    # fractions of frame width / height


@dataclass
class Alert:
    type: str
    message: str
    dog_id: int | None = None
    zone_id: int | None = None


@dataclass
class DogView:
    """What the alert engine needs to know about one visible dog."""
    dog_id: int
    box: tuple[float, float, float, float]   # x1, y1, x2, y2 in pixels
    activity: str


def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray casting: count how many polygon edges a ray to the right crosses."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            cross_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < cross_x:
                inside = not inside
    return inside


def feet(box) -> tuple[float, float]:
    x1, _, x2, y2 = box
    return (x1 + x2) / 2, y2


def centre(box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass
class AlertRules:
    zone: bool = True
    approach: bool = True
    pack: bool = True
    pack_size: int = PACK_SIZE


@dataclass
class AlertEngine:
    rules: AlertRules = field(default_factory=AlertRules)
    zones: list[Zone] = field(default_factory=list)

    _inside_frames: dict = field(default_factory=dict)      # (dog, zone) -> consecutive frames inside
    _last_fired: dict = field(default_factory=dict)         # key -> time of last alert
    _gap_history: dict = field(default_factory=dict)        # dog -> deque[(t, gap in box heights)]

    def zones_containing(self, box, width: int, height: int) -> list[Zone]:
        fx, fy = feet(box)
        px, py = fx / max(width, 1), fy / max(height, 1)
        return [z for z in self.zones if point_in_polygon(px, py, z.points)]

    def evaluate(self, now: float, dogs: list[DogView], people: list[tuple], width: int,
                 height: int) -> list[Alert]:
        alerts: list[Alert] = []
        if self.rules.zone:
            alerts += self._check_zones(now, dogs, width, height)
        if self.rules.approach:
            alerts += self._check_approach(now, dogs, people)
        if self.rules.pack:
            alerts += self._check_pack(now, dogs)
        self._forget_missing({d.dog_id for d in dogs})
        return alerts

    # -- rules -----------------------------------------------------------------

    def _check_zones(self, now, dogs, width, height) -> list[Alert]:
        out = []
        for dog in dogs:
            inside_ids = {z.id for z in self.zones_containing(dog.box, width, height)}
            for zone in self.zones:
                key = (dog.dog_id, zone.id)
                if zone.id in inside_ids:
                    self._inside_frames[key] = self._inside_frames.get(key, 0) + 1
                    if (self._inside_frames[key] == ZONE_FRAMES_REQUIRED
                            and self._ready(("zone", key), now, ZONE_COOLDOWN)):
                        out.append(Alert("zone_entered", f"Dog #{dog.dog_id} entered {zone.name}",
                                         dog_id=dog.dog_id, zone_id=zone.id))
                else:
                    self._inside_frames.pop(key, None)
        return out

    def _check_approach(self, now, dogs, people) -> list[Alert]:
        out = []
        for dog in dogs:
            if not people:
                self._gap_history.pop(dog.dog_id, None)
                continue
            dx, dy = centre(dog.box)
            box_h = max(1.0, dog.box[3] - dog.box[1])
            gap = min(math.hypot(dx - centre(p)[0], dy - centre(p)[1]) for p in people) / box_h
            hist = self._gap_history.setdefault(dog.dog_id, deque())
            hist.append((now, gap))
            while len(hist) > 2 and now - hist[1][0] >= APPROACH_WINDOW:
                hist.popleft()
            t0, gap0 = hist[0]
            closing = gap0 - gap
            if (dog.activity == RUNNING and now - t0 >= APPROACH_WINDOW * 0.8
                    and closing >= APPROACH_MIN_CLOSING and gap <= APPROACH_MAX_DISTANCE
                    and self._ready(("approach", dog.dog_id), now, APPROACH_COOLDOWN)):
                out.append(Alert("dog_running_at_person",
                                 f"Dog #{dog.dog_id} is running towards a person", dog_id=dog.dog_id))
        return out

    def _check_pack(self, now, dogs) -> list[Alert]:
        if len(dogs) >= self.rules.pack_size and self._ready(("pack",), now, PACK_COOLDOWN):
            ids = ", ".join(f"#{d.dog_id}" for d in dogs)
            return [Alert("dog_pack", f"{len(dogs)} dogs together ({ids})")]
        return []

    # -- helpers ---------------------------------------------------------------

    def _ready(self, key, now: float, cooldown: float) -> bool:
        last = self._last_fired.get(key)
        if last is not None and now - last < cooldown:
            return False
        self._last_fired[key] = now
        return True

    def _forget_missing(self, visible: set[int]) -> None:
        for key in [k for k in self._inside_frames if k[0] not in visible]:
            del self._inside_frames[key]
        for dog_id in [d for d in self._gap_history if d not in visible]:
            del self._gap_history[dog_id]
