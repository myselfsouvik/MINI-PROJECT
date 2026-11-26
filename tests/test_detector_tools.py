"""
Tests for the detector tools (checkpoint 10): frame extraction with pre-labels,
the scoring maths, dataset loading and a full evaluation run.
"""

from __future__ import annotations

import json
import shutil

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.demo import DOGS, _load, make_demo_video
from tests.test_api import LOCAL
from training.detector import evaluate as ev
from training.detector.extract_frames import extract_video, main as extract_main, yolo_line

ROOT = ev.ROOT
MODEL = ROOT / "models" / "yolo11n.pt"


# -- scoring maths ----------------------------------------------------------------------------

def test_box_iou():
    a = np.array([[0, 0, 2, 2]], float)
    b = np.array([[0, 0, 2, 2], [1, 1, 3, 3], [5, 5, 6, 6]], float)
    assert ev.box_iou(a, b).round(3).tolist() == [[1.0, round(1 / 7, 3), 0.0]]
    assert ev.box_iou(a, np.zeros((0, 4))).shape == (1, 0)


def test_match_is_greedy_and_one_to_one():
    truth = np.array([[0, 0, 1, 1]], float)
    pred = np.array([[0, 0, 1, 1], [0, 0, 1, 1]], float)
    # Two boxes on one dog: only the more confident one counts, the other is a false alarm.
    assert ev.match(pred, np.array([0.4, 0.9]), truth, 0.5).tolist() == [False, True]


def test_average_precision():
    assert ev.average_precision(np.array([True, True]), np.array([0.9, 0.8]), 2) == pytest.approx(1.0)
    assert ev.average_precision(np.array([True]), np.array([0.9]), 2) == pytest.approx(51 / 101)
    # A false alarm ranked above the only hit halves the precision.
    assert ev.average_precision(np.array([False, True]), np.array([0.9, 0.8]), 1) == pytest.approx(0.5)
    assert ev.average_precision(np.zeros(0, bool), np.zeros(0), 3) == 0.0
    assert np.isnan(ev.average_precision(np.zeros(0, bool), np.zeros(0), 0))


def test_score_counts_false_alarms_on_empty_images(tmp_path):
    dog = np.array([[0.1, 0.1, 0.4, 0.5]])
    samples = [ev.Sample(tmp_path / "a.jpg", dog), ev.Sample(tmp_path / "b.jpg")]
    preds = [ev.Prediction(dog.copy(), np.array([0.9])),
             ev.Prediction(np.array([[0.5, 0.5, 0.7, 0.7], [0.1, 0.1, 0.2, 0.2]]), np.array([0.8, 0.3]))]
    r = ev.score(samples, preds, conf_thr=0.5)
    assert (r["true_positives"], r["false_positives"], r["missed"]) == (1, 1, 0)
    assert r["precision"] == 0.5 and r["recall"] == 1.0
    assert r["false_alarms_per_empty_image"] == 1.0          # the 0.3 box is below the threshold
    assert r["mAP50"] == pytest.approx(1.0)                  # the only hit is ranked first
    json.dumps(r)                                            # must be valid JSON (no NaN)


def test_score_with_no_dogs_is_valid_json(tmp_path):
    r = ev.score([ev.Sample(tmp_path / "a.jpg")], [ev.Prediction(np.zeros((0, 4)), np.zeros(0))])
    assert r["mAP50"] is None and r["recall"] == 0.0
    assert "NaN" not in json.dumps(r)


# -- dataset loading ---------------------------------------------------------------------------------

def _write_image(path, w=200, h=100):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((h, w, 3), 128, np.uint8))


def test_load_dataset_from_yaml_finds_dog_class_by_name(tmp_path):
    base = tmp_path / "ds"
    _write_image(base / "images" / "test" / "a.jpg")
    _write_image(base / "images" / "test" / "b.jpg")
    (base / "labels" / "test").mkdir(parents=True)
    # class 1 = dog here; class 0 = person must be ignored
    (base / "labels" / "test" / "a.txt").write_text("1 0.5 0.5 0.2 0.4\n0 0.1 0.1 0.1 0.1\n")
    yaml = base / "data.yaml"
    yaml.write_text("path: .\ntrain: images/train\nval: images/test\ntest: images/test\n"
                    "names:\n  0: person\n  1: dog\n")
    samples, name = ev.load_dataset(yaml, "test")
    assert name == "ds/test" and [s.image.name for s in samples] == ["a.jpg", "b.jpg"]
    assert samples[0].dogs.round(3).tolist() == [[0.4, 0.3, 0.6, 0.7]]
    assert len(samples[1].dogs) == 0                          # no label file = no dogs


