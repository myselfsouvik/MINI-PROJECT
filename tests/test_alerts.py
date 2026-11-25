"""
Tests for zones and alerts: the rule engine on its own (fast), then the API
with a real video where a dog walks into a zone (uses the YOLO model).
"""

from __future__ import annotations

from backend.alerts import (APPROACH_COOLDOWN, PACK_COOLDOWN, ZONE_FRAMES_REQUIRED, AlertEngine,
                            AlertRules, DogView, Zone, point_in_polygon)
from backend.behaviour import RESTING, RUNNING
from tests.test_api import client, dog_video, wait_for  # noqa: F401  (pytest fixtures)

W, H = 1000, 500
RIGHT_HALF = Zone(1, "Gate", [(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)])


def box_at(x, y=400, w=100, h=100):
    """A dog box whose feet (bottom centre) are at (x, y) in pixels."""
    return (x - w / 2, y - h, x + w / 2, y)


# -- geometry ------------------------------------------------------------------

def test_point_in_polygon():
    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert point_in_polygon(0.5, 0.5, square)
    assert not point_in_polygon(1.5, 0.5, square)
    triangle = [(0, 0), (1, 0), (0, 1)]
    assert point_in_polygon(0.2, 0.2, triangle)
    assert not point_in_polygon(0.8, 0.8, triangle)


def test_zone_uses_the_dogs_feet():
    engine = AlertEngine(zones=[RIGHT_HALF])
    # Box reaches well into the zone, but the feet (x = 480) are still outside.
    assert engine.zones_containing(box_at(480, w=300), W, H) == []
    assert [z.id for z in engine.zones_containing(box_at(700), W, H)] == [1]


# -- zone rule -------------------------------------------------------------------

def test_zone_alert_after_a_few_frames_and_only_once():
    engine = AlertEngine(zones=[RIGHT_HALF])
    t, fired = 0.0, []
    for _ in range(ZONE_FRAMES_REQUIRED + 10):
        t += 0.1
        fired += engine.evaluate(t, [DogView(7, box_at(700), RESTING)], [], W, H)
    assert [a.type for a in fired] == ["zone_entered"]
    assert fired[0].dog_id == 7 and "Gate" in fired[0].message


def test_zone_ignores_a_single_frame_of_jitter():
    engine = AlertEngine(zones=[RIGHT_HALF])
    out = []
    for i, x in enumerate([300, 700, 300, 300, 700, 300]):
        out += engine.evaluate(i * 0.1, [DogView(1, box_at(x), RESTING)], [], W, H)
    assert out == []


def test_zone_cooldown_then_fires_again():
    engine = AlertEngine(zones=[RIGHT_HALF])

    def visit(start):
        fired = []
        for i in range(ZONE_FRAMES_REQUIRED + 2):
            fired += engine.evaluate(start + i * 0.1, [DogView(1, box_at(700), RESTING)], [], W, H)
        engine.evaluate(start + 1, [DogView(1, box_at(200), RESTING)], [], W, H)   # walks out
        return fired

    assert len(visit(0)) == 1
    assert len(visit(5)) == 0          # back in within the cooldown
    assert len(visit(100)) == 1        # long after: alert again


def test_zone_rule_can_be_switched_off():
    engine = AlertEngine(rules=AlertRules(zone=False), zones=[RIGHT_HALF])
    out = []
    for i in range(10):
        out += engine.evaluate(i * 0.1, [DogView(1, box_at(700), RESTING)], [], W, H)
    assert out == []


# -- running at a person ------------------------------------------------------------

def run_towards(engine, activity, start_x=100, step=40, person_x=900, frames=15):
    person = box_at(person_x, w=60, h=170)
    out = []
    for i in range(frames):
        out += engine.evaluate(i * 0.1, [DogView(3, box_at(start_x + step * i), activity)], [person], W, H)
    return out


def test_running_dog_closing_in_on_person_alerts():
    out = run_towards(AlertEngine(), RUNNING)
    assert [a.type for a in out] == ["dog_running_at_person"]


