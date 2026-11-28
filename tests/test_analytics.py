"""
Tests for analytics, video upload and model switching (checkpoint 6).
"""

from __future__ import annotations

import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.db import Database
from backend.pipeline import class_ids
from tests.test_api import LOCAL, ROOT, make_moving_dog_video, wait_for

STOCK_MODEL = ROOT / "models" / "yolo11n.pt"


# -- database analytics (fast) -------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


def fill(db, since, n=60):
    dog = db.add_dog("cam1", 1, since, 0.9)
    for i in range(n):
        activity = ["RESTING", "WALKING", "RUNNING"][i // 20]
        db.add_observation(dog, since + i, (i / n, 0.75), speed=i * 0.05,
                           activity=activity, confidence=0.9)
    return dog


def test_activity_timeline(db):
    t0 = time.time() - 100
    fill(db, t0)
    buckets = db.activity_timeline(t0, 30)
    assert len(buckets) == 2
    assert buckets[0]["RESTING"] == 20 and buckets[0]["WALKING"] == 10
    assert buckets[1]["WALKING"] == 10 and buckets[1]["RUNNING"] == 20
    assert sum(b["RESTING"] + b["WALKING"] + b["RUNNING"] for b in buckets) == 60


def test_speed_histogram_last_bin_holds_the_rest(db):
    t0 = time.time() - 100
    fill(db, t0)                                     # speeds 0 .. 2.95
    counts = db.speed_histogram(t0, bin_width=0.5, max_speed=2.0)
    assert len(counts) == 4 and sum(counts) == 60
    assert counts[0] == 10 and counts[-1] == 30     # 1.5 and above lands in the last bin


def test_position_grid(db):
    t0 = time.time() - 100
    fill(db, t0)
    # Old databases stored pixel positions; those are ignored, not crashed on.
    db.add_observation(1, t0 + 1, (640.0, 360.0), 0.1, "RESTING", 0.9)
    grid = db.position_grid(t0, cols=4, rows_=2)
    assert grid[0] == [0, 0, 0, 0]                    # nothing in the top half (y = 0.75)
    assert grid[1] == [15, 15, 15, 15]


def test_source_filter(db):
    t0 = time.time() - 100
    fill(db, t0)
    assert db.speed_histogram(t0, 0.5, 2.0, source_id="cam9") == [0, 0, 0, 0]


# -- model class numbers ---------------------------------------------------------

def test_class_ids_for_stock_and_fine_tuned_models():
    assert class_ids({0: "person", 1: "bicycle", 16: "dog"}) == (16, 0)
    assert class_ids({0: "dog"}) == (0, None)              # our fine-tuned single-class model
    assert class_ids({0: "street_dog"}) == (0, None)
    assert class_ids({0: "cat", 1: "Dog"}) == (1, None)
    with pytest.raises(ValueError):
        class_ids({0: "cat", 1: "bird"})


# -- API ---------------------------------------------------------------------------

@pytest.fixture()
def models_dir(tmp_path):
    folder = tmp_path / "models"
    folder.mkdir()
    shutil.copy(STOCK_MODEL, folder / "yolo11n.pt")
    shutil.copy(STOCK_MODEL, folder / "copy.pt")
    (folder / "copy.json").write_text(json.dumps({"mAP50": 0.81, "test_images": 120}))
    (folder / "notes.txt").write_text("not a model")
    return folder


@pytest.fixture()
def client(tmp_path, models_dir):
    settings = AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(tmp_path / "media"),
                           model_path=str(models_dir / "yolo11n.pt"), models_dir=str(models_dir))
    with TestClient(create_app(settings), client=LOCAL) as c:
        yield c


def test_stats_endpoints_when_empty(client):
    assert client.get("/api/stats/timeline").json()["buckets"] == []
    sp = client.get("/api/stats/speeds?bin_width=0.5&max_speed=2").json()
    assert sp["counts"] == [0, 0, 0, 0] and sp["edges"] == [0, 0.5, 1.0, 1.5, 2.0]
    heat = client.get("/api/stats/heatmap?cols=4&rows=3").json()
    assert heat["max"] == 0 and len(heat["grid"]) == 3 and len(heat["grid"][0]) == 4
    s = client.get("/api/stats/summary").json()
    assert s["dogs_seen"] == 0 and s["alerts"] == 0
    assert client.get("/api/stats/timeline?minutes=600&bucket=5").status_code == 400   # too many buckets


