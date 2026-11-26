"""
Turn recorded videos into full frames for labelling, pre-labelled by the
current detector.

    python -m training.detector.extract_frames recordings/captures --out datasets/street_dogs/unlabelled

For each video it keeps one frame every --every seconds, skips frames that
look almost the same as the last one kept (a dog lying still for a minute
would otherwise give 60 copies), and writes:

    <out>/images/<video>_<time>.jpg     full frame (never a crop)
    <out>/labels/<video>_<time>.txt     YOLO boxes from the current model ("pre-labels")
    <out>/classes.txt                   class names, in label order

Import the folder into CVAT / Label Studio / Roboflow as a **YOLO** dataset
and only *correct* the boxes instead of drawing every one. Frames with no
dog are kept too (as --negatives allows): they teach the model what is *not*
a dog (cats, goats, bags...), which is where the stock model goes wrong.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "models" / "yolo11n.pt"
VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
CLASSES = ["dog", "person"]          # label order for our dataset (data.yaml uses the same)


def _thumb(frame: np.ndarray) -> np.ndarray:
    small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)


def different_enough(a: np.ndarray | None, b: np.ndarray, threshold: float) -> bool:
    """Mean absolute difference of tiny grey thumbnails, 0..255."""
    return a is None or float(np.abs(a - b).mean()) >= threshold


def yolo_line(cls: int, box, w: int, h: int) -> str:
    x1, y1, x2, y2 = box
    return (f"{cls} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} "
            f"{(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")


def extract_video(video: Path, out: Path, model=None, every: float = 1.0, min_change: float = 4.0,
                  negatives: float = 0.3, confidence: float = 0.25, max_frames: int = 0) -> dict:
    """Save frames (+ pre-labels if model is given). Returns counts."""
    from backend.pipeline import class_ids

    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    dog_cls, person_cls = class_ids(model.names) if model is not None else (None, None)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Can't open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(every * fps)))
    counts = {"frames": 0, "with_dogs": 0, "negatives": 0, "skipped_similar": 0}
    last_thumb, index, neg_budget = None, -1, 0.0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            index += 1
            if index % step:
                continue
            ok, frame = cap.retrieve()
            if not ok:
                break
            thumb = _thumb(frame)
            if not different_enough(last_thumb, thumb, min_change):
                counts["skipped_similar"] += 1
                continue

            lines = []
            if model is not None:
                wanted = [c for c in (dog_cls, person_cls) if c is not None]
                r = model(frame, classes=wanted, conf=confidence, verbose=False)[0]
                h, w = frame.shape[:2]
                for box, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int)):
                    ours = CLASSES.index("dog") if c == dog_cls else CLASSES.index("person")
                    lines.append(yolo_line(ours, box.tolist(), w, h))
            has_dog = any(l.startswith(f"{CLASSES.index('dog')} ") for l in lines)
            if model is not None and not has_dog:
                # Keep only some dog-free frames: enough hard negatives, not a flood of empty street.
                neg_budget += negatives
                if neg_budget < 1:
                    continue
                neg_budget -= 1

            last_thumb = thumb
            stem = f"{video.stem}_{index / fps:07.1f}s".replace(".", "_")
            cv2.imwrite(str(out / "images" / f"{stem}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            (out / "labels" / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
            counts["frames"] += 1
            counts["with_dogs" if has_dog else "negatives"] += 1
            if max_frames and counts["frames"] >= max_frames:
                break
    finally:
        cap.release()
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n")
    return counts


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", type=Path, help="video files or folders of videos")
    p.add_argument("--out", type=Path, default=ROOT / "datasets" / "street_dogs" / "unlabelled")
    p.add_argument("--every", type=float, default=1.0, help="seconds between frames (default 1)")
    p.add_argument("--min-change", type=float, default=4.0,
                   help="skip frames this similar to the last kept one (0 = keep all; default 4)")
    p.add_argument("--negatives", type=float, default=0.3,
                   help="share of dog-free frames to keep as hard negatives (default 0.3)")
    p.add_argument("--model", default=str(DEFAULT_MODEL), help="detector for pre-labels")
    p.add_argument("--no-labels", action="store_true", help="only save frames, no pre-labels")
    p.add_argument("--conf", type=float, default=0.25, help="pre-label confidence (low: easier to delete than draw)")
    p.add_argument("--max-frames", type=int, default=0, help="per video, 0 = no limit")
    args = p.parse_args(argv)

    videos = []
    for item in args.inputs:
        if item.is_dir():
            videos += sorted(f for f in item.rglob("*") if f.suffix.lower() in VIDEO_TYPES)
        elif item.suffix.lower() in VIDEO_TYPES:
            videos.append(item)
    if not videos:
        p.error("No videos found.")

    model = None
    if not args.no_labels:
        from ultralytics import YOLO
        model = YOLO(args.model)

    total = {"frames": 0, "with_dogs": 0, "negatives": 0, "skipped_similar": 0}
    for v in videos:
        c = extract_video(v, args.out, model, args.every, args.min_change, args.negatives, args.conf,
                          args.max_frames)
        print(f"{v.name}: {c['frames']} frames ({c['with_dogs']} with dogs, {c['negatives']} without), "
              f"{c['skipped_similar']} near-duplicates skipped")
        for k in total:
            total[k] += c[k]
    print(f"\nWrote {total['frames']} frames to {args.out}. Import it as a YOLO dataset "
          f"(images/ + labels/ + classes.txt) and correct the boxes.")


if __name__ == "__main__":
    main()