def test_resting_or_moving_away_does_not_alert():
    assert run_towards(AlertEngine(), RESTING) == []
    assert run_towards(AlertEngine(), RUNNING, start_x=700, step=-40) == []   # running away
    assert run_towards(AlertEngine(), RUNNING, frames=15, person_x=5000) == []  # far away


def test_approach_has_a_cooldown():
    engine = AlertEngine()
    assert len(run_towards(engine, RUNNING)) == 1
    assert len(run_towards(engine, RUNNING)) == 0
    assert APPROACH_COOLDOWN > 1


# -- pack -------------------------------------------------------------------------

def test_pack_of_three_dogs():
    engine = AlertEngine()
    two = [DogView(i, box_at(100 + 200 * i), RESTING) for i in range(2)]
    three = [DogView(i, box_at(100 + 200 * i), RESTING) for i in range(3)]
    assert engine.evaluate(0, two, [], W, H) == []
    out = engine.evaluate(1, three, [], W, H)
    assert [a.type for a in out] == ["dog_pack"] and "3 dogs" in out[0].message
    assert engine.evaluate(2, three, [], W, H) == []                   # cooldown
    assert len(engine.evaluate(2 + PACK_COOLDOWN, three, [], W, H)) == 1


def test_pack_size_setting():
    engine = AlertEngine(rules=AlertRules(pack_size=2))
    two = [DogView(i, box_at(100 + 200 * i), RESTING) for i in range(2)]
    assert len(engine.evaluate(0, two, [], W, H)) == 1


# -- API ----------------------------------------------------------------------------

def test_zone_api_validation(client):
    assert client.get("/api/sources/nope/zones").status_code == 404
    assert client.post("/api/sources/nope/zones",
                       json={"name": "x", "points": [[0, 0], [1, 0], [1, 1]]}).status_code == 404
    assert client.delete("/api/zones/999").status_code == 404


def test_alert_settings(client):
    s = client.get("/api/settings").json()
    assert s["alert_zone"] and s["alert_approach"] and s["alert_pack"] and s["pack_size"] == 3
    r = client.patch("/api/settings", json={"alert_pack": False, "pack_size": 4})
    assert r.json()["alert_pack"] is False and r.json()["pack_size"] == 4
    assert client.patch("/api/settings", json={"pack_size": 1}).status_code == 422


def test_dog_walking_into_zone_raises_alert(client, dog_video):
    src = client.post("/api/sources", json={"source": str(dog_video), "loop": False})
    assert src.status_code == 201, src.text
    sid = src.json()["id"]

    # Bad zones are refused.
    assert client.post(f"/api/sources/{sid}/zones", json={"name": "x", "points": [[0, 0], [1, 1]]}).status_code == 422
    assert client.post(f"/api/sources/{sid}/zones",
                       json={"name": "x", "points": [[0, 0], [2, 0], [1, 1]]}).status_code == 400

    # The dog walks left to right; the zone is the right-hand side of the frame.
    zone = client.post(f"/api/sources/{sid}/zones",
                       json={"name": "School gate", "points": [[0.6, 0], [1, 0], [1, 1], [0.6, 1]]})
    assert zone.status_code == 201, zone.text
    zone_id = zone.json()["id"]
    assert [z["name"] for z in client.get(f"/api/sources/{sid}/zones").json()] == ["School gate"]

    alerts = wait_for(lambda: client.get("/api/alerts").json(), timeout=60)
    assert alerts, "no zone alert was raised"
    alert = alerts[0]
    assert alert["type"] == "zone_entered" and "School gate" in alert["message"]
    assert alert["snapshot_url"]
    img = client.get(alert["snapshot_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    # Alerts also show up in the general event list.
    assert any(e["type"] == "zone_entered" for e in client.get("/api/events").json())

    assert client.delete(f"/api/zones/{zone_id}").status_code == 204
    assert client.get(f"/api/sources/{sid}/zones").json() == []
