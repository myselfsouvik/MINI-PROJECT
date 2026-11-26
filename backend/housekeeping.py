"""
Storage housekeeping, so a long demo or a week of recording can't fill the disk.

- usage():   size of the database, dog photos, alert photos/clips, recordings
             and free disk space.
- cleanup(): deletes data older than N days: dogs not seen since then (and
             their photos), per-second positions, events and their photos and
             clips, plus photo/clip files nothing points to any more. Zones
             and videos in recordings/ (uploads, captures) are never deleted.

Files are only ever deleted inside the storage folder (dogs/ and alerts/).
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from backend.db import Database

MIN_DAYS = 1 / 24          # never delete data younger than an hour: the camera may still use it
MANAGED = ("dogs", "alerts")


def _folder_size(folder: Path) -> dict:
    files = [f for f in folder.rglob("*") if f.is_file()] if folder.is_dir() else []
    return {"files": len(files), "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1)}


def usage(db: Database, storage_dir: Path, media_dir: Path) -> dict:
    storage_dir, media_dir = Path(storage_dir), Path(media_dir)
    db_bytes = sum(p.stat().st_size for p in storage_dir.glob(db.path.name + "*") if p.is_file())
    disk = shutil.disk_usage(storage_dir)
    return {
        "database_mb": round(db_bytes / 1e6, 1),
        "rows": db.counts(),
        "dog_photos": _folder_size(storage_dir / "dogs"),
        "alert_files": _folder_size(storage_dir / "alerts"),
        "captures": _folder_size(media_dir / "captures"),
        "uploads": _folder_size(media_dir / "uploads"),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "disk_used_share": round(disk.used / disk.total, 3),
    }


def _inside(storage_dir: Path, rel: str) -> Path | None:
    """The file for a stored path, only if it is in dogs/ or alerts/ of the storage folder."""
    root = storage_dir.resolve()
    path = (root / rel).resolve()
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    return path if len(parts) >= 2 and parts[0] in MANAGED else None


def cleanup(db: Database, storage_dir: Path, days: float, dry_run: bool = False, vacuum: bool = False) -> dict:
    if days < MIN_DAYS:
        raise ValueError(f"days must be at least {MIN_DAYS:.3f} (one hour)")
    storage_dir = Path(storage_dir)
    cutoff = time.time() - days * 86400
    result = db.delete_before(cutoff, dry_run=dry_run)

    candidates = {p for p in (_inside(storage_dir, f) for f in result.pop("files")) if p}
    # Files no row points to (e.g. from a deleted database), if they are old enough too.
    keep = {p for p in (_inside(storage_dir, f) for f in db.referenced_files()) if p}
    for folder in MANAGED:
        for f in (storage_dir / folder).glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff and f.resolve() not in keep:
                candidates.add(f.resolve())

    freed = removed = 0
    for path in sorted(candidates):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue                          # in use (Windows): try again next time
        freed += size
        removed += 1
    if vacuum and not dry_run:
        db.vacuum()
    return {**result, "files": removed, "freed_mb": round(freed / 1e6, 1), "freed_bytes": freed, "days": days,
            "dry_run": dry_run, "cutoff": cutoff}


class AutoCleaner:
    """Runs cleanup(keep_days) at start and then every `every` seconds in the background."""

    def __init__(self, db: Database, storage_dir: Path, keep_days: float, every: float = 3600):
        if keep_days < MIN_DAYS:
            raise ValueError(f"keep_days must be at least {MIN_DAYS:.3f}")
        self.db, self.storage_dir, self.keep_days, self.every = db, Path(storage_dir), keep_days, every
        self.last: dict | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="auto-cleanup", daemon=True)

    def start(self) -> "AutoCleaner":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.last = cleanup(self.db, self.storage_dir, self.keep_days)
                self.last_error = None
            except Exception as e:                # keep the server running whatever happens
                self.last_error = str(e)
            self._stop.wait(self.every)
