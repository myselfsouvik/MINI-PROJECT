"""
Quick check that a camera works before using it in the dashboard.

Examples (run from the project folder):

    python -m backend.camera_test --list                      # find webcams (USB phone shows up here)
    python -m backend.camera_test --source 0                  # laptop webcam
    python -m backend.camera_test --source 1 --detect         # USB phone + dog detection
    python -m backend.camera_test --phone 192.168.1.5         # phone over Wi-Fi (IP Webcam app)
    python -m backend.camera_test --phone 192.168.1.5 --app droidcam
    python -m backend.camera_test --source clip.mp4 --detect  # recorded video

Keys in the window:  Q = quit,  S = save a snapshot to recordings/
Add --headless --frames 100 to test without opening a window.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:          # allow "python backend/camera_test.py" too
    sys.path.insert(0, str(ROOT))

from backend.cameras import PHONE_APPS, CameraSource, list_local_cameras, phone_url  # noqa: E402

DOG_CLASS = 16  # COCO class id for "dog"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Test a camera source for the Street Dog Monitoring System.")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--list", action="store_true", help="list webcams connected to this computer")
    src.add_argument("--source", help="webcam number, stream URL or video file (default: 0)")
    src.add_argument("--phone", metavar="IP", help="phone's IP address shown in the camera app")
    p.add_argument("--app", choices=sorted(PHONE_APPS), default="ipwebcam",
                   help="phone camera app used with --phone (default: ipwebcam)")
    p.add_argument("--detect", action="store_true", help="draw YOLO dog detections")
    p.add_argument("--model", default=str(ROOT / "models" / "yolo11n.pt"), help="YOLO weights")
    p.add_argument("--conf", type=float, default=0.5, help="detection confidence (default 0.5)")
    p.add_argument("--headless", action="store_true", help="no window; print stats instead")
    p.add_argument("--frames", type=int, default=0, help="stop after this many frames (0 = run until Q)")
    p.add_argument("--no-loop", action="store_true", help="stop when a video file ends")
    return p


def draw_detections(frame, result) -> int:
    dogs = 0
    for box in result.boxes:
        if int(box.cls[0]) != DOG_CLASS:
            continue
        dogs += 1
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.putText(frame, f"dog {conf:.2f}", (x1, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
    return dogs


def draw_hud(frame, lines: list[str]) -> None:
    y = 22
    for text in lines:
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        y += 22


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        print("Looking for cameras (each one may switch on briefly)…")
        cams = list_local_cameras()
        if not cams:
            print("No cameras found.")
            return 1
        for c in cams:
            print(f"  [{c['index']}] {c['width']}x{c['height']}")
        print("A phone connected with DroidCam / Iriun usually appears as the last one.")
        return 0

    source = phone_url(args.phone, args.app) if args.phone else (args.source or "0")

    model = None
    if args.detect:
        from ultralytics import YOLO
        model = YOLO(args.model)

    print(f"Opening {source} …")
    try:
        cam = CameraSource(source, loop=not args.no_loop).start()
    except (RuntimeError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Connected: {cam.name}  ({cam.stats.width}x{cam.stats.height})")
    if not args.headless:
        print("Press Q to quit, S to save a snapshot.")

    shown, last_id, infer_fps = 0, 0, 0.0
    started = time.monotonic()
    try:
        while True:
            frame = cam.wait_frame(timeout=5, after_id=last_id)
            if frame is None:
                if cam.finished:
                    print("Video ended.")
                    break
                print("No new frame for 5 s; still waiting…")
                continue
            last_id = cam.frame_id
            shown += 1

            dogs = None
            if model is not None:
                t0 = time.monotonic()
                result = model(frame, conf=args.conf, classes=[DOG_CLASS], verbose=False)[0]
                dt = time.monotonic() - t0
                infer_fps = 0.9 * infer_fps + 0.1 * (1 / dt if dt else 0)
                dogs = draw_detections(frame, result)

            hud = [cam.name, f"camera {cam.stats.fps:.1f} fps"]
            if dogs is not None:
                hud.append(f"detector {infer_fps:.1f} fps   dogs: {dogs}")

            if args.headless:
                if shown % 25 == 0:
                    print("  " + " | ".join(hud))
            else:
                draw_hud(frame, hud)
                cv2.imshow("Camera test", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("s"):
                    out = ROOT / "recordings"
                    out.mkdir(exist_ok=True)
                    path = out / time.strftime("snapshot_%Y%m%d_%H%M%S.jpg")
                    cv2.imwrite(str(path), frame)
                    print(f"Saved {path}")

            if args.frames and shown >= args.frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        cv2.destroyAllWindows()

    elapsed = time.monotonic() - started
    print(f"Done: {shown} frames in {elapsed:.1f}s ({shown / elapsed if elapsed else 0:.1f} fps shown).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
