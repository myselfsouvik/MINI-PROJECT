"""
Session report: one self-contained HTML page about a monitoring session, for
the project report, slides or the teacher.

    python -m backend.report --minutes 120 --out session_report.html
    (or GET /api/report?minutes=120 while the server runs)

It contains the summary numbers, activity over time, where dogs spent time,
speeds, every alert with its photo, the dogs that stayed longest and the
models' test results. Photos are embedded as small JPEGs, so the file works
offline and can be printed to PDF from the browser (Ctrl+P).
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime
from html import escape
from pathlib import Path

import cv2

from backend.alerts import ALERT_TYPES
from backend.db import Database
from backend.housekeeping import _inside

ROOT = Path(__file__).resolve().parent.parent
ACTIVITIES = ("RESTING", "WALKING", "RUNNING")
COLOURS = {"RESTING": "#2a8be0", "WALKING": "#3caa3c", "RUNNING": "#e5482a"}
ALERT_NAMES = {"zone_entered": "Dog in zone", "dog_running_at_person": "Dog running at person",
               "dog_pack": "Pack of dogs"}


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def thumbnail(storage_dir: Path, rel: str | None, width: int = 200) -> str | None:
    """A small JPEG of a stored photo as a data: URL, or None."""
    path = _inside(Path(storage_dir), rel) if rel else None
    if path is None or not path.is_file() or path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return None
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None


def _img(src: str | None, alt: str = "") -> str:
    return f'<img src="{src}" alt="{escape(alt)}">' if src else '<div class="noimg"></div>'


# -- charts (inline SVG, no JavaScript) ------------------------------------------------------------

def timeline_svg(buckets: list[dict], start: float, end: float, bucket: float) -> str:
    n = max(1, int(round((end - start) / bucket)))
    by_index = {int(round((b["start"] - start) / bucket)): b for b in buckets}
    totals = [sum(by_index.get(i, {}).get(a, 0) for a in ACTIVITIES) for i in range(n)]
    top = max(totals + [1])
    W, H, bw = 720, 160, 720 / n
    bars = []
    for i in range(n):
        y = H
        for a in ACTIVITIES:
            v = by_index.get(i, {}).get(a, 0)
            if v:
                h = v / top * (H - 10)
                y -= h
                bars.append(f'<rect x="{i * bw + 1:.1f}" y="{y:.1f}" width="{max(bw - 2, 1):.1f}" '
                            f'height="{h:.1f}" fill="{COLOURS[a]}"><title>{_when(start + i * bucket)[11:16]} '
                            f'{a.lower()}: {v} dog-seconds</title></rect>')
    labels = "".join(f'<text x="{i * bw:.1f}" y="{H + 14}" font-size="10">{_when(start + i * bucket)[11:16]}</text>'
                     for i in range(0, n, max(1, n // 6)))
    return (f'<svg viewBox="0 0 {W} {H + 18}" role="img" aria-label="Activity over time">'
            f'<line x1="0" y1="{H}" x2="{W}" y2="{H}" stroke="#bbb"/>{"".join(bars)}{labels}</svg>')


def heatmap_svg(grid: list[list[int]]) -> str:
    rows, cols = len(grid), len(grid[0])
    top = max(max(r) for r in grid) or 1
    W, H = 320, 180
    cw, ch = W / cols, H / rows
    cells = "".join(f'<rect x="{x * cw:.1f}" y="{y * ch:.1f}" width="{cw:.1f}" height="{ch:.1f}" '
                    f'fill="#e5482a" fill-opacity="{0.15 + 0.85 * n / top:.2f}"><title>{n} dog-seconds</title></rect>'
                    for y, row in enumerate(grid) for x, n in enumerate(row) if n)
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Where dogs spent time">'
            f'<rect width="{W}" height="{H}" fill="#f1f3f6" stroke="#ccc"/>{cells}</svg>')


def histogram_svg(counts: list[int], bin_width: float) -> str:
    top = max(counts + [1])
    W, H = 320, 120
    bw = W / len(counts)
    bars = "".join(f'<rect x="{i * bw + 1:.1f}" y="{H - n / top * (H - 6):.1f}" width="{bw - 2:.1f}" '
                   f'height="{n / top * (H - 6):.1f}" fill="#4f6bed"><title>{i * bin_width:.2f}–'
                   f'{(i + 1) * bin_width:.2f}: {n}</title></rect>' for i, n in enumerate(counts) if n)
    marks = "".join(f'<line x1="{v / bin_width * bw:.1f}" y1="0" x2="{v / bin_width * bw:.1f}" y2="{H}" '
                    f'stroke="#888" stroke-dasharray="3 3"/>' for v in (0.25, 1.5) if v / bin_width < len(counts))
    return (f'<svg viewBox="0 0 {W} {H + 4}" role="img" aria-label="Speeds">'
            f'<line x1="0" y1="{H}" x2="{W}" y2="{H}" stroke="#bbb"/>{bars}{marks}</svg>')


# -- the page -------------------------------------------------------------------------------------

def collect(db: Database, since: float, until: float) -> dict:
    """All the numbers for the report (also handy as JSON)."""
    span = max(until - since, 60)
    bucket = max(60.0, span / 24)
    seconds = db.activity_summary(since)
    total = sum(seconds.get(a, 0) for a in ACTIVITIES)
    summary = db.summary(since)
    alerts = db.events_since(since, ALERT_TYPES, limit=40)
    return {
        "since": since, "until": until, "bucket": bucket,
        "dogs_seen": summary["dogs_seen"],
        "busiest_hour": summary["busiest_hour"],
        "events": summary["events"],
        "alert_counts": {t: summary["events"].get(t, 0) for t in ALERT_TYPES},
        "activity_seconds": {a: seconds.get(a, 0) for a in ACTIVITIES},
        "activity_share": {a: round(seconds.get(a, 0) / total, 3) if total else 0.0 for a in ACTIVITIES},
        "timeline": db.activity_timeline(since, bucket),
        "grid": db.position_grid(since, 16, 9),
        "speeds": db.speed_histogram(since, 0.1, 3.0),
        "alerts": alerts,
        "dogs": db.list_dogs(12, None, 2.0, "longest", since),
    }


def build_report(db: Database, storage_dir: Path, since: float, until: float | None = None,
                 title: str = "Street Dog Monitoring: session report", models: dict | None = None) -> str:
    until = until or datetime.now().timestamp()
    d = collect(db, since, until)
    total_alerts = sum(d["alert_counts"].values())
    share = d["activity_share"]

    cards = [("Dogs seen", d["dogs_seen"]), ("Alerts", total_alerts),
             ("Busiest hour", f'{d["busiest_hour"]}:00' if d["busiest_hour"] is not None else "–"),
             ("Dog-time observed", _duration(sum(d["activity_seconds"].values())))]
    cards_html = "".join(f"<div><b>{escape(str(v))}</b>{escape(k)}</div>" for k, v in cards)
    split = "".join(f'<span style="width:{100 * share[a]}%;background:{COLOURS[a]}"></span>' for a in ACTIVITIES)
    split_text = " · ".join(f"{a.capitalize()} {share[a]:.0%} ({_duration(d['activity_seconds'][a])})"
                            for a in ACTIVITIES)
    alert_counts = " · ".join(f"{ALERT_NAMES[t]}: {n}" for t, n in d["alert_counts"].items())

    alert_rows = []
    for e in d["alerts"]:
        img = thumbnail(storage_dir, e["snapshot"])
        alert_rows.append(
            f"<tr><td>{_when(e['ts'])}</td><td>{escape(ALERT_NAMES.get(e['type'], e['type']))}</td>"
            f"<td>{escape(e['message'])}</td><td>{_img(img) if img else ''}</td></tr>")
    alerts_html = ("<table><thead><tr><th>Time</th><th>Alert</th><th>What happened</th><th>Photo</th></tr></thead>"
                   f"<tbody>{''.join(alert_rows)}</tbody></table>") if alert_rows else "<p class=muted>No alerts.</p>"

    dog_cards = []
    for dog in d["dogs"]:
        img = thumbnail(storage_dir, dog["snapshot"], 160)
        secs = {a: dog[f"{a.lower()}_s"] for a in ACTIVITIES}
        t = sum(secs.values()) or 1
        bar = "".join(f'<span style="width:{100 * secs[a] / t}%;background:{COLOURS[a]}"></span>' for a in ACTIVITIES)
        photo = _img(img, f"Dog {dog['id']}")
        dog_cards.append(
            f'<figure>{photo}'
            f'<figcaption><b>Dog #{dog["id"]}</b> · {escape(dog["source_id"])}<br>'
            f'{_duration(dog["last_seen"] - dog["first_seen"])} · top speed {dog["max_speed"]:.2f}'
            f'<div class="split">{bar}</div></figcaption></figure>')
    dogs_html = f'<div class="dogs">{"".join(dog_cards)}</div>' if dog_cards else "<p class=muted>No dogs.</p>"

    model_html = ""
    if models:
        rows = []
        for label, info in models.items():
            if not info:
                continue
            m = info.get("metrics") or {}
            shown = {k: v for k, v in m.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            numbers = " · ".join(f"{escape(k)} {v}" for k, v in list(shown.items())[:8]) or "no test results saved yet"
            rows.append(f"<tr><td>{escape(label)}</td><td>{escape(str(info.get('name') or info.get('file') or ''))}"
                        f"</td><td>{numbers}</td></tr>")
        if rows:
            model_html = ("<h2>Models</h2><table><thead><tr><th>Model</th><th>File</th><th>Test results</th></tr>"
                          f"</thead><tbody>{''.join(rows)}</tbody></table>")

    period = f"{_when(since)} → {_when(until)} ({_duration(until - since)})"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  body {{ font: 14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; color: #1c2330; background: #fff;
         max-width: 900px; margin: 24px auto; padding: 0 16px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }} h2 {{ font-size: 16px; margin: 26px 0 8px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .muted {{ color: #66707f; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 14px 0; }}
  .cards div {{ background: #f1f3f6; border-radius: 8px; padding: 8px 10px; }} .cards b {{ display: block; font-size: 20px; }}
  .split {{ display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: #e6e8ec; margin: 4px 0; }}
  .split span {{ display: block; height: 100%; }}
  .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }} @media (max-width: 640px) {{ .row {{ grid-template-columns: 1fr; }} }}
  svg {{ width: 100%; height: auto; display: block; }} svg text {{ fill: #66707f; }}
  table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; padding: 5px 6px; border-bottom: 1px solid #e3e5e9; vertical-align: top; }}
  td img {{ width: 120px; border-radius: 4px; }}
  .dogs {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }}
  .dogs figure {{ margin: 0; font-size: 12px; }} .dogs img, .noimg {{ width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px; background: #eee; }}
  .legend span {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 10px; }}
  @media print {{ body {{ margin: 0; }} h2 {{ break-after: avoid; }} tr, figure {{ break-inside: avoid; }} }}
</style></head><body>
<h1>{escape(title)}</h1>
<p class="muted">{period} · generated {_when(datetime.now().timestamp())}</p>
<div class="cards">{cards_html}</div>
<div class="split">{split}</div><p class="muted">{split_text}</p>
<p class="muted">{alert_counts}</p>

<h2>Activity over time</h2>
<p class="legend muted">dog-seconds per {_duration(d['bucket'])}{''.join(f'<span style="background:{COLOURS[a]}"></span>{a.lower()}' for a in ACTIVITIES)}</p>
{timeline_svg(d['timeline'], since, until, d['bucket'])}

<div class="row">
  <div><h2>Where dogs spent time</h2>{heatmap_svg(d['grid'])}<p class="muted">The camera view; darker = more time.</p></div>
  <div><h2>Speeds</h2>{histogram_svg(d['speeds'], 0.1)}
    <p class="muted">Box heights per second, 0 → 3+. Dashed lines: resting &lt; 0.25 ≤ walking &lt; 1.5 ≤ running.</p></div>
</div>

<h2>Alerts ({total_alerts})</h2>
{alerts_html}

<h2>Dogs that stayed longest</h2>
{dogs_html}
{model_html}
<p class="muted" style="margin-top:28px">Street Dog Monitoring System · YOLO11 detection + ByteTrack tracking · numbers from the local SQLite database.</p>
</body></html>
"""


def main(argv=None) -> Path:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--minutes", type=float, default=24 * 60, help="how far back (default 24 h)")
    p.add_argument("--storage", type=Path, default=ROOT / "backend" / "storage", help="the server's storage folder")
    p.add_argument("--out", type=Path, default=Path("session_report.html"))
    p.add_argument("--title", default="Street Dog Monitoring: session report")
    p.add_argument("--model", type=Path, help="detector weights the session used, to list its test results")
    args = p.parse_args(argv)
    if args.minutes <= 0:
        p.error("--minutes must be positive")
    db_path = args.storage / "dogwatch.db"
    if not db_path.exists():
        p.error(f"No database at {db_path}")
    db = Database(db_path)
    try:
        now = datetime.now().timestamp()
        models = None
        if args.model:                           # test results saved by training/detector/evaluate.py
            meta = args.model.with_suffix(".json")
            models = {"Detector": {"name": args.model.name,
                                   "metrics": json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None}}
        html = build_report(db, args.storage, now - args.minutes * 60, now, args.title, models)
    finally:
        db.close()
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} ({len(html) / 1e3:.0f} kB). Open it in a browser; Ctrl+P saves it as PDF.")
    return args.out


if __name__ == "__main__":
    main()
