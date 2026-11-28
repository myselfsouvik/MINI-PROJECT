"""
Tests for demo-day features (checkpoint 8): serving the built React dashboard,
the backup demo video, the demo zone and the setup doctor.
"""

from __future__ import annotations

import socket
from argparse import Namespace
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient

from backend import doctor
from backend.app import AppSettings, create_app
from backend.demo import DEMO_ZONE, make_demo_video
from backend.server import add_demo_zone
from tests.test_api import LOCAL, REMOTE, ROOT, TOKEN, wait_for


# -- serving the React dashboard ------------------------------------------------

@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>REACT DASHBOARD</html>")
    (d / "assets" / "app.js").write_text("console.log('hi')")
    (tmp_path / "secret.txt").write_text("do not serve")
    return d


def make(tmp_path, frontend_dir):
    return create_app(AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(tmp_path),
                                  access_token=TOKEN, frontend_dir=str(frontend_dir)))


def test_dashboard_is_served_when_built(tmp_path, dist):
    with TestClient(make(tmp_path, dist), client=LOCAL) as c:
        assert "REACT DASHBOARD" in c.get("/").text
        assert 'id="dogwatch-console"' in c.get("/console").text
        js = c.get("/assets/app.js")
        assert js.text == "console.log('hi')"
        assert js.headers["content-type"].startswith("text/javascript")      # not text/plain from the Windows registry
        assert "REACT DASHBOARD" in c.get("/dogs/12").text          # client-side route
        assert c.get("/assets/missing.js").status_code == 404
        assert c.get("/api/nothing-here").status_code == 404           # API paths never get index.html
        assert c.get("/api/health").json()["ok"]


def test_dashboard_files_cannot_escape_dist(tmp_path, dist):
    with TestClient(make(tmp_path, dist), client=LOCAL) as c:
        for path in ["/../secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"]:
            r = c.get(path)
            assert "do not serve" not in r.text, path


def test_other_devices_load_dashboard_but_api_needs_token(tmp_path, dist):
    with TestClient(make(tmp_path, dist), client=REMOTE) as c:
        assert c.get("/").status_code == 200
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/settings").status_code == 200                    # client-side route
        for path in ["/api/health", "/media/x.jpg", "/docs", "/openapi.json"]:
            assert c.get(path).status_code == 401, path
        assert c.get("/api/health", headers={"X-Access-Token": TOKEN}).status_code == 200


def test_without_build_the_test_console_is_home(tmp_path):
    with TestClient(make(tmp_path, tmp_path / "no-dist"), client=LOCAL) as c:
        assert 'id="dogwatch-console"' in c.get("/").text
        assert c.get("/whatever").status_code == 404
    with TestClient(make(tmp_path, tmp_path / "no-dist"), client=REMOTE) as c:
        assert c.get("/whatever").status_code == 401                    # unknown paths stay locked


# -- demo video and zone ---------------------------------------------------------------

def test_demo_video_has_three_detectable_dogs(tmp_path):
    video = make_demo_video(tmp_path / "demo.mp4", seconds=2)
    cap = cv2.VideoCapture(str(video))
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 30
    ok, frame = cap.read()
    cap.release()
    assert ok and frame.shape[:2] == (600, 960)

    from ultralytics import YOLO
    result = YOLO(str(ROOT / "models" / "yolo11n.pt"))(frame, classes=[16], conf=0.5, verbose=False)[0]
    assert len(result.boxes) == 3


def test_demo_zone_added_once_and_used(tmp_path):
    video = make_demo_video(tmp_path / "demo.mp4", seconds=4)
    app = create_app(AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(tmp_path)),
                     initial_sources=[str(video)])
    add_demo_zone(app, video)
    add_demo_zone(app, video)
    with TestClient(app, client=LOCAL) as c:
        zones = c.get("/api/sources/cam1/zones").json()
        assert [z["name"] for z in zones] == [DEMO_ZONE["name"]]
        # Three dogs at once: the pack alert fires.
        assert wait_for(lambda: [a for a in c.get("/api/alerts").json() if a["type"] == "dog_pack"], timeout=40)


# -- doctor -------------------------------------------------------------------------------

def test_doctor_passes_on_this_machine():
    args = Namespace(model=str(ROOT / "models" / "yolo11n.pt"), quick=True, port=free_port(),
                     phone=False, phone_port=8443, cameras=False)
    checks = doctor.run_checks(args)
    assert [c for c in checks if c.status == doctor.FAIL] == []
    assert {"Python", "Packages", "Detector", "Storage", "Dashboard"} <= {c.name for c in checks}


def test_doctor_reports_problems():
    missing = doctor.check_model(Path("no/such/model.pt"))
    assert missing[0].status == doctor.FAIL and "not found" in missing[0].detail and missing[0].fix
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        check = doctor.check_port(busy, "dashboard")
        assert check.status == doctor.FAIL and f"--port {busy + 1}" in check.fix


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
