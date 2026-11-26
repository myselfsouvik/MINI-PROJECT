"""
Score dog detectors on our own labelled test set, all in the same way.

    python -m training.detector.evaluate --data datasets/street_dogs/data.yaml --split test \
        --models models/yolo11n.pt models/dogs_v1.pt --table results.md

The test set is a normal YOLO dataset (images/ + labels/ with one .txt per
image, "class cx cy w h", values 0..1). Only the dog class is scored. It is
found by name, so the stock COCO model (dog = 16) and our fine-tuned model
(dog = 0) are compared fairly.

For each model it reports:

    mAP50, mAP50-95   area under the precision/recall curve (COCO method, 101 points)
    precision, recall, F1   at the confidence the app uses (--conf, default 0.5)
    false alarms      dog boxes per image that has *no* dog (cats, goats, bags...)
    FPS               frames per second on this computer (inference only)

and saves them as models/<model>.json next to the weights, which the
dashboard shows under "Model". --save-errors DIR draws every image with a
mistake: green = correct, red = false alarm, yellow = missed dog.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)


# -- dataset -----------------------------------------------------------------------------

@dataclass
class Sample:
    image: Path
    dogs: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))   # xyxy, 0..1


def _names_from_yaml(data: dict) -> list[str]:
    names = data.get("names", [])
    if isinstance(names, dict):
        return [names[k] for k in sorted(names)]
    return list(names)


def _label_path(image: Path) -> Path:
    """YOLO convention: .../images/x.jpg -> .../labels/x.txt"""
    parts = list(image.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            return Path(*parts).with_suffix(".txt")
    return image.with_suffix(".txt")


def load_dataset(data: Path, split: str = "test") -> tuple[list[Sample], str]:
    """
    data: a data.yaml, or a folder with images/ (+ labels/ and classes.txt).
    Returns the samples and a short name for the dataset.
    """
    data = Path(data)
    if data.suffix.lower() in {".yaml", ".yml"}:
        import yaml
        cfg = yaml.safe_load(data.read_text(encoding="utf-8")) or {}
        base = Path(cfg.get("path") or data.parent)
        if not base.is_absolute():
            base = (data.parent / base).resolve()
        split_dir = cfg.get(split) or (cfg.get("val") if split == "test" else None)
        if not split_dir:
            raise ValueError(f"{data.name} has no '{split}' split")
        image_dir = base / split_dir
        names = _names_from_yaml(cfg)
        name = f"{data.parent.name}/{split}"
    else:
        image_dir = data / "images" if (data / "images").is_dir() else data
        classes = data / "classes.txt"
        names = classes.read_text(encoding="utf-8").split() if classes.exists() else ["dog"]
        name = data.name
    lowered = [n.lower() for n in names]
    if "dog" in lowered:
        dog_cls = lowered.index("dog")
    elif len(names) == 1:
        dog_cls = 0
    else:
        raise ValueError(f"No 'dog' class in dataset names {names}")

    images = sorted(f for f in image_dir.rglob("*") if f.suffix.lower() in IMAGE_TYPES)
    if not images:
        raise ValueError(f"No images in {image_dir}")
    samples = []
    for img in images:
        boxes = []
        label = _label_path(img)
        if label.exists():
            for line in label.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) >= 5 and int(float(parts[0])) == dog_cls:
                    cx, cy, w, h = map(float, parts[1:5])
                    boxes.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
        samples.append(Sample(img, np.array(boxes, dtype=float).reshape(-1, 4)))
    return samples, name


# -- scoring -------------------------------------------------------------------------------

def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU matrix between xyxy boxes a (N,4) and b (M,4)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-12)


def match(pred: np.ndarray, conf: np.ndarray, truth: np.ndarray, iou_thr: float) -> np.ndarray:
    """Greedy matching, most confident first. Returns True for each correct prediction."""
    correct = np.zeros(len(pred), dtype=bool)
    if len(pred) == 0 or len(truth) == 0:
        return correct
    iou = box_iou(pred, truth)
    taken = np.zeros(len(truth), dtype=bool)
    for i in np.argsort(-conf, kind="stable"):
        candidates = np.where(~taken & (iou[i] >= iou_thr))[0]
        if len(candidates):
            j = candidates[np.argmax(iou[i, candidates])]
            taken[j] = correct[i] = True
    return correct


def average_precision(correct: np.ndarray, conf: np.ndarray, n_truth: int) -> float:
    """COCO-style AP: area under the precision envelope sampled at 101 recall points."""
    if n_truth == 0:
        return float("nan")
    if len(correct) == 0:
        return 0.0
    order = np.argsort(-conf, kind="stable")
    tp = np.cumsum(correct[order])
    fp = np.cumsum(~correct[order])
    recall = tp / n_truth
    precision = tp / np.maximum(tp + fp, 1e-12)
    precision = np.maximum.accumulate(precision[::-1])[::-1]       # envelope
    points = np.linspace(0, 1, 101)
    idx = np.searchsorted(recall, points, side="left")
    return float(np.mean([precision[i] if i < len(precision) else 0.0 for i in idx]))


@dataclass
class Prediction:
    boxes: np.ndarray          # xyxy, 0..1
    conf: np.ndarray


def score(samples: list[Sample], preds: list[Prediction], conf_thr: float = 0.5) -> dict:
    """All the numbers for one model. preds[i] belongs to samples[i]."""
    n_truth = int(sum(len(s.dogs) for s in samples))
    all_conf = np.concatenate([p.conf for p in preds]) if preds else np.zeros(0)
    aps = []
    for thr in IOU_THRESHOLDS:
        correct = np.concatenate([match(p.boxes, p.conf, s.dogs, thr) for s, p in zip(samples, preds)]) \
            if preds else np.zeros(0, bool)
        aps.append(average_precision(correct, all_conf, n_truth))

    tp = fp = fn = 0
    empty_images = empty_alarms = 0
    for s, p in zip(samples, preds):
        keep = p.conf >= conf_thr
        ok = match(p.boxes[keep], p.conf[keep], s.dogs, 0.5)
        tp += int(ok.sum())
        fp += int((~ok).sum())
        fn += len(s.dogs) - int(ok.sum())
        if len(s.dogs) == 0:
            empty_images += 1
            empty_alarms += int(keep.sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    nan = lambda v: None if v != v else round(v, 4)          # noqa: E731  (NaN -> None for JSON)
    return {
        "mAP50": nan(aps[0]),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fps": None,
        "mAP50_95": nan(float(np.mean(aps))),
        "f1": round(f1, 4),
        "conf": conf_thr,
        "images": len(samples),
        "dogs": n_truth,
        "true_positives": tp,
        "false_positives": fp,
        "missed": fn,
        "empty_images": empty_images,
        "false_alarms_per_empty_image": round(empty_alarms / empty_images, 4) if empty_images else None,
    }


# -- running a model -----------------------------------------------------------------------

def predict_all(model, samples: list[Sample], imgsz: int = 640) -> tuple[list[Prediction], float]:
    """Run an Ultralytics model on every image. Returns predictions and FPS."""
    from backend.pipeline import class_ids

    dog_cls, _ = class_ids(model.names)
    preds, times = [], []
    for i, s in enumerate(samples):
        img = cv2.imread(str(s.image))
        if img is None:
            raise RuntimeError(f"Can't read {s.image}")
        h, w = img.shape[:2]
        start = time.perf_counter()
        r = model(img, classes=[dog_cls], conf=0.001, imgsz=imgsz, max_det=300, verbose=False)[0]
        if i:                                     # the first call includes warm-up
            times.append(time.perf_counter() - start)
        boxes = r.boxes.xyxy.cpu().numpy().reshape(-1, 4) / [w, h, w, h]
        preds.append(Prediction(boxes, r.boxes.conf.cpu().numpy().reshape(-1)))
    fps = len(times) / sum(times) if times and sum(times) > 0 else None
    return preds, fps


def draw_errors(samples: list[Sample], preds: list[Prediction], out: Path, conf_thr: float) -> int:
    """Save images where the model made a mistake. Returns how many."""
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for s, p in zip(samples, preds):
        keep = p.conf >= conf_thr
        boxes, conf = p.boxes[keep], p.conf[keep]
        ok = match(boxes, conf, s.dogs, 0.5)
        found = box_iou(s.dogs, boxes[ok]).max(axis=1) >= 0.5 if ok.any() else np.zeros(len(s.dogs), bool)
        if ok.all() and found.all():
            continue
        img = cv2.imread(str(s.image))
        h, w = img.shape[:2]
        scale = np.array([w, h, w, h])
        for box, c, good in zip(boxes, conf, ok):
            x1, y1, x2, y2 = (box * scale).astype(int)
            colour = (60, 190, 60) if good else (40, 40, 230)
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2)
            cv2.putText(img, f"{c:.2f}", (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
        for box, seen in zip(s.dogs, found):
            if not seen:
                x1, y1, x2, y2 = (box * scale).astype(int)
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 220, 255), 2)
                cv2.putText(img, "missed", (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
        cv2.imwrite(str(out / f"{s.image.stem}.jpg"), img)
        count += 1
    return count


def evaluate_model(model_path: str, samples: list[Sample], dataset: str, conf: float = 0.5,
                   imgsz: int = 640, errors_dir: Path | None = None, save_meta: bool = True) -> dict:
    from ultralytics import YOLO

    model = YOLO(model_path)
    preds, fps = predict_all(model, samples, imgsz)
    result = score(samples, preds, conf)
    result["fps"] = round(fps, 1) if fps else None
    result |= {"model": Path(model_path).name, "dataset": dataset, "imgsz": imgsz,
               "evaluated": datetime.now().isoformat(timespec="seconds")}
    if errors_dir is not None:
        result["error_images"] = draw_errors(samples, preds, errors_dir / Path(model_path).stem, conf)
    path = Path(model_path)
    if save_meta and path.is_file():
        path.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def markdown_table(results: list[dict]) -> str:
    cols = [("Model", "model"), ("mAP50", "mAP50"), ("mAP50-95", "mAP50_95"), ("Precision", "precision"),
            ("Recall", "recall"), ("F1", "f1"), ("False alarms / empty image", "false_alarms_per_empty_image"),
            ("FPS", "fps")]
    def fmt(key, v):
        if v is None:
            return "-"
        if key == "fps":
            return f"{v:.1f}"
        return f"{v:.3f}" if isinstance(v, float) else str(v)

    lines = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(k, r.get(k)) for _, k in cols) + " |" for r in results]
    if results:
        r = results[0]
        lines.append(f"\nTest set: {r['dataset']}, {r['images']} images, {r['dogs']} dogs, "
                     f"{r['empty_images']} without dogs. Precision/recall at confidence {r['conf']}, IoU 0.5.")
    return "\n".join(lines)


def main(argv=None) -> list[dict]:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, required=True, help="data.yaml, or a folder with images/ and labels/")
    p.add_argument("--split", default="test", help="split in data.yaml (default test, falls back to val)")
    p.add_argument("--models", nargs="+", default=[str(ROOT / "models" / "yolo11n.pt")])
    p.add_argument("--conf", type=float, default=0.5, help="confidence for precision/recall (app uses 0.5)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--save-errors", type=Path, help="folder for pictures of mistakes")
    p.add_argument("--table", type=Path, help="also write the comparison table to this .md file")
    p.add_argument("--no-meta", action="store_true", help="don't write models/<model>.json")
    args = p.parse_args(argv)

    samples, dataset = load_dataset(args.data, args.split)
    print(f"Test set {dataset}: {len(samples)} images, {sum(len(s.dogs) for s in samples)} dogs\n")
    results = []
    for m in args.models:
        print(f"Evaluating {Path(m).name} ...")
        results.append(evaluate_model(m, samples, dataset, args.conf, args.imgsz, args.save_errors,
                                      not args.no_meta))
    table = markdown_table(results)
    print("\n" + table)
    if args.table:
        args.table.write_text(table + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    main()
