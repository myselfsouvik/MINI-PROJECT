"""
Find the best detector image size for this computer.

    python -m backend.benchmark                       # uses the demo video
    python -m backend.benchmark --video recordings/captures/street.mp4 --target-fps 8

Runs the detector on the same frames at several image sizes and reports, for
each size:

    FPS        frames per second on this computer
    dogs found share of the dogs found at 640 that this size also finds (IoU >= 0.5)

and recommends the largest size that is fast enough (--target-fps, default 10)
while still finding at least 90% of the dogs. Start the server with it:
start.bat --imgsz 416  (or change it live in the console).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SIZES = (320, 416, 512, 640)
REFERENCE = 640


@dataclass
class SizeResult:
    imgsz: int
    fps: float
    dogs_per_frame: float
    dogs_found: float          # share of the reference size's dogs also found (1.0 for the reference)


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda z: (z[:, 2] - z[:, 0]) * (z[:, 3] - z[:, 1])          # noqa: E731
    return inter / np.maximum(area(a)[:, None] + area(b)[None, :] - inter, 1e-9)


def matched(reference: np.ndarray, boxes: np.ndarray, thr: float = 0.5) -> int:
    """How many reference boxes have their own box in `boxes` (greedy, one-to-one)."""
    iou = _iou(reference, boxes)
    used, n = set(), 0
    for i in range(len(reference)):
        order = [j for j in np.argsort(-iou[i]) if j not in used and iou[i, j] >= thr] if iou.size else []
        if order:
            used.add(order[0])
            n += 1
    return n


def read_frames(video: Path, count: int) -> list[np.ndarray]:
    """`count` frames spread evenly over the video."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Can't open {video}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or count
    wanted = set(np.linspace(0, max(total - 1, 0), count).astype(int).tolist())
    frames, i = [], 0
    try:
        while len(frames) < len(wanted):
            ok, frame = cap.read()
            if not ok:
                break
            if i in wanted:
                frames.append(frame)
            i += 1
    finally:
        cap.release()
    if not frames:
        raise RuntimeError(f"No frames in {video}")
    return frames


def run(model, frames: list[np.ndarray], sizes=SIZES, conf: float = 0.5) -> list[SizeResult]:
    from backend.pipeline import class_ids

    dog_cls, _ = class_ids(model.names)
    sizes = sorted(set(sizes) | {REFERENCE})
    boxes, times = {}, {}
    for size in sizes:
        model(frames[0], imgsz=size, classes=[dog_cls], conf=conf, verbose=False)      # warm-up
        boxes[size], times[size] = [], []
        for f in frames:
            t0 = time.perf_counter()
            r = model(f, imgsz=size, classes=[dog_cls], conf=conf, verbose=False)[0]
            times[size].append(time.perf_counter() - t0)
            boxes[size].append(r.boxes.xyxy.cpu().numpy().reshape(-1, 4))
    ref_total = sum(len(b) for b in boxes[REFERENCE])
    results = []
    for size in sizes:
        found = sum(matched(r, b) for r, b in zip(boxes[REFERENCE], boxes[size]))
        results.append(SizeResult(
            imgsz=size,
            fps=round(1 / statistics.median(times[size]), 1),
            dogs_per_frame=round(sum(len(b) for b in boxes[size]) / len(frames), 2),
            dogs_found=round(found / ref_total, 3) if ref_total else 1.0,
        ))
    return results


def recommend(results: list[SizeResult], target_fps: float = 10, min_found: float = 0.9) -> tuple[SizeResult, str]:
    """The largest size that is fast enough and finds enough dogs; otherwise the fastest."""
    good = [r for r in results if r.fps >= target_fps and r.dogs_found >= min_found]
    if good:
        best = max(good, key=lambda r: r.imgsz)
        why = f"fastest accurate setting: {best.fps} fps, finds {best.dogs_found:.0%} of the dogs found at {REFERENCE}"
        if best.imgsz == REFERENCE:
            why = f"this computer is fast enough for full size ({best.fps} fps)"
        return best, why
    fastest = max(results, key=lambda r: r.fps)
    return fastest, (f"no size reaches {target_fps:g} fps with {min_found:.0%} of the dogs; using the fastest "
                     f"({fastest.fps} fps). Also try --max-fps, closing other apps or plugging in the charger.")


def table(results: list[SizeResult], best: SizeResult) -> str:
    lines = ["| Image size | FPS | Dogs per frame | Dogs found (vs 640) |", "|---|---|---|---|"]
    for r in results:
        mark = " ← recommended" if r.imgsz == best.imgsz else ""
        lines.append(f"| {r.imgsz}{mark} | {r.fps} | {r.dogs_per_frame} | {r.dogs_found:.0%} |")
    return "\n".join(lines)


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", type=Path, help="video with dogs (default: the demo video)")
    p.add_argument("--model", default=str(ROOT / "models" / "yolo11n.pt"))
    p.add_argument("--frames", type=int, default=40, help="frames to test per size (default 40)")
    p.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    p.add_argument("--target-fps", type=float, default=10)
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--json", type=Path, help="also save the results as JSON")
    args = p.parse_args(argv)
    if any(s % 32 or not 160 <= s <= 1280 for s in args.sizes):
        p.error("sizes must be multiples of 32 between 160 and 1280")
    if args.frames < 2:
        p.error("--frames must be at least 2")

    if args.video is None:
        from backend.demo import ensure_demo_video
        args.video = ensure_demo_video()
    from ultralytics import YOLO
    import torch

    frames = read_frames(args.video, args.frames)
    print(f"Testing {Path(args.model).name} on {len(frames)} frames of {args.video.name} "
          f"({frames[0].shape[1]}x{frames[0].shape[0]}), {torch.get_num_threads()} CPU threads ...\n")
    results = run(YOLO(args.model), frames, args.sizes, args.conf)
    best, why = recommend(results, args.target_fps)
    print(table(results, best))
    print(f"\nRecommended: --imgsz {best.imgsz} ({why}).")
    print(f"Start with:  start.bat --imgsz {best.imgsz}   (or pick it in the console under 'Detector image size')")
    out = {"video": str(args.video), "model": Path(args.model).name, "frames": len(frames),
           "results": [asdict(r) for r in results], "recommended": best.imgsz, "reason": why}
    if args.json:
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