def test_timeline_can_start_on_whole_hours(client):
    # India is 330 minutes ahead of UTC: half-hour buckets must start on :00 or :30 there.
    t = client.get("/api/stats/timeline?minutes=1440&bucket=1800&align=true&utc_offset=330").json()
    assert (t["since"] + 330 * 60) % 1800 == 0
    assert t["count"] == 49                        # the 48 of the last 24 hours plus the one running now
    six = client.get("/api/stats/timeline?minutes=10080&bucket=21600&align=true&utc_offset=330").json()
    assert (six["since"] + 330 * 60) % 21600 == 0  # 00:00, 06:00, 12:00, 18:00 local
    plain = client.get("/api/stats/timeline?minutes=60&bucket=60").json()
    assert plain["count"] == 60


def test_upload_rejects_bad_files(client):
    assert client.post("/api/uploads?filename=evil.exe", content=b"MZ...").status_code == 400
    assert client.post("/api/uploads?filename=empty.mp4", content=b"").status_code == 400
    r = client.post("/api/uploads?filename=fake.mp4&start=1", content=b"not really a video")
    assert r.status_code == 400
    assert client.get("/api/uploads").json() == []          # failed uploads are cleaned up


def test_upload_path_tricks_stay_in_media_folder(client, tmp_path):
    r = client.post("/api/uploads?filename=..%2F..%2Foutside.mp4", content=b"x" * 10)
    assert r.status_code == 201
    assert r.json()["name"] == "outside.mp4"
    assert (tmp_path / "media" / "uploads" / "outside.mp4").exists()
    again = client.post("/api/uploads?filename=outside.mp4", content=b"y" * 10).json()
    assert again["name"] == "outside_1.mp4"                  # never overwrites


def test_upload_video_then_analytics(client, tmp_path):
    video = make_moving_dog_video(tmp_path / "walk.mp4")
    r = client.post("/api/uploads?filename=walk.mp4&start=1&loop=0", content=video.read_bytes())
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    assert [v["name"] for v in client.get("/api/uploads").json()] == ["walk.mp4"]

    # Wait until a few observations are stored (one per dog per second).
    heat = wait_for(lambda: (h := client.get(f"/api/stats/heatmap?cols=4&rows=4&source_id={sid}").json())["max"] >= 2 and h,
                    timeout=60)
    assert heat, "no positions recorded"
    # The dog in the test video is in the middle band of the frame.
    rows_with_dog = [i for i, row in enumerate(heat["grid"]) if any(row)]
    assert rows_with_dog and all(1 <= i <= 2 for i in rows_with_dog)

    assert sum(client.get(f"/api/stats/speeds?source_id={sid}").json()["counts"]) >= 2
    timeline = client.get("/api/stats/timeline?minutes=5&bucket=10").json()["buckets"]
    assert sum(b["RESTING"] + b["WALKING"] + b["RUNNING"] for b in timeline) >= 2


def test_models_list_and_switch(client, tmp_path):
    m = client.get("/api/models").json()
    assert m["current"] == "yolo11n.pt"
    assert [x["name"] for x in m["available"]] == ["copy.pt", "yolo11n.pt"]
    assert next(x for x in m["available"] if x["name"] == "copy.pt")["metrics"]["mAP50"] == 0.81

    assert client.post("/api/models/select", json={"name": "nope.pt"}).status_code == 404
    assert client.post("/api/models/select", json={"name": "notes.txt"}).status_code == 404
    assert client.post("/api/models/select", json={"name": "../storage/dogwatch.db"}).status_code == 404

    (tmp_path / "media").mkdir(exist_ok=True)
    video = make_moving_dog_video(tmp_path / "media" / "dog.mp4")
    sid = client.post("/api/sources", json={"source": str(video)}).json()["id"]
    assert wait_for(lambda: client.get(f"/api/sources/{sid}/live").json()["dogs"], timeout=40)

    r = client.post("/api/models/select", json={"name": "copy.pt"})
    assert r.status_code == 200, r.text
    assert r.json() == {"current": "copy.pt", "dog_class": 16, "person_class": 0, "cameras_updated": 1}
    assert client.get("/api/models").json()["current"] == "copy.pt"
    assert any(e["type"] == "model_changed" for e in client.get("/api/events").json())

    # Detection keeps working with the new model.
    before = {d["dog_id"] for d in client.get(f"/api/sources/{sid}/live").json()["dogs"]}
    new_dog = wait_for(lambda: [d for d in client.get(f"/api/sources/{sid}/live").json()["dogs"]
                                if d["dog_id"] not in before], timeout=40)
    assert new_dog, "no detections after switching model"
    assert client.get(f"/api/sources/{sid}/live").json()["status"] == "running"
