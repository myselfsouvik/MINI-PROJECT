"""
Movement features for the behaviour classifier, and loading the trained model.

A *window* is the last ~2 seconds of one dog's bounding boxes:
``[(t, x1, y1, x2, y2), ...]``. ``window_features`` turns it into a fixed set
of numbers that don't depend on camera resolution or on how far away the dog
is (distances are divided by the dog's box height):

    speed_mean / speed_max / speed_std   frame-to-frame speed, box heights per second
    net_speed                            start-to-end distance / time (ignores jitter)
    straightness                         net distance / path length (1 = straight line)
    horizontal_share                     share of movement that is sideways
    aspect_mean / aspect_std             box width / height (a lying dog is wider)
    height_change                        how fast the box grows (dog coming closer)
    height_jitter                        relative variation of box height
    fps                                  samples per second (lets the model discount noise)

The same function is used by the training tool (training/behaviour) and by the
live server, so the model sees identical features in both places.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

FEATURE_WINDOW = 2.0      # seconds of history per sample
MIN_WINDOW = 0.8          # need at least this much history to classify
MIN_SAMPLES = 4
MAX_SPEED = 6.0           # same cap as behaviour.py: faster = tracker glitch

FEATURE_NAMES = [
    "speed_mean", "speed_max", "speed_std", "net_speed", "straightness", "horizontal_share",
    "aspect_mean", "aspect_std", "height_change", "height_jitter", "fps",
]

# Whatever labels the classifier is trained on, the rest of the system (stats,
# alerts) still needs one of RESTING / WALKING / RUNNING.
ACTIVITY_FOR_LABEL = {
    "resting": "RESTING", "lying": "RESTING", "sitting": "RESTING", "standing": "RESTING",
    "sleeping": "RESTING", "eating": "RESTING",
    "walking": "WALKING", "trotting": "WALKING", "sniffing": "WALKING",
    "running": "RUNNING", "chasing": "RUNNING", "playing": "RUNNING",
}


def to_activity(label: str) -> str | None:
    return ACTIVITY_FOR_LABEL.get(str(label).lower())


def window_features(samples) -> dict | None:
    """Features for one window of boxes, or None if there isn't enough history."""
    if len(samples) < MIN_SAMPLES:
        return None
    a = np.asarray(samples, dtype=float)
    t = a[:, 0]
    duration = t[-1] - t[0]
    if duration < MIN_WINDOW:
        return None
    cx, cy = (a[:, 1] + a[:, 3]) / 2, (a[:, 2] + a[:, 4]) / 2
    w = np.maximum(a[:, 3] - a[:, 1], 1.0)
    h = np.maximum(a[:, 4] - a[:, 2], 1.0)
    h_mean = float(h.mean())

    dt = np.diff(t)
    ok = dt > 0
    dx, dy = np.diff(cx)[ok], np.diff(cy)[ok]
    step = np.hypot(dx, dy)
    h_pair = ((h[1:] + h[:-1]) / 2)[ok]
    speeds = np.minimum(step / h_pair / dt[ok], MAX_SPEED) if ok.any() else np.zeros(1)

    path = float(step.sum())
    net = math.hypot(cx[-1] - cx[0], cy[-1] - cy[0])
    moved = float(np.abs(dx).sum() + np.abs(dy).sum())
    aspect = w / h

    return {
        "speed_mean": float(speeds.mean()),
        "speed_max": float(speeds.max()),
        "speed_std": float(speeds.std()),
        "net_speed": min(net / h_mean / duration, MAX_SPEED),
        "straightness": net / path if path > 0 else 0.0,
        "horizontal_share": float(np.abs(dx).sum()) / moved if moved > 0 else 0.5,
        "aspect_mean": float(aspect.mean()),
        "aspect_std": float(aspect.std()),
        "height_change": float((h[-1] - h[0]) / h_mean / duration),
        "height_jitter": float(h.std() / h_mean),
        "fps": (len(t) - 1) / duration,
    }


class BehaviourModel:
    """
    A trained classifier saved by training/behaviour/train_classifier.py as a
    joblib file: {"model": sklearn estimator, "features": [...], "labels": [...]}.

    joblib files are pickles and can run code when loaded, exactly like YOLO
    .pt weights. Only load files we trained ourselves: the server only ever
    reads the fixed path models/behaviour.joblib, never a path from a request.
    """

    def __init__(self, path: str | Path):
        import joblib   # only needed when a model is actually used

        self.path = Path(path)
        bundle = joblib.load(self.path)
        self.model = bundle["model"]
        self.features: list[str] = list(bundle["features"])
        self.labels: list[str] = [str(x) for x in bundle.get("labels", self.model.classes_)]
        missing = set(self.features) - set(FEATURE_NAMES)
        if missing:
            raise ValueError(f"Model needs features this server doesn't compute: {sorted(missing)}")

    @classmethod
    def load_if_exists(cls, path: str | Path | None) -> "BehaviourModel | None":
        if not path or not Path(path).is_file():
            return None
        try:
            return cls(path)
        except Exception as e:   # a broken file must not stop the server
            print(f"[behaviour] could not load {path}: {e}")
            return None

    def predict(self, features: dict) -> tuple[str, float]:
        x = np.array([[features[name] for name in self.features]])
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba(x)[0]
            i = int(np.argmax(probs))
            return str(self.model.classes_[i]), float(probs[i])
        return str(self.model.predict(x)[0]), 1.0
