"""
Tests for the session report (checkpoint 14): content, escaping, embedded
photos staying inside the storage folder, the API and the command line.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.db import Database
from backend.report import build_report, collect, main as report_main, thumbnail
from tests.test_api import LOCAL

NOW = time.time()


def photo(path, w=400, h=300):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((h, w, 3), 120, np.uint8))


def fill(db: Database, storage):
    dog = db.add_dog("cam1", 1, NOW - 600, 0.9)
    db.update_dog(dog, last_seen=NOW - 60, seconds_in={"RESTING": 300, "WALKING": 200, "RUNNING": 40},
                  max_speed=2.2, snapshot="dogs/dog_1.jpg")
    short = db.add_dog("cam1", 2, NOW - 100, 0.9)
    db.update_dog(short, last_seen=NOW - 99, seconds_in={"RESTING": 5, "WALKING": 0, "RUNNING": 0}, max_speed=0.1)
    for i in range(540):
        act = "RESTING" if i < 300 else "WALKING" if i < 500 else "RUNNING"
        db.add_observation(dog, NOW - 600 + i, (0.2 + i / 1000, 0.6), {"RESTING": 0.1, "WALKING": 0.8, "RUNNING": 2.0}[act],
                           act, 0.9)
    db.add_event("cam1", "zone_entered", "Dog #1 entered <script>alert(1)</script>", dog_id=dog,
                 snapshot="alerts/a1.jpg", ts=NOW - 300)
    db.add_event("cam1", "dog_pack", "3 dogs together", ts=NOW - 200)
    db.add_event("cam1", "dog_appeared", "Dog #1 appeared", dog_id=dog, ts=NOW - 600)    # not an alert
    db.add_event("cam1", "zone_entered", "old alert", ts=NOW - 7200)                     # outside the period
    photo(storage / "dogs" / "dog_1.jpg")
    photo(storage / "alerts" / "a1.jpg", 1280, 720)
    return dog


@pytest.fixture()
def setup(tmp_path):
    storage = tmp_path / "storage"
    db = Database(storage / "dogwatch.db")
    fill(db, storage)
    yield db, storage
    db.close()


def test_collect_numbers(setup):
    db, _ = setup
    d = collect(db, NOW - 3600, NOW)
    assert d["dogs_seen"] == 2 and d["alert_counts"] == {"zone_entered": 1, "dog_running_at_person": 0, "dog_pack": 1}
    assert d["activity_seconds"] == {"RESTING": 300, "WALKING": 200, "RUNNING": 40}
    assert d["activity_share"]["RESTING"] == pytest.approx(300 / 540, abs=1e-3)
    assert [a["message"][:6] for a in d["alerts"]] == ["3 dogs", "Dog #1"]
    assert d["dogs"][0]["id"] == 1 and sum(d["speeds"]) == 540
    assert sum(map(sum, d["grid"])) == 540


def test_report_content_and_escaping(setup):
    db, storage = setup
    html = build_report(db, storage, NOW - 3600, NOW,
                        models={"Detector": {"name": "yolo11n.pt", "metrics": {"mAP50": 0.91, "recall": 0.88}},
                                "Behaviour classifier": None})
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html          # messages are escaped
    assert "Alerts (2)" in html and "old alert" not in html
    assert "Dog #1" in html and "Dog #2" not in html                    # stays under 2 s are left out
    assert html.count("data:image/jpeg;base64,") == 2                    # alert photo + dog photo
    assert html.count("<svg") == 3 and "mAP50 0.91" in html
    assert "Resting 56%" in html


def test_thumbnails_are_small_and_stay_in_storage(setup, tmp_path):
    db, storage = setup
    src = thumbnail(storage, "alerts/a1.jpg", width=200)
    img = cv2.imdecode(np.frombuffer(__import__("base64").b64decode(src.split(",", 1)[1]), np.uint8), 1)
    assert img.shape[1] == 200 and img.shape[0] == 112
    photo(tmp_path / "secret.jpg")
    assert thumbnail(storage, "../secret.jpg") is None
    assert thumbnail(storage, "dogwatch.db") is None
    assert thumbnail(storage, "alerts/missing.jpg") is None and thumbnail(storage, None) is None


def test_empty_report(tmp_path):
    db = Database(tmp_path / "s" / "dogwatch.db")
    html = build_report(db, tmp_path / "s", NOW - 600, NOW)
    db.close()
    assert "No alerts." in html and "No dogs." in html and "Models" not in html


def test_report_api(tmp_path):
    storage = tmp_path / "st"
    app = create_app(AppSettings(storage_dir=str(storage), media_dir=str(tmp_path / "m")))
    with TestClient(app, client=LOCAL) as c:
        fill(app.state.db, storage)
        r = c.get("/api/report?minutes=60")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert "Alerts (2)" in r.text and "yolo11n.pt" in r.text
        assert "content-disposition" not in r.headers
        d = c.get("/api/report?minutes=60&download=true")
        assert 'filename="dogwatch_report_' in d.headers["content-disposition"]
        assert c.get("/api/report?minutes=0").status_code == 422


def test_report_needs_token_from_other_devices(tmp_path):
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m"),
                                 access_token="secret"))
    with TestClient(app, client=("192.168.1.50", 5000)) as c:
        assert c.get("/api/report").status_code == 401
        assert c.get("/api/report?token=secret").status_code == 200


def test_command_line(setup, tmp_path):
    db, storage = setup
    out = tmp_path / "r.html"
    assert report_main(["--storage", str(storage), "--minutes", "60", "--out", str(out)]) == out
    assert "Alerts (2)" in out.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        report_main(["--storage", str(tmp_path / "nowhere"), "--out", str(out)])
