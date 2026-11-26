"""
Turn labelled video clips into a feature table for the behaviour classifier.

Put short clips (3-20 s, one behaviour per clip) into one folder per label:

    datasets/behaviour_clips/
        RESTING/  lying_gate_01.mp4  sitting_02.mp4 ...
        WALKING/  ...
        RUNNING/  ...

Then run (from the repo root):

    python -m training.behaviour.extract_features --clips datasets/behaviour_clips --out datasets/behaviour_features.csv

Each clip goes through the same YOLO detector + tracker as the live server.
For every tracked dog, one row of movement features (backend/features.py) is
written every --step seconds of video, using the last --window seconds.
Times come from the video's frame rate, not the clock, so a slow laptop gives
the same features as a fast one.

Label names are free: RESTING/WALKING/RUNNING, or finer ones like LYING,
SITTING, STANDING. See backend/features.py ACTIVITY_FOR_LABEL for how they map
onto the dashboard's three activities.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict, deque
from pathlib import Path

import cv2

from backend.features import FEATURE_NAMES, FEATURE_WINDOW, window_features
from backend.pipeline import class_ids

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "models" / "yolo11n.pt"
VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
COLUMNS = ["clip", "label", "track_id", "t"] + FEATURE_NAMES


def extract_clip(video: Path, label: str, model_path: str | Path = DEFAULT_MODEL,
                 window: float = FEATURE_WINDOW, step: float = 0.5, stride: int = 1,
                 confidence: float = 0.4) -> list[dict]:
    """Feature rows for every dog tracked in one clip."""
    from ultralytics import YOLO

    model = YOLO(str(model_path))          # fresh model = fresh tracker for each clip
    dog_cls, _ = class_ids(model.names)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Can't open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    samples: dict[int, deque] = defaultdict(deque)
    last_row: dict[int, float] = {}
    rows, index = [], -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            index += 1
            if index % stride:
                continue
            t = index / fps
            result = model.track(frame, persist=True, classes=[dog_cls], conf=confidence,
                                 tracker="bytetrack.yaml", verbose=False)[0]
            boxes = result.boxes
            if boxes is None or boxes.id is None:
                continue
            for box, tid in zip(boxes.xyxy.cpu().numpy(), boxes.id.cpu().numpy().astype(int)):
                tid = int(tid)
                hist = samples[tid]
                hist.append((t, *(float(v) for v in box)))
                while hist and t - hist[0][0] > window:
                    hist.popleft()
                if t - last_row.get(tid, -1e9) < step:
                    continue
                feats = window_features(hist)
                if feats is None:
                    continue
                last_row[tid] = t
                rows.append({"clip": video.name, "label": label, "track_id": tid,
                             "t": round(t, 2), **{k: round(v, 5) for k, v in feats.items()}})
    finally:
        cap.release()
    return rows


def find_clips(folder: Path) -> list[tuple[Path, str]]:
    """(clip, label) for every video in <folder>/<label>/."""
    out = []
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        for f in sorted(sub.rglob("*")):
            if f.suffix.lower() in VIDEO_TYPES:
                out.append((f, sub.name.upper()))
    return out


def write_rows(rows: list[dict], out: Path, append: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not (append and out.exists())
    with open(out, "w" if new_file else "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--clips", type=Path, help="folder with one sub-folder per label")
    src.add_argument("--video", type=Path, help="a single clip (use with --label)")
    p.add_argument("--label", help="label for --video")
    p.add_argument("--out", type=Path, default=ROOT / "datasets" / "behaviour_features.csv")
    p.add_argument("--append", action="store_true", help="add to an existing CSV instead of replacing it")
    p.add_argument("--model", default=str(DEFAULT_MODEL), help="detector weights")
    p.add_argument("--window", type=float, default=FEATURE_WINDOW, help="seconds of history per row")
    p.add_argument("--step", type=float, default=0.5, help="seconds between rows")
    p.add_argument("--stride", type=int, default=1, help="use every Nth frame (faster)")
    p.add_argument("--conf", type=float, default=0.4)
    args = p.parse_args(argv)

    if args.video:
        if not args.label:
            p.error("--video needs --label")
        clips = [(args.video, args.label.upper())]
    else:
        clips = find_clips(args.clips)
        if not clips:
            p.error(f"No videos found in sub-folders of {args.clips}")

    all_rows = []
    for clip, label in clips:
        rows = extract_clip(clip, label, args.model, args.window, args.step, args.stride, args.conf)
        print(f"{label:>10}  {clip.name}: {len(rows)} rows")
        all_rows += rows
    write_rows(all_rows, args.out, args.append)
    counts = defaultdict(int)
    for r in all_rows:
        counts[r["label"]] += 1
    print(f"Wrote {len(all_rows)} rows to {args.out}  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
