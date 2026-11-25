"""
Tests for the behaviour classifier pipeline (checkpoint 7): features,
clip -> features tool, training script, and the live server using the model.
"""

from __future__ import annotations

import json
import math

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.behaviour import RUNNING, RESTING, BehaviourTracker
from backend.features import FEATURE_NAMES, BehaviourModel, to_activity, window_features
from tests.test_api import DOG_IMAGE, LOCAL, wait_for
from training.behaviour import extract_features, train_classifier


# -- features ------------------------------------------------------------------

def boxes_moving(speed_bh=1.0, seconds=2.0, fps=15, h=100, w=150, scale=1.0):
    out = []
    for i in range(int(seconds * fps) + 1):
        t = i / fps
        x = 100 + speed_bh * h * t
        out.append((t, x * scale, 200 * scale, (x + w) * scale, (200 + h) * scale))
    return out


def test_features_of_still_and_moving_dog():
    still = window_features(boxes_moving(0))
    assert still["speed_mean"] == 0 and still["net_speed"] == 0 and still["aspect_mean"] == 1.5
    moving = window_features(boxes_moving(2.0))
    assert math.isclose(moving["net_speed"], 2.0, rel_tol=1e-6)
    assert math.isclose(moving["straightness"], 1.0) and moving["horizontal_share"] == 1.0
    assert set(moving) == set(FEATURE_NAMES)


def test_features_do_not_depend_on_resolution():
    a, b = window_features(boxes_moving(1.2)), window_features(boxes_moving(1.2, scale=2.5))
    for k in FEATURE_NAMES:
        assert math.isclose(a[k], b[k], rel_tol=1e-6, abs_tol=1e-9), k


def test_too_little_history_gives_none():
    assert window_features(boxes_moving(1, seconds=0.3)) is None
    assert window_features(boxes_moving(1)[:2]) is None


def test_label_to_activity():
    assert to_activity("SITTING") == "RESTING" and to_activity("running") == "RUNNING"
    assert to_activity("barking") is None


# -- tracker with a classifier ----------------------------------------------------

class FakeModel:
    def __init__(self, label="SITTING", fail=False):
        self.label, self.fail, self.calls = label, fail, 0

    def predict(self, feats):
        self.calls += 1
        if self.fail:
            raise RuntimeError("broken")
        return self.label, 0.9


def feed(tracker, speed_bh=3.0, seconds=3.0):
    state = None
    for t, *box in boxes_moving(speed_bh, seconds):
        state, _ = tracker.update(1, box, t, 0.9)
    return state


def test_classifier_label_overrides_speed_rule():
    model = FakeModel("SITTING")
    state = feed(BehaviourTracker(classifier=model))      # moving fast...
    assert state.label == "SITTING" and state.activity == RESTING   # ...but the model says sitting
    assert 3 <= model.calls <= 6                           # about every 0.5 s, not every frame


def test_without_classifier_speed_rule_is_used():
    state = feed(BehaviourTracker())
    assert state.label is None and state.activity == RUNNING


def test_unknown_label_keeps_speed_rule_activity():
    state = feed(BehaviourTracker(classifier=FakeModel("BARKING")))
    assert state.label == "BARKING" and state.activity == RUNNING


def test_broken_classifier_falls_back():
    model = FakeModel(fail=True)
    tracker = BehaviourTracker(classifier=model)
    state = feed(tracker)
    assert model.calls == 1 and tracker.classifier_failed and state.activity == RUNNING


# -- clips -> features -> trained model -> live server --------------------------------

def make_clip(path, speed_bh, y=150, seconds=4, fps=15):
    """Dog photo that stays still (speed 0) or moves back and forth at speed_bh box heights/s."""
    dog = cv2.imread(str(DOG_IMAGE))
    h = 200
    dog = cv2.resize(dog, (int(dog.shape[1] * h / dog.shape[0]), h))
    W, H = 1100, 520
    span = W - dog.shape[1] - 40
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for i in range(int(seconds * fps)):
        travel = speed_bh * h * i / fps
        x = 20 + int(abs((travel % (2 * span)) - span)) if speed_bh else 400
        canvas = np.full((H, W, 3), 200, np.uint8)
        canvas[y:y + h, x:x + dog.shape[1]] = dog
        writer.write(canvas)
    writer.release()
    return path


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("beh")
    clips = root / "clips"
    for label, speed in [("RESTING", 0), ("WALKING", 0.6), ("RUNNING", 2.5)]:
        (clips / label).mkdir(parents=True)
        for k, y in enumerate([60, 280]):
            make_clip(clips / label / f"{label.lower()}_{k}.mp4", speed, y=y)
    csv_path = root / "features.csv"
    extract_features.main(["--clips", str(clips), "--out", str(csv_path), "--step", "0.5"])
    model_path = root / "models" / "behaviour.joblib"
    meta = train_classifier.main(["--data", str(csv_path), "--out", str(model_path)])
    return {"root": root, "clips": clips, "csv": csv_path, "model": model_path, "meta": meta}


