"""
Tests for speed tuning (checkpoint 15): the image-size setting and the
benchmark that recommends one.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.benchmark import SizeResult, main as bench_main, matched, read_frames, recommend, run, table
from backend.demo import make_demo_video
from tests.test_api import LOCAL

ROOT_MODEL = "models/yolo11n.pt"


def test_matched_is_one_to_one():
    ref = np.array([[0, 0, 10, 10], [20, 20, 30, 30]], float)
    assert matched(ref, np.array([[1, 1, 10, 10]], float)) == 1
    assert matched(ref, np.array([[0, 0, 10, 10], [0, 0, 10, 10]], float)) == 1      # two boxes, one dog
    assert matched(ref, ref.copy()) == 2
    assert matched(ref, np.zeros((0, 4))) == 0 and matched(np.zeros((0, 4)), ref) == 0


R = [SizeResult(320, 60, 0.5, 0.40), SizeResult(416, 40, 2.1, 0.92), SizeResult(512, 25, 2.6, 0.97),
     SizeResult(640, 12, 2.8, 1.0)]


def test_recommend():
    assert recommend(R, target_fps=10)[0].imgsz == 640                 # fast enough for full size
    best, why = recommend(R, target_fps=20)
    assert best.imgsz == 512 and "97%" in why
    assert recommend(R, target_fps=30)[0].imgsz == 416                  # 320 is fast but finds too few
    best, why = recommend(R, target_fps=100)
    assert best.imgsz == 320 and "fastest" in why                       # nothing qualifies
    assert "512 ← recommended" in table(R, R[2])


def test_read_frames_spreads_over_video(tmp_path):
    video = make_demo_video(tmp_path / "v.mp4", seconds=2, fps=10)
    frames = read_frames(video, 5)
    assert len(frames) == 5 and frames[0].shape == (600, 960, 3)
    with pytest.raises(RuntimeError):
        read_frames(tmp_path / "missing.mp4", 3)


def test_run_on_demo_frames(tmp_path):
    from ultralytics import YOLO

    frames = read_frames(make_demo_video(tmp_path / "v.mp4", seconds=2), 4)
    results = run(YOLO(ROOT_MODEL), frames, sizes=[416])
    assert [r.imgsz for r in results] == [416, 640]                     # 640 is always the reference
    ref = results[-1]
    assert ref.dogs_found == 1.0 and ref.dogs_per_frame >= 2 and ref.fps > 0
    assert 0 <= results[0].dogs_found <= 1


def test_command_line(tmp_path):
    video = make_demo_video(tmp_path / "v.mp4", seconds=2)
    out = bench_main(["--video", str(video), "--frames", "3", "--sizes", "512", "--json", str(tmp_path / "b.json")])
    assert out["recommended"] in (512, 640) and len(out["results"]) == 2
    assert json.loads((tmp_path / "b.json").read_text())["frames"] == 3
    with pytest.raises(SystemExit):
        bench_main(["--sizes", "500"])                                  # not a multiple of 32


# -- the setting ---------------------------------------------------------------------------------

def test_imgsz_setting(tmp_path):
    video = make_demo_video(tmp_path / "m" / "v.mp4", seconds=4)
    app = create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m"), imgsz=512),
                     initial_sources=[str(video)])
    with TestClient(app, client=LOCAL) as c:
        assert c.get("/api/settings").json()["imgsz"] == 512
        assert c.patch("/api/settings", json={"imgsz": 416}).json()["imgsz"] == 416
        for bad in (400, 96, 2048):
            assert c.patch("/api/settings", json={"imgsz": bad}).status_code == 422, bad
        manager = app.state.manager
        pipe = manager.get(c.get("/api/sources").json()[0]["id"])
        assert pipe.settings is manager.pipeline_settings and pipe.settings.imgsz == 416   # cameras use it live
