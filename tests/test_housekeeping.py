"""
Tests for storage housekeeping (checkpoint 13): what gets deleted, what is
always kept, that files outside the storage folder are never touched, the
API and automatic cleanup.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.db import Database
from backend.housekeeping import AutoCleaner, cleanup, usage
from tests.test_api import LOCAL, wait_for

DAY = 86400
NOW = time.time()


def touch(path, age_days=0.0, size=1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    t = NOW - age_days * DAY
    os.utime(path, (t, t))
    return path


def fill(db: Database, storage):
    """An old dog (10 days), a new dog, old and new events with files, and stray files."""
    old = db.add_dog("cam1", 1, NOW - 10 * DAY, 0.9)
    db.update_dog(old, last_seen=NOW - 10 * DAY + 60, seconds_in={"RESTING": 60, "WALKING": 0, "RUNNING": 0},
                  max_speed=0.1, snapshot="dogs/dog_old.jpg")
    new = db.add_dog("cam1", 2, NOW - 8 * DAY, 0.9)
    db.update_dog(new, last_seen=NOW - 60, seconds_in={"RESTING": 0, "WALKING": 10, "RUNNING": 0},
                  max_speed=1.0, snapshot="dogs/dog_new.jpg")
    for i in range(5):
        db.add_observation(old, NOW - 10 * DAY + i, (0.5, 0.5), 0.1, "RESTING", 0.9)
        db.add_observation(new, NOW - 8 * DAY + i, (0.5, 0.5), 1.0, "WALKING", 0.9)   # old rows, new dog
        db.add_observation(new, NOW - 60 + i, (0.5, 0.5), 1.0, "WALKING", 0.9)
    e = db.add_event("cam1", "zone_entered", "old alert", dog_id=old, snapshot="alerts/old.jpg", ts=NOW - 9 * DAY)
    db.set_event_clip(e, "alerts/old.webm")
    db.add_event("cam1", "zone_entered", "new alert", dog_id=new, snapshot="alerts/new.jpg", ts=NOW - 100)
    db.add_zone("file:x", "Gate", [[0, 0], [1, 0], [1, 1]])
    touch(storage / "dogs" / "dog_old.jpg", 10)
    touch(storage / "dogs" / "dog_new.jpg", 0)
    touch(storage / "alerts" / "old.jpg", 9)
    touch(storage / "alerts" / "old.webm", 9, size=5000)
    touch(storage / "alerts" / "new.jpg", 0)
    touch(storage / "alerts" / "stray_old.jpg", 20)         # nothing points to it
    touch(storage / "alerts" / "stray_new.jpg", 0)          # too new to touch
    return old, new


@pytest.fixture()
def setup(tmp_path):
    storage = tmp_path / "storage"
    db = Database(storage / "dogwatch.db")
    ids = fill(db, storage)
    yield db, storage, ids
    db.close()


def test_dry_run_changes_nothing(setup):
    db, storage, _ = setup
    before = db.counts()
    plan = cleanup(db, storage, days=7, dry_run=True)
    assert (plan["dogs"], plan["events"], plan["observations"]) == (1, 1, 10)
    assert plan["files"] == 4 and plan["freed_bytes"] == 8000
    assert db.counts() == before and (storage / "alerts" / "old.webm").exists()


def test_cleanup_deletes_old_and_keeps_new(setup):
    db, storage, (old, new) = setup
    r = cleanup(db, storage, days=7, vacuum=True)
    assert (r["dogs"], r["events"], r["files"]) == (1, 1, 4)
    assert db.get_dog(old) is None and db.get_dog(new) is not None
    assert len(db.observations(dog_id=new)) == 5                       # only its recent rows remain
    assert [e["message"] for e in db.list_events()] == ["new alert"]
    assert db.counts()["zones"] == 1                                   # zones are never deleted
    left = sorted(p.name for p in storage.rglob("*") if p.is_file() and p.suffix in (".jpg", ".webm"))
    assert left == ["dog_new.jpg", "new.jpg", "stray_new.jpg"]
    assert cleanup(db, storage, days=7)["files"] == 0                  # nothing more the second time


def test_never_deletes_outside_storage(setup, tmp_path):
    db, storage, _ = setup
    outside = touch(tmp_path / "precious.jpg", 30)
    other = touch(storage / "certs" / "old.pem", 30)                   # not a managed folder
    d = db.add_dog("cam1", 9, NOW - 30 * DAY, 0.5)
    db.update_dog(d, last_seen=NOW - 30 * DAY, seconds_in={"RESTING": 0, "WALKING": 0, "RUNNING": 0},
                  max_speed=0, snapshot="../precious.jpg")             # a bad path in the database
    db.add_event("cam1", "x", "bad", snapshot="certs/old.pem", ts=NOW - 30 * DAY)
    cleanup(db, storage, days=7)
    assert outside.exists() and other.exists()


def test_minimum_age(setup):
    db, storage, _ = setup
    with pytest.raises(ValueError):
        cleanup(db, storage, days=0.01)
    with pytest.raises(ValueError):
        AutoCleaner(db, storage, keep_days=0)


def test_usage(setup, tmp_path):
    db, storage, _ = setup
    media = tmp_path / "media"
    touch(media / "captures" / "a.mp4", size=2_000_000)
    u = usage(db, storage, media)
    assert u["rows"]["dogs"] == 2 and u["alert_files"]["files"] == 5
    assert u["captures"] == {"files": 1, "mb": 2.0} and u["uploads"]["files"] == 0
    assert u["database_mb"] >= 0 and u["disk_free_gb"] > 0


# -- API and automatic cleanup -------------------------------------------------------------------

def test_storage_api(tmp_path):
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m")))
    with TestClient(app, client=LOCAL) as c:
        fill(app.state.db, tmp_path / "st")
        s = c.get("/api/storage").json()
        assert s["rows"]["dogs"] == 2 and s["keep_days"] is None and s["last_auto_cleanup"] is None

        assert c.post("/api/storage/cleanup", json={"days": 0}).status_code == 422
        plan = c.post("/api/storage/cleanup", json={"days": 7, "dry_run": True}).json()
        assert plan["dogs"] == 1 and c.get("/api/storage").json()["rows"]["dogs"] == 2

        done = c.post("/api/storage/cleanup", json={"days": 7}).json()
        assert done["dogs"] == 1 and done["files"] == 4
        assert c.get("/api/storage").json()["rows"]["dogs"] == 1
        assert any(e["type"] == "storage_cleaned" for e in c.get("/api/events").json())


def test_storage_api_needs_token_from_other_devices(tmp_path):
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m"),
                                 access_token="secret"))
    with TestClient(app, client=("192.168.1.50", 5000)) as c:
        assert c.post("/api/storage/cleanup", json={"days": 7}).status_code == 401
        assert c.get("/api/storage").status_code == 401


def test_auto_cleanup_on_start(tmp_path):
    storage = tmp_path / "st"
    db = Database(storage / "dogwatch.db")
    fill(db, storage)
    db.close()
    app = create_app(AppSettings(storage_dir=str(storage), media_dir=str(tmp_path / "m"), keep_days=7))
    with TestClient(app, client=LOCAL) as c:
        s = wait_for(lambda: (x := c.get("/api/storage").json())["last_auto_cleanup"] and x, timeout=10)
        assert s["keep_days"] == 7 and s["last_auto_cleanup"]["dogs"] == 1 and s["rows"]["dogs"] == 1
