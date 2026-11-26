"""
Tests for connecting a phone through its browser (/phone page + /ws/phone).

The phone is simulated: we send JPEG frames of a real dog photo over the
WebSocket, exactly as phone.html does, and check the server detects the dog.
"""

from __future__ import annotations

import ipaddress
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.cameras import PushCameraSource
from backend.phone import ensure_certificate, qr_svg
from tests.test_api import wait_for

ROOT = Path(__file__).resolve().parent.parent
DOG_IMAGE = ROOT / "legacy" / "dog_images" / "dog_ID_5_002.jpg"
LOCAL = ("127.0.0.1", 50000)
REMOTE = ("192.168.1.50", 50000)
TOKEN = "phone-token-1"


def dog_frame(x: int) -> bytes:
    dog = cv2.imread(str(DOG_IMAGE))
    dog = cv2.resize(dog, (int(dog.shape[1] * 200 / dog.shape[0]), 200))
    canvas = np.full((360, 640, 3), 200, np.uint8)
    canvas[80:280, x:x + dog.shape[1]] = dog
    ok, jpg = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpg.tobytes()


def make_app(tmp_path, phone_port=8443):
    return create_app(AppSettings(storage_dir=str(tmp_path / "storage"), media_dir=str(tmp_path),
                                  access_token=TOKEN, phone_port=phone_port))


# ----------------------------------------------------------------------------
# PushCameraSource
# ----------------------------------------------------------------------------

def test_push_camera_source():
    cam = PushCameraSource("Phone A").start()
    assert cam.is_running and cam.kind == "phone"
    assert cam.push_jpeg(dog_frame(10))
    assert not cam.push_jpeg(b"not a jpeg")
    assert not cam.push_jpeg(b"")
    assert cam.read().shape == (360, 640, 3)
    assert cam.frame_id == 1
    cam.stop()
    assert cam.finished and not cam.is_running
    assert not cam.push_jpeg(dog_frame(10))     # ignored after stop


# ----------------------------------------------------------------------------
# Certificate + QR
# ----------------------------------------------------------------------------

def test_certificate_covers_ip_and_is_reused(tmp_path):
    from cryptography import x509

    cert, key = ensure_certificate(tmp_path, ["192.168.1.20"])
    c = x509.load_pem_x509_certificate(cert.read_bytes())
    ips = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
    assert ipaddress.ip_address("192.168.1.20") in ips
    assert ipaddress.ip_address("127.0.0.1") in ips

    before = cert.read_bytes()
    ensure_certificate(tmp_path, ["192.168.1.20"])
    assert cert.read_bytes() == before              # same IP: reused (phone keeps trusting it)
    ensure_certificate(tmp_path, ["10.0.0.7"])
    assert cert.read_bytes() != before              # Wi-Fi changed: new certificate


def test_qr_svg():
    svg = qr_svg("https://192.168.1.20:8443/phone?token=x")
    assert "<svg" in svg and "path" in svg


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------

def test_phone_link_disabled_by_default(tmp_path):
    with TestClient(make_app(tmp_path, phone_port=None), client=LOCAL) as c:
        info = c.get("/api/phone-link").json()
        assert info["enabled"] is False and info["urls"] == [] and info["hint"]
        assert c.get("/api/phone-link/qr.svg").status_code == 404


def test_phone_link_contains_token(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.lan_ips", lambda: ["192.168.1.20"])
    with TestClient(make_app(tmp_path), client=LOCAL) as c:
        info = c.get("/api/phone-link").json()
        assert info["urls"] == [f"https://192.168.1.20:8443/phone?token={TOKEN}"]
        r = c.get(info["qr_url"])
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    # Another device can't read the link (it contains the token) without the token
    with TestClient(make_app(tmp_path), client=REMOTE) as remote:
        assert remote.get("/api/phone-link").status_code == 401


def test_phone_page_is_public_but_websocket_needs_token(tmp_path):
    with TestClient(make_app(tmp_path), client=REMOTE) as remote:
        r = remote.get("/phone")
        assert r.status_code == 200 and "Start camera" in r.text
        with pytest.raises(Exception):
            with remote.websocket_connect("/ws/phone") as ws:
                ws.receive_json()
        with remote.websocket_connect(f"/ws/phone?token={TOKEN}&name=Gate") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "ready" and msg["name"] == "Gate"


def test_phone_streams_frames_and_dog_is_detected(tmp_path):
    with TestClient(make_app(tmp_path), client=LOCAL) as c:
        with c.websocket_connect("/ws/phone?name=Test%20phone") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            sid = ready["id"]

            sources = c.get("/api/sources").json()
            assert [(s["id"], s["kind"], s["name"]) for s in sources] == [(sid, "phone", "Test phone")]

            ws.send_bytes(b"garbage")
            bad = ws.receive_json()
            assert bad["type"] == "ack" and bad["ok"] is False

            seen = None
            deadline = time.monotonic() + 30
            x = 10
            while time.monotonic() < deadline:
                ws.send_bytes(dog_frame(x))
                ack = ws.receive_json()
                assert ack["type"] == "ack" and ack["ok"] is True
                if ack["dogs"]:
                    seen = ack
                    break
                x = (x + 8) % 300
                time.sleep(0.05)
            assert seen, "phone frames never produced a dog detection"
            assert seen["dogs"][0]["activity"] in ("RESTING", "WALKING", "RUNNING")

            snap = c.get(f"/api/sources/{sid}/snapshot.jpg")
            assert snap.status_code == 200

        # Phone disconnected: its source disappears at once; the event is logged once the
        # detector thread has stopped (up to 5 s on a busy laptop), so allow time for that.
        assert wait_for(lambda: not c.get("/api/sources").json(), timeout=5), "phone source still listed"
        assert wait_for(lambda: "source_removed" in [e["type"] for e in c.get("/api/events").json()],
                        timeout=20), "phone source not removed after disconnect"


def test_phone_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.MAX_PHONES", 1)
    with TestClient(make_app(tmp_path), client=LOCAL) as c:
        with c.websocket_connect("/ws/phone") as first:
            assert first.receive_json()["type"] == "ready"
            with c.websocket_connect("/ws/phone") as second:
                msg = second.receive_json()
                assert msg["type"] == "error" and "phones connected" in msg["message"]