def test_load_dataset_folder_and_errors(tmp_path):
    _write_image(tmp_path / "f" / "images" / "x.jpg")
    (tmp_path / "f" / "labels").mkdir()
    (tmp_path / "f" / "labels" / "x.txt").write_text("0 0.5 0.5 0.5 0.5\n")
    samples, _ = ev.load_dataset(tmp_path / "f")
    assert len(samples[0].dogs) == 1                          # no classes.txt: single class = dog

    (tmp_path / "f" / "classes.txt").write_text("cat\nperson\n")
    with pytest.raises(ValueError, match="dog"):
        ev.load_dataset(tmp_path / "f")
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="No images"):
        ev.load_dataset(tmp_path / "empty")


# -- frame extraction --------------------------------------------------------------------------------

def test_yolo_line():
    assert yolo_line(0, [10, 20, 50, 100], 100, 200) == "0 0.300000 0.300000 0.400000 0.400000"


def test_extract_frames_skips_duplicates(tmp_path):
    video = tmp_path / "still.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for _ in range(50):                                       # 5 s of the same picture
        writer.write(np.full((240, 320, 3), 90, np.uint8))
    writer.release()
    counts = extract_video(video, tmp_path / "out", model=None, every=1.0)
    assert counts["frames"] == 1 and counts["skipped_similar"] == 4
    counts = extract_video(video, tmp_path / "all", model=None, every=1.0, min_change=0)
    assert counts["frames"] == 5


def test_extract_frames_prelabels_dogs(tmp_path):
    video = make_demo_video(tmp_path / "demo.mp4", seconds=4)
    out = tmp_path / "frames"
    extract_main([str(tmp_path), "--out", str(out), "--every", "1", "--model", str(MODEL)])
    images = sorted((out / "images").glob("*.jpg"))
    labels = sorted((out / "labels").glob("*.txt"))
    assert len(images) == len(labels) >= 3
    assert (out / "classes.txt").read_text().split() == ["dog", "person"]
    boxes = [l.split() for l in labels[0].read_text().splitlines()]
    assert len(boxes) >= 2 and all(b[0] == "0" and len(b) == 5 for b in boxes)
    assert all(0 <= float(v) <= 1 for b in boxes for v in b[1:])
    img = cv2.imread(str(images[0]))
    assert img.shape[:2] == (600, 960)                       # full frames, not crops
    assert video.exists()


# -- full evaluation ------------------------------------------------------------------------------------

def make_test_set(base, n=6):
    """Dog photos pasted at known places, plus empty street images."""
    W, H = 960, 600
    rng = np.random.default_rng(0)
    for i in range(n):
        img = np.full((H, W, 3), 190, np.uint8)
        lines = []
        if i < n - 2:                                         # last two images have no dog
            for k, (name, y, h, _) in enumerate(DOGS[: 1 + i % 3]):
                dog = _load(name, h)
                dh, dw = dog.shape[:2]
                x = int(rng.integers(10, W - dw - 10))
                img[y:y + dh, x:x + dw] = dog
                lines.append(yolo_line(0, [x, y, x + dw, y + dh], W, H))
        _write_image(base / "images" / "test" / f"img{i}.jpg")
        cv2.imwrite(str(base / "images" / "test" / f"img{i}.jpg"), img)
        (base / "labels" / "test").mkdir(parents=True, exist_ok=True)
        (base / "labels" / "test" / f"img{i}.txt").write_text("\n".join(lines))
    (base / "data.yaml").write_text("path: .\ntest: images/test\nnames: [dog, person]\n")
    return base / "data.yaml"


def test_evaluate_end_to_end(tmp_path):
    data = make_test_set(tmp_path / "ds")
    models = tmp_path / "models"
    models.mkdir()
    model = models / "yolo11n.pt"
    shutil.copy(MODEL, model)                                 # metadata is written next to this copy
    table = tmp_path / "table.md"

    results = ev.main(["--data", str(data), "--models", str(model), "--table", str(table),
                       "--save-errors", str(tmp_path / "errors")])
    r = results[0]
    assert (r["images"], r["dogs"], r["empty_images"]) == (6, 7, 2)
    assert r["recall"] >= 0.75 and r["precision"] >= 0.75 and r["mAP50"] >= 0.75
    assert 0 <= r["mAP50_95"] <= r["mAP50"] and r["fps"] > 0
    assert r["false_alarms_per_empty_image"] == 0.0

    saved = json.loads((models / "yolo11n.json").read_text())
    assert saved["mAP50"] == r["mAP50"] and saved["dataset"] == "ds/test"
    assert "| yolo11n.pt |" in table.read_text()

    # The dashboard shows the saved numbers for the model.
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "media"),
                                 models_dir=str(models)))
    with TestClient(app, client=LOCAL) as c:
        listed = {m["name"]: m for m in c.get("/api/models").json()["available"]}
        assert listed["yolo11n.pt"]["metrics"]["recall"] == r["recall"]
