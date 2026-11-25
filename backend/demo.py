"""
Backup demo video, for when no dog walks past during the presentation.

    python -m backend.demo                       # writes recordings/demo_street.mp4
    python -m backend.server --demo              # starts the server with it (made if missing)

The video is generated from the dog photos in legacy/dog_images: three dogs on
a grey background, one resting, one walking and one running back and forth.
That exercises every activity label, the pack alert (3 dogs) and, with the
demo zone the server adds on the right side, the zone alert.

It's a stand-in: for the real demo, record a clip of real street dogs and put
it in recordings/, then start with --source recordings/<clip>.mp4.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DOG_IMAGES = ROOT / "legacy" / "dog_images"
DEFAULT_VIDEO = ROOT / "recordings" / "demo_street.mp4"
DEMO_ZONE = {"name": "Demo zone (school gate)",
             "points": [[0.7, 0.0], [1.0, 0.0], [1.0, 1.0], [0.7, 1.0]]}

# (photo, row top y, height in px, speed in box heights per second); 0 = resting.
# These photos and sizes are ones the stock detector finds reliably.
DOGS = [
    ("dog_ID_5_002.jpg", 10, 175, 0.0),
    ("dog_20260904_201328.jpg", 200, 190, 0.5),
    ("dog_20260903_185406.jpg", 410, 170, 3.2),
]


def _load(name: str, height: int) -> np.ndarray:
    path = DOG_IMAGES / name
    if not path.exists():           # fall back to any photo that's there
        path = sorted(DOG_IMAGES.glob("*.jpg"))[0]
    img = cv2.imread(str(path))
    if img is None:
        raise RuntimeError(f"Can't read {path}")
    return cv2.resize(img, (int(img.shape[1] * height / img.shape[0]), height))


def make_demo_video(path: str | Path = DEFAULT_VIDEO, seconds: float = 20, fps: int = 15,
                    size: tuple[int, int] = (960, 600)) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    W, H = size
    dogs = [(_load(name, h), y, speed) for name, y, h, speed in DOGS]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    if not writer.isOpened():
        raise RuntimeError(f"Can't write video {path}")
    try:
        for i in range(int(seconds * fps)):
            t = i / fps
            frame = np.full((H, W, 3), 190, np.uint8)
            cv2.line(frame, (0, H - 6), (W, H - 6), (150, 150, 150), 3)
            for img, y, speed in dogs:
                h, w = img.shape[:2]
                span = W - w - 20
                if speed == 0:
                    x = 60 + int(3 * np.sin(t * 2))                # resting: tiny movement only
                else:
                    travel = speed * h * t
                    x = 10 + int(abs((travel % (2 * span)) - span))  # back and forth
                    if int(travel // span) % 2 == 0:
                        img = img[:, ::-1]                           # face the way it's going
                frame[y:y + h, x:x + w] = img
            writer.write(frame)
    finally:
        writer.release()
    return path


def ensure_demo_video(path: str | Path = DEFAULT_VIDEO) -> Path:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        print(f"[demo] making backup demo video {path} ...")
        make_demo_video(path)
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Make the backup demo video")
    p.add_argument("--out", default=str(DEFAULT_VIDEO))
    p.add_argument("--seconds", type=float, default=20)
    args = p.parse_args()
    print(f"Wrote {make_demo_video(args.out, args.seconds)}")
