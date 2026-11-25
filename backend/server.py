"""
Start the backend server.

    python -m backend.server                          # no camera yet, add one from the page
    python -m backend.server --source 0               # laptop webcam
    python -m backend.server --source 1 --source 0    # USB phone + laptop webcam
    python -m backend.server --source clip.mp4        # recorded video
    python -m backend.server --host 0.0.0.0           # reachable from other devices on the Wi-Fi
                                                      # (prints an access token they must use)

Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from backend.app import AppSettings, create_app  # noqa: E402
from backend.security import is_local_client, new_token  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Street Dog Monitoring System backend")
    p.add_argument("--host", default="127.0.0.1",
                   help="127.0.0.1 = this computer only (default); 0.0.0.0 = whole Wi-Fi network")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--source", action="append", default=[],
                   help="camera to watch at startup (repeatable): webcam number, URL or video file")
    p.add_argument("--model", default=AppSettings.model_path, help="YOLO weights file")
    p.add_argument("--conf", type=float, default=0.5, help="detection confidence (default 0.5)")
    p.add_argument("--max-fps", type=float, default=0.0, help="limit detector FPS to save CPU (0 = no limit)")
    p.add_argument("--media-dir", default=AppSettings.media_dir,
                   help="folder video files must be in when added from the page (default: recordings/)")
    p.add_argument("--token", help="access token for other devices (default: random when --host isn't local)")
    args = p.parse_args(argv)

    token = args.token or (None if is_local_client(args.host) else new_token())
    settings = AppSettings(model_path=args.model, confidence=args.conf, max_fps=args.max_fps,
                           media_dir=args.media_dir, access_token=token)
    Path(args.media_dir).mkdir(parents=True, exist_ok=True)
    app = create_app(settings, initial_sources=args.source)
    print(f"\n  Dashboard: http://127.0.0.1:{args.port}    API docs: http://127.0.0.1:{args.port}/docs")
    if token:
        print(f"  Other devices need the access token:  ?token={token}")
        print(f"  e.g. http://<this-laptop's-IP>:{args.port}/?token={token}")
    print()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