def test_extract_features_writes_rows_per_label(trained):
    import pandas as pd
    df = pd.read_csv(trained["csv"])
    assert list(df.columns) == extract_features.COLUMNS
    assert set(df["label"]) == {"RESTING", "WALKING", "RUNNING"}
    assert df.groupby("label")["clip"].nunique().min() == 2
    assert df.groupby("label").size().min() >= 6
    run, rest = df[df.label == "RUNNING"]["net_speed"].mean(), df[df.label == "RESTING"]["net_speed"].mean()
    assert run > 1.0 > 0.2 > rest


def test_training_saves_model_and_metrics(trained):
    meta = trained["meta"]
    assert "grouped by clip" in meta["split"]
    assert meta["accuracy"] >= 0.8 and meta["macro_f1"] >= 0.8
    assert meta["labels"] == ["RESTING", "RUNNING", "WALKING"]
    assert len(meta["confusion_matrix"]) == 3 and "vs_rule_baseline" in meta
    saved = json.loads(trained["model"].with_suffix(".json").read_text())
    assert saved["accuracy"] == meta["accuracy"]
    model = BehaviourModel(trained["model"])
    fast = window_features(boxes_moving(2.5, h=200))
    assert model.predict(fast)[0] == "RUNNING"


def test_server_uses_trained_model(trained, tmp_path):
    video = trained["clips"] / "RUNNING" / "running_0.mp4"
    settings = AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(trained["clips"]),
                           behaviour_model_path=str(trained["model"]))
    with TestClient(create_app(settings, initial_sources=[str(video)]), client=LOCAL) as c:
        s = c.get("/api/settings").json()
        assert s["behaviour_model_loaded"] and s["use_behaviour_model"]
        info = c.get("/api/models").json()["behaviour"]
        assert info["in_use"] and info["labels"] == ["RESTING", "RUNNING", "WALKING"]
        assert info["metrics"]["accuracy"] == trained["meta"]["accuracy"]

        labelled = wait_for(lambda: [d for d in c.get("/api/sources/cam1/live").json()["dogs"] if d["behaviour"]],
                            timeout=40)
        assert labelled and labelled[0]["behaviour"] in {"RESTING", "WALKING", "RUNNING"}
        assert labelled[0]["behaviour_conf"] > 0

        c.patch("/api/settings", json={"use_behaviour_model": False})
        assert wait_for(lambda: (d := c.get("/api/sources/cam1/live").json()["dogs"]) and d[0]["behaviour"] is None,
                        timeout=20)

        assert c.post("/api/models/behaviour/reload").status_code == 200


def test_server_without_model(tmp_path):
    settings = AppSettings(storage_dir=str(tmp_path / "s"), behaviour_model_path=str(tmp_path / "none.joblib"))
    with TestClient(create_app(settings), client=LOCAL) as c:
        assert c.get("/api/settings").json()["behaviour_model_loaded"] is False
        assert c.get("/api/models").json()["behaviour"]["loaded"] is False
        assert c.post("/api/models/behaviour/reload").status_code == 404


def test_broken_model_file_does_not_stop_server(tmp_path):
    bad = tmp_path / "behaviour.joblib"
    bad.write_bytes(b"not a model")
    settings = AppSettings(storage_dir=str(tmp_path / "s"), behaviour_model_path=str(bad))
    with TestClient(create_app(settings), client=LOCAL) as c:
        assert c.get("/api/health").json()["ok"]
        assert c.get("/api/settings").json()["behaviour_model_loaded"] is False
        assert c.post("/api/models/behaviour/reload").status_code == 400
