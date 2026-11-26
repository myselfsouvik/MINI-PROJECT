"""
Check that this laptop is ready to run the demo.

    python -m backend.doctor             # quick checks
    python -m backend.doctor --cameras   # also look for webcams / USB phones (switches them on briefly)
    python -m backend.doctor --phone     # also check the phone (HTTPS) port

Each line is OK, WARN (works, but worth fixing) or FAIL (the demo won't
work). Every problem comes with what to do about it. Exit code is 1 if
anything failed, so it can be used in scripts.
"""

from __future__ import annotations

import argparse
import importlib
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK, WARN, FAIL = "OK", "WARN", "FAIL"
PACKAGES = [  # (import name, pip name)
    ("ultralytics", "ultralytics"), ("cv2", "opencv-python"), ("torch", "torch"), ("numpy", "numpy"),
    ("lap", "lap"), ("fastapi", "fastapi"), ("uvicorn", "uvicorn[standard]"), ("sklearn", "scikit-learn"),
    ("joblib", "joblib"), ("pandas", "pandas"), ("qrcode", "qrcode"), ("cryptography", "cryptography"),
]


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


def check_python() -> Check:
    v = sys.version_info
    text = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < (3, 10):
        return Check("Python", FAIL, text, "Install Python 3.11 and recreate the venv.")
    if (v.major, v.minor) > (3, 12):
        return Check("Python", WARN, text, "Tested with 3.11; if a package fails to install, use 3.11.")
    venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    return Check("Python", OK if venv else WARN, text + (" (venv)" if venv else " (no venv)"),
                 "" if venv else "Activate the project venv: .venv\\Scripts\\activate")


def check_packages() -> list[Check]:
    out, missing = [], []
    for mod, pip_name in PACKAGES:
        try:
            m = importlib.import_module(mod)
            out.append((mod, getattr(m, "__version__", "?")))
        except Exception:
            missing.append(pip_name)
    if missing:
        return [Check("Packages", FAIL, "missing: " + ", ".join(missing),
                      "pip install -r requirements.txt")]
    return [Check("Packages", OK, ", ".join(f"{m} {v}" for m, v in out[:4]) + f" (+{len(out) - 4} more)")]


def check_model(path: Path, speed_test: bool = True) -> list[Check]:
    if not path.is_file():
        return [Check("Detector", FAIL, f"{path} not found",
                      "Get models/yolo11n.pt from the repo (git pull) or pass --model.")]
    try:
        import numpy as np
        from ultralytics import YOLO

        from backend.pipeline import class_ids

        model = YOLO(str(path))
        dog, person = class_ids(model.names)
    except Exception as e:
        return [Check("Detector", FAIL, f"{path.name}: {e}", "Re-download the weights file.")]
    checks = [Check("Detector", OK, f"{path.name}: dog = class {dog}"
                    + (f", person = class {person}" if person is not None
                       else " (no person class: running-at-person alert is off)"))]
    if speed_test:
        frame = np.full((480, 640, 3), 127, np.uint8)
        model(frame, verbose=False)                    # warm-up
        t0, n = time.perf_counter(), 5
        for _ in range(n):
            model(frame, verbose=False)
        fps = n / (time.perf_counter() - t0)
        if fps >= 8:
            checks.append(Check("Speed", OK, f"{fps:.0f} frames/s on this laptop"))
        else:
            checks.append(Check("Speed", WARN, f"only {fps:.1f} frames/s",
                                "Plug in the charger and close other apps; or start with --max-fps 5. "
                                "An ONNX/OpenVINO export (training/detector) is faster on CPU."))
    return checks


def check_behaviour_model(path: Path) -> Check:
    if not path.is_file():
        return Check("Behaviour", OK, "speed thresholds (no trained classifier yet)")
    from backend.features import BehaviourModel

    try:
        m = BehaviourModel(path)
        return Check("Behaviour", OK, f"classifier {path.name}: {' / '.join(m.labels)}")
    except Exception as e:
        return Check("Behaviour", WARN, f"{path.name} can't be loaded: {e}",
                     "Retrain it: python -m training.behaviour.train_classifier")


