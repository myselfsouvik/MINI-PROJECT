"""Tests for backend/behaviour.py (no model or camera needed)."""

import pytest

from backend.behaviour import RESTING, RUNNING, WALKING, BehaviourTracker, classify


def feed(tracker, track_id, speed_bh, box_h=100.0, seconds=3.0, fps=20, x0=100.0):
    """Move a box of height box_h at speed_bh box heights / second."""
    state = None
    for i in range(int(seconds * fps) + 1):
        t = i / fps
        x = x0 + speed_bh * box_h * t
        state, _ = tracker.update(track_id, (x, 50, x + box_h, 50 + box_h), t, 0.9)
    return state


def test_classify_thresholds():
    assert classify(0.0) == RESTING
    assert classify(0.8) == WALKING
    assert classify(3.0) == RUNNING


@pytest.mark.parametrize("speed,expected", [(0.0, RESTING), (0.8, WALKING), (3.0, RUNNING)])
def test_activity_from_motion(speed, expected):
    state = feed(BehaviourTracker(), 1, speed)
    assert state.activity == expected
    assert state.speed == pytest.approx(speed, rel=0.1, abs=0.02)


def test_speed_does_not_depend_on_distance_from_camera():
    near = feed(BehaviourTracker(), 1, 1.0, box_h=300)   # big box, close to camera
    far = feed(BehaviourTracker(), 1, 1.0, box_h=40)     # small box, far away
    assert near.speed == pytest.approx(far.speed, rel=0.05)


def test_smoothing_ignores_a_single_jump():
    tr = BehaviourTracker()
    state = feed(tr, 1, 0.0, seconds=2)
    # a few frames where the box wobbles by 10% of its height (normal detector jitter)
    for i, dx in enumerate([10, -10, 10]):
        state, _ = tr.update(1, (100 + dx, 50, 200 + dx, 150), 2.05 + i * 0.05, 0.9)
    assert state.activity == RESTING


def test_one_frame_spike_is_capped():
    tr = BehaviourTracker()
    feed(tr, 1, 0.0, seconds=2)
    # tracker glitch: box teleports 5 box heights in one frame
    state, _ = tr.update(1, (600, 50, 700, 150), 2.05, 0.9)
    assert state.activity != RUNNING


def test_time_per_activity_is_counted():
    state = feed(BehaviourTracker(), 1, 0.0, seconds=4)
    assert state.seconds_in[RESTING] == pytest.approx(4.0, abs=0.1)
    assert state.duration == pytest.approx(4.0, abs=0.1)


def test_new_and_expired_tracks():
    tr = BehaviourTracker(forget_after=3.0)
    _, new = tr.update(7, (0, 0, 10, 10), 0.0, 0.8)
    assert new
    _, new = tr.update(7, (1, 0, 11, 10), 0.1, 0.8)
    assert not new
    assert [s.track_id for s in tr.visible(0.2)] == [7]
    assert tr.expire(2.0) == []
    gone = tr.expire(3.5)
    assert [s.track_id for s in gone] == [7]
    assert tr.tracks == {}
