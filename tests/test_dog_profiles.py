"""
Tests for dog profiles and CSV export (checkpoint 12): sorting, a dog's path
and events, and exporting dogs / observations / events.
"""

from __future__ import annotations

import csv
import io
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.db import Database
from tests.test_api import LOCAL

NOW = time.time()


def fill(db: Database) -> tuple[int, int, int]:
    """Three dogs: a long resting one, a short fast runner and an old walker."""
    rest = db.add_dog("cam1", 1, NOW - 120, 0.9)
    db.update_dog(rest, last_seen=NOW - 10, seconds_in={"RESTING": 100, "WALKING": 10, "RUNNING": 0}, max_speed=0.3)
    run = db.add_dog("cam1", 2, NOW - 30, 0.8)
    db.update_dog(run, last_seen=NOW - 5, seconds_in={"RESTING": 0, "WALKING": 5, "RUNNING": 20}, max_speed=3.1)
    old = db.add_dog("cam2", 7, NOW - 7200, 0.7)
    db.update_dog(old, last_seen=NOW - 7000, seconds_in={"RESTING": 0, "WALKING": 200, "RUNNING": 0}, max_speed=0.9)
    for i in range(500):
        db.add_observation(run, NOW - 30 + i * 0.05, (i / 500, 0.5), 2.0, "RUNNING" if i > 100 else "WALKING", 0.8)
    db.add_observation(run, NOW - 4, (640.0, 360.0), 2.0, "RUNNING", 0.8)          # old pixel row: ignored in path
    db.add_event("cam1", "dog_appeared", "Dog #2 appeared", dog_id=run, ts=NOW - 30)
    db.add_event("cam1", "zone_entered", "Dog #2 entered Gate", dog_id=run, snapshot="alerts/a.jpg", ts=NOW - 20)
    db.add_event("cam1", "dog_appeared", "Dog #1 appeared", dog_id=rest, ts=NOW - 120)
    return rest, run, old


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


def test_sorting_and_time_filter(db):
    rest, run, old = fill(db)
    ids = lambda sort, **kw: [d["id"] for d in db.list_dogs(sort=sort, **kw)]       # noqa: E731
    assert ids("recent") == [run, rest, old]
    assert ids("longest") == [old, rest, run]
    assert ids("fastest") == [run, old, rest]
    assert ids("active") == [old, run, rest]
    assert ids("oldest") == [old, rest, run]
    assert ids("recent", since=NOW - 3600) == [run, rest]
    with pytest.raises(ValueError):
        db.list_dogs(sort="max_speed; DROP TABLE dogs")


def test_dog_path_is_thinned_and_normalised(db):
    _, run, _ = fill(db)
    path = db.dog_path(run, max_points=50)
    assert len(path) == 50
    assert path[0]["x"] == 0 and path[-1]["x"] == pytest.approx(499 / 500)       # first and last kept
    assert all(0 <= p["x"] <= 1 and 0 <= p["y"] <= 1 for p in path)
    assert [p["ts"] for p in path] == sorted(p["ts"] for p in path)
    assert {p["activity"] for p in path} == {"WALKING", "RUNNING"}
    assert len(db.dog_path(run)) == 300


def test_export_rows_stream_from_own_connection(db):
    fill(db)
    rows = db.export_rows("observations")
    header = next(rows)
    assert header[:4] == ["id", "dog_id", "source_id", "ts"]
    assert sum(1 for _ in rows) == 501
    dogs = list(db.export_rows("dogs", since=NOW - 3600))
    assert len(dogs) == 3 and "seconds_visible" in dogs[0]
    with pytest.raises(ValueError):
        next(db.export_rows("zones"))


# -- API -------------------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m")))
    with TestClient(app, client=LOCAL) as c:
        yield c, fill(app.state.db)


def test_dog_list_api(client):
    c, (rest, run, old) = client
    dogs = c.get("/api/dogs?sort=fastest").json()
    assert [d["id"] for d in dogs] == [run, old, rest]
    first = dogs[0]
    assert first["main_activity"] == "RUNNING" and first["activity_share"]["RUNNING"] == 0.8
    assert first["seconds_visible"] == 25.0
    assert [d["id"] for d in c.get("/api/dogs?minutes=60").json()] == [run, rest]
    assert c.get("/api/dogs?sort=bogus").status_code == 422


def test_dog_detail_api(client):
    c, (rest, run, old) = client
    d = c.get(f"/api/dogs/{run}").json()
    assert len(d["path"]) == 300 and len(d["observations"]) == 501
    assert [e["type"] for e in d["events"]] == ["zone_entered", "dog_appeared"]
    assert d["events"][0]["snapshot_url"] == "/media/alerts/a.jpg"
    assert "observations" not in c.get(f"/api/dogs/{run}?observations=false").json()
    assert c.get(f"/api/dogs/{old}").json()["path"] == []
    assert c.get("/api/dogs/9999").status_code == 404


def test_csv_export_api(client):
    c, (rest, run, old) = client
    r = c.get("/api/export/dogs.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="dogwatch_dogs_' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [int(x["id"]) for x in rows] == [rest, run, old]
    assert rows[1]["running_s"] == "20.0" and rows[1]["first_seen_local"][:4].isdigit()

    obs = list(csv.reader(io.StringIO(c.get("/api/export/observations.csv?minutes=60").text)))
    assert len(obs) == 1 + 501 and obs[0][-1] == "ts_local"
    events = list(csv.DictReader(io.StringIO(c.get("/api/export/events.csv").text)))
    assert len(events) == 3 and events[1]["type"] == "zone_entered"

    assert c.get("/api/export/zones.csv").status_code == 404
    assert c.get("/api/export/dogs.csv?minutes=-5").status_code == 422


def test_export_needs_token_from_other_devices(tmp_path):
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m"),
                                 access_token="secret"))
    with TestClient(app, client=("192.168.1.50", 5000)) as c:
        assert c.get("/api/export/dogs.csv").status_code == 401
        assert c.get("/api/export/dogs.csv?token=secret").status_code == 200