def check_writable(folder: Path) -> Check:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder):
            pass
        return Check("Storage", OK, str(folder))
    except OSError as e:
        return Check("Storage", FAIL, f"can't write to {folder}: {e}",
                     "Move the project to a folder you own (not Program Files / OneDrive sync).")


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def check_port(port: int, what: str) -> Check:
    if port_free(port):
        return Check(f"Port {port}", OK, f"free ({what})")
    return Check(f"Port {port}", FAIL, f"in use ({what})",
                 f"Close the other server, or start with --port {port + 1}.")


def check_network(phone: bool) -> Check:
    from backend.phone import lan_ips

    ips = lan_ips()
    if ips:
        return Check("Wi-Fi", OK, "address " + ", ".join(ips))
    return Check("Wi-Fi", WARN if phone else OK, "no Wi-Fi address",
                 "Phones need the laptop on Wi-Fi or a phone hotspot. USB phone cameras still work."
                 if phone else "")


def check_cameras() -> Check:
    from backend.cameras import list_local_cameras

    cams = list_local_cameras(4)
    if not cams:
        return Check("Cameras", WARN, "no webcam found",
                     "Use --demo or a video file; for a phone over USB, start DroidCam/Iriun first.")
    return Check("Cameras", OK, ", ".join(f"#{c['index']} {c['width']}x{c['height']}" for c in cams)
                 + ("  (#1+ is usually a USB phone)" if len(cams) > 1 else ""))


def check_frontend(dist: Path) -> Check:
    if (dist / "index.html").is_file():
        return Check("Dashboard", OK, f"React build found ({dist.relative_to(ROOT)})")
    return Check("Dashboard", OK, "test console (React dashboard not built yet: cd frontend && npm run build)")


def check_demo_video(path: Path) -> Check:
    if path.is_file():
        return Check("Demo video", OK, str(path.relative_to(ROOT)))
    return Check("Demo video", OK, "will be made on first --demo run (python -m backend.demo)")


def run_checks(args) -> list[Check]:
    from backend.app import AppSettings

    s = AppSettings()
    checks = [check_python(), *check_packages()]
    if checks[-1].status == FAIL:          # nothing else can be checked without the packages
        return checks
    checks += check_model(Path(args.model), speed_test=not args.quick)
    checks.append(check_behaviour_model(Path(s.behaviour_model_path)))
    checks.append(check_writable(Path(s.storage_dir)))
    checks.append(check_port(args.port, "dashboard"))
    if args.phone:
        checks.append(check_port(args.phone_port, "phones, HTTPS"))
    checks.append(check_network(args.phone))
    if args.cameras:
        checks.append(check_cameras())
    checks.append(check_frontend(Path(s.frontend_dir)))
    from backend.demo import DEFAULT_VIDEO
    checks.append(check_demo_video(DEFAULT_VIDEO))
    return checks


def main(argv=None) -> int:
    from backend.app import AppSettings

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cameras", action="store_true", help="also look for webcams (turns them on briefly)")
    p.add_argument("--phone", action="store_true", help="also check what phones need")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--phone-port", type=int, default=8443)
    p.add_argument("--model", default=AppSettings.model_path)
    p.add_argument("--quick", action="store_true", help="skip the speed test")
    args = p.parse_args(argv)

    print("\nChecking this laptop for the Street Dog Monitoring demo...\n")
    checks = run_checks(args)
    width = max(len(c.name) for c in checks) + 2
    for c in checks:
        print(f"  [{c.status:^4}] {c.name.ljust(width)}{c.detail}")
        if c.fix and c.status != OK:
            print(f"  {'':6} {'':{width}}-> {c.fix}")
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    print()
    if fails:
        print(f"  {fails} problem(s) to fix before the demo.")
    else:
        print("  Ready. Start with:  python -m backend.server --open"
              + ("   (some warnings above)" if warns else ""))
    print()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
