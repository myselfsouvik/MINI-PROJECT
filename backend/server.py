"""
Start the backend server.

    python -m backend.server                          # no camera yet, add one from the page
    python -m backend.server --source 0               # laptop webcam
    python -m backend.server --source 1 --source 0    # USB phone + laptop webcam
    python -m backend.server --source clip.mp4        # recorded video
    python -m backend.server --phone                  # also let phones connect from their browser (QR code)
    python -m backend.server --host 0.0.0.0           # whole dashboard reachable from the Wi-Fi
                                                      # (prints an access token other devices must use)
    python -m backend.server --demo --open            # backup demo video + demo zone, opens the browser
    python -m backend.doctor                          # check this laptop is ready before a demo

Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
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
    p.add_argument("--phone", action="store_true",
                   help="let phones on the Wi-Fi stream their camera from the browser (HTTPS + QR code)")
    p.add_argument("--phone-port", type=int, default=8443, help="HTTPS port for phones (default 8443)")
    p.add_argument("--phone-host", default="0.0.0.0",
                   help="address the phone server listens on (default 0.0.0.0 = the Wi-Fi network)")
    p.add_argument("--model", default=AppSettings.model_path, help="YOLO weights file")
    p.add_argument("--behaviour-model", default=AppSettings.behaviour_model_path,
                   help="trained behaviour classifier (.joblib); used only if the file exists")
    p.add_argument("--conf", type=float, default=0.5, help="detection confidence (default 0.5)")
    p.add_argument("--max-fps", type=float, default=0.0, help="limit detector FPS to save CPU (0 = no limit)")
    p.add_argument("--imgsz", type=int, default=640,
                   help="detector image size, a multiple of 32 (default 640; 416 or 320 on slow laptops, "
                        "see python -m backend.benchmark)")
    p.add_argument("--media-dir", default=AppSettings.media_dir,
                   help="folder video files must be in when added from the page (default: recordings/)")
    p.add_argument("--token", help="access token for other devices (default: random when they can connect)")
    p.add_argument("--demo", action="store_true",
                   help="also watch the backup demo video (made if missing) with a demo zone")
    p.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    p.add_argument("--keep-days", type=float, default=None,
                   help="auto-delete dogs, events, photos and clips older than this many days (default: keep all)")
    args = p.parse_args(argv)

    if args.demo:
        from backend.demo import ensure_demo_video

        demo_video = ensure_demo_video()
        if str(demo_video) not in args.source:
            args.source.append(str(demo_video))

    if not 160 <= args.imgsz <= 1280 or args.imgsz % 32:
        p.error("--imgsz must be a multiple of 32 between 160 and 1280")
    if args.keep_days is not None and args.keep_days < 1 / 24:
        p.error("--keep-days must be at least 0.042 (one hour)")
    reachable_from_network = args.phone or not is_local_client(args.host)
    token = args.token or (new_token() if reachable_from_network else None)
    settings = AppSettings(model_path=args.model, behaviour_model_path=args.behaviour_model, confidence=args.conf, max_fps=args.max_fps, imgsz=args.imgsz,
                           media_dir=args.media_dir, access_token=token,
                           phone_port=args.phone_port if args.phone else None, keep_days=args.keep_days)
    Path(args.media_dir).mkdir(parents=True, exist_ok=True)
    app = create_app(settings, initial_sources=args.source)
    if args.demo:
        add_demo_zone(app, demo_video)

    configs = [uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")]
    print(f"\n  Dashboard: http://127.0.0.1:{args.port}    API docs: http://127.0.0.1:{args.port}/docs")
    if Path(args.behaviour_model).is_file():
        print(f"  Behaviour: trained classifier {Path(args.behaviour_model).name}")
    else:
        print("  Behaviour: speed thresholds (no models/behaviour.joblib yet, see training/behaviour)")

    if args.phone:
        from backend.phone import ensure_certificate, lan_ips

        ips = lan_ips()
        cert, key = ensure_certificate(Path(settings.storage_dir) / "certs", ips)
        configs.append(uvicorn.Config(app, host=args.phone_host, port=args.phone_port, log_level="warning",
                                      ssl_certfile=str(cert), ssl_keyfile=str(key)))
        if ips:
            print(f"  Phones: click 'Connect phone' on the dashboard and scan the QR code,")
            print(f"          or open https://{ips[0]}:{args.phone_port}/phone?token={token}")
        else:
            print("  Phones: no Wi-Fi address found. Connect this laptop to Wi-Fi or a phone hotspot.")
        print("  (Windows may ask to allow Python through the firewall: allow it on Private networks.)")
    elif token:
        print(f"  Other devices need the access token:  ?token={token}")
        print(f"  e.g. http://<this-laptop's-IP>:{args.port}/?token={token}")
    print()

    if args.open:
        import threading
        import webbrowser

        threading.Timer(2.0, webbrowser.open, [f"http://127.0.0.1:{args.port}"]).start()

    async def serve_all():
        await asyncio.gather(*(uvicorn.Server(c).serve() for c in configs))

    try:
        asyncio.run(serve_all())
    except KeyboardInterrupt:
        pass


def add_demo_zone(app, video: Path) -> None:
    """Give the demo video a zone (once), so zone alerts show up in the demo."""
    from backend.demo import DEMO_ZONE

    db = app.state.db
    key = f"file:{Path(video).resolve()}"
    if not db.list_zones(key):
        db.add_zone(key, DEMO_ZONE["name"], DEMO_ZONE["points"])


if __name__ == "__main__":
    main()
