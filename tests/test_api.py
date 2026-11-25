"""
End-to-end tests for the FastAPI backend.

A short video of a real dog photo moving across the frame is generated, added
as a camera source, and the API is checked: live detections, MJPEG stream,
stored dogs, snapshots and events. Uses the real YOLO model, so it takes
~30 s on a laptop CPU.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app

ROOT = Path(__file__).resolve().parent.parent
DOG_IMAGE = ROOT / "legacy" / "dog_images" / "dog_ID_5_002.jpg"


def make_moving_dog_video(path: Path, seconds: float = 6, fps: int = 15) -> Path:
    dog = cv2.imread(str(DOG_IMAGE))
    h = 200
    dog = cv2.resize(dog, (int(dog.shape[1] * h / dog.shape[0]), h))
    W, H = 960, 400
    frames = int(seconds * fps)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for i in range(frames):
        canvas = np.full((H, W, 3), 200, np.uint8)
        x = int(20 + (W - dog.shape[1] - 40) * i / (frames - 1))
        canvas[100:100 + h, x:x + dog.shape[1]] = dog
        writer.write(canvas)
    writer.release()
    return path


def wait_for(fn, timeout=30.0, every=0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(every)
    return None


LOCAL = ("127.0.0.1", 50000)        # a request from this computer
REMOTE = ("192.168.1.50", 50000)    # a request from another device on the Wi-Fi
TOKEN = "test-token-123"


def make_app(tmp_path):
    return create_app(AppSettings(storage_dir=str(tmp_path / "storage"),
                                  media_dir=str(tmp_path), access_token=TOKEN))


@pytest.fixture()
def client(tmp_path):
    with TestClient(make_app(tmp_path), client=LOCAL) as c:
        yield c


@pytest.fixture()
def dog_video(tmp_path):
    return make_moving_dog_video(tmp_path / "dog.mp4")


def test_health_and_settings(client):
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/settings").json()["confidence"] == 0.5
    r = client.patch("/api/settings", json={"confidence": 0.4})
    assert r.status_code == 200 and r.json()["confidence"] == 0.4
    assert client.patch("/api/settings", json={"confidence": 2}).status_code == 422


def test_test_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "DogWatch" in r.text


def test_bad_sources_are_rejected(client):
    assert client.post("/api/sources", json={"source": "no_such_file.mp4"}).status_code == 400
    r = client.post("/api/sources/phone", json={"ip": "127.0.0.1", "port": 1})
    assert r.status_code == 400 and "Could not open stream" in r.json()["detail"]
    assert client.get("/api/sources/cam99/live").status_code == 404


def test_full_flow_with_moving_dog(client, dog_video):
    r = client.post("/api/sources", json={"source": str(dog_video), "name": "Test video"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["name"] == "Test video"

    # Adding the same video twice is refused
    assert client.post("/api/sources", json={"source": str(dog_video)}).status_code == 400

    # 1. Live detections
    live = wait_for(lambda: (d := client.get(f"/api/sources/{sid}/live").json())["dogs"] and d)
    assert live, "no dog detected in the live feed"
    dog = live["dogs"][0]
    assert dog["confidence"] >= 0.5
    assert dog["activity"] in ("RESTING", "WALKING", "RUNNING")
    assert live["frame_width"] == 960

    # 2. Snapshot + MJPEG stream
    snap = client.get(f"/api/sources/{sid}/snapshot.jpg")
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
    with client.stream("GET", f"/api/sources/{sid}/stream.mjpg") as stream:
        first = next(stream.iter_bytes())
        assert b"--frame" in first

    # 3. The dog is stored once it has been tracked for > 1 s
    dogs = wait_for(lambda: client.get("/api/dogs").json())
    assert dogs, "dog was not stored"
    d = dogs[0]
    assert d["snapshot_url"]
    img = client.get(d["snapshot_url"])
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"

    detail = client.get(f"/api/dogs/{d['id']}").json()
    assert detail["observations"], "no observations stored"

    # The dog moves steadily across the frame, so it should be walking/running at some point
    moving = wait_for(lambda: any(o["activity"] != "RESTING"
                                  for o in client.get(f"/api/dogs/{d['id']}").json()["observations"]),
                      timeout=15)
    assert moving, "steadily moving dog never classified as moving"

    events = client.get("/api/events").json()
    types = {e["type"] for e in events}
    assert {"source_added", "dog_appeared"} <= types

    stats = client.get("/api/stats/activity").json()["seconds"]
    assert sum(stats.values()) >= 1

    # 4. Source list + removal
    listed = client.get("/api/sources").json()
    assert [s["id"] for s in listed] == [sid]
    assert client.delete(f"/api/sources/{sid}").status_code == 204
    assert client.get("/api/sources").json() == []
    types = {e["type"] for e in client.get("/api/events").json()}
    assert "dog_left" in types and "source_removed" in types


def test_websocket_pushes_live_state(client, dog_video):
    sid = client.post("/api/sources", json={"source": str(dog_video)}).json()["id"]
    with client.websocket_connect("/ws/live") as ws:
        msg = ws.receive_json()
        assert sid in msg["sources"]
        assert "events" in msg


# ----------------------------------------------------------------------------
# Security: access token and source restrictions
# ----------------------------------------------------------------------------

def test_other_devices_need_the_token(tmp_path):
    with TestClient(make_app(tmp_path), client=REMOTE) as remote:
        assert remote.get("/").status_code == 200                       # page itself is fine
        assert remote.get("/api/sources").status_code == 401
        assert remote.get("/api/sources", headers={"X-Access-Token": "wrong"}).status_code == 401
        assert remote.get("/api/sources", headers={"X-Access-Token": TOKEN}).status_code == 200
        assert remote.get(f"/api/health?token={TOKEN}").status_code == 200
        assert remote.get("/media/dogs/dog_1.jpg").status_code == 401
        with pytest.raises(Exception):
            with remote.websocket_connect("/ws/live") as ws:
                ws.receive_json()
        with remote.websocket_connect(f"/ws/live?token={TOKEN}") as ws:
            assert "sources" in ws.receive_json()


def test_without_a_token_only_this_computer_can_connect(tmp_path):
    app = create_app(AppSettings(storage_dir=str(tmp_path / "s"), media_dir=str(tmp_path)))
    with TestClient(app, client=REMOTE) as remote:
        assert remote.get("/api/health", headers={"X-Access-Token": ""}).status_code == 401
    with TestClient(app, client=LOCAL) as local:
        assert local.get("/api/health").status_code == 200


def test_video_files_must_be_in_media_folder(client, tmp_path):
    outside = tmp_path.parent / "outside_media.mp4"
    outside.write_bytes(b"x")
    try:
        r = client.post("/api/sources", json={"source": str(outside)})
        assert r.status_code == 400 and "media folder" in r.json()["detail"]
        # Paths that escape the folder with ".." are caught too
        sneaky = str(tmp_path / ".." / "outside_media.mp4")
        assert client.post("/api/sources", json={"source": sneaky}).status_code == 400
    finally:
        outside.unlink()


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data",   # cloud metadata (link-local)
    "http://224.0.0.1/video",                   # multicast
    "http://0.0.0.0:8080/video",
])
def test_unsafe_stream_addresses_rejected(client, url):
    r = client.post("/api/sources", json={"source": url})
    assert r.status_code == 400 and "not allowed" in r.json()["detail"]


def test_other_devices_cannot_point_camera_at_this_computer(tmp_path):
    with TestClient(make_app(tmp_path), client=REMOTE, headers={"X-Access-Token": TOKEN}) as remote:
        r = remote.post("/api/sources", json={"source": "http://127.0.0.1:8000/api/health"})
        assert r.status_code == 400 and "localhost" in r.json()["detail"]
        r = remote.post("/api/sources/phone", json={"ip": "127.0.0.1"})
        assert r.status_code == 400
