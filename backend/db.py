"""
SQLite storage for dogs, observations and events.

Plain ``sqlite3`` (built into Python): no server to install, the whole
database is one file in ``backend/storage/``. All methods are thread-safe so
several camera pipelines can write at once.

Tables
    dogs          one row per tracked dog (per camera session)
    observations  position / speed / activity, at most one row per dog per second;
                  position (center_x, center_y) is a fraction of the frame, 0..1
    events        things that happened: dog appeared, dog left, alerts
    zones         areas drawn on a camera view; kept per camera (kind:value)
                  so they survive a server restart
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import quote

SCHEMA = """
CREATE TABLE IF NOT EXISTS dogs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT    NOT NULL,
    track_id        INTEGER NOT NULL,
    first_seen      REAL    NOT NULL,
    last_seen       REAL    NOT NULL,
    best_confidence REAL    NOT NULL DEFAULT 0,
    snapshot        TEXT,
    resting_s       REAL    NOT NULL DEFAULT 0,
    walking_s       REAL    NOT NULL DEFAULT 0,
    running_s       REAL    NOT NULL DEFAULT 0,
    max_speed       REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS observations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dog_id     INTEGER NOT NULL REFERENCES dogs(id) ON DELETE CASCADE,
    ts         REAL    NOT NULL,
    center_x   REAL    NOT NULL,
    center_y   REAL    NOT NULL,
    speed      REAL    NOT NULL,
    activity   TEXT    NOT NULL,
    confidence REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_dog_ts ON observations(dog_id, ts);
CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(ts);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    source_id TEXT    NOT NULL,
    type      TEXT    NOT NULL,
    dog_id    INTEGER REFERENCES dogs(id) ON DELETE SET NULL,
    message   TEXT    NOT NULL,
    snapshot  TEXT,
    clip      TEXT                         -- short video around an alert
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, id);

CREATE TABLE IF NOT EXISTS zones (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_key TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    points     TEXT    NOT NULL,           -- JSON [[x, y], ...] as fractions of the frame
    created    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_zones_camera ON zones(camera_key);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            # Databases made before alert clips existed: add the column.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)")}
            if "clip" not in cols:
                self._conn.execute("ALTER TABLE events ADD COLUMN clip TEXT")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- low level -------------------------------------------------------------

    def _write(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def _read(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # -- dogs ------------------------------------------------------------------

    def add_dog(self, source_id: str, track_id: int, ts: float, confidence: float) -> int:
        return self._write(
            "INSERT INTO dogs (source_id, track_id, first_seen, last_seen, best_confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, track_id, ts, ts, confidence),
        )

    def update_dog(self, dog_id: int, *, last_seen: float, seconds_in: dict, max_speed: float,
                   best_confidence: float | None = None, snapshot: str | None = None) -> None:
        sets = ["last_seen = ?", "resting_s = ?", "walking_s = ?", "running_s = ?",
                "max_speed = MAX(max_speed, ?)"]
        params: list = [last_seen, seconds_in["RESTING"], seconds_in["WALKING"],
                        seconds_in["RUNNING"], max_speed]
        if best_confidence is not None:
            sets.append("best_confidence = ?")
            params.append(best_confidence)
        if snapshot is not None:
            sets.append("snapshot = ?")
            params.append(snapshot)
        params.append(dog_id)
        self._write(f"UPDATE dogs SET {', '.join(sets)} WHERE id = ?", tuple(params))

    def get_dog(self, dog_id: int) -> dict | None:
        rows = self._read("SELECT * FROM dogs WHERE id = ?", (dog_id,))
        return rows[0] if rows else None

    DOG_ORDER = {
        "recent": "last_seen DESC",
        "longest": "(last_seen - first_seen) DESC",
        "fastest": "max_speed DESC",
        "active": "(walking_s + running_s) DESC",
        "oldest": "first_seen ASC",
    }

    def list_dogs(self, limit: int = 100, source_id: str | None = None,
                  min_seconds: float = 0.0, sort: str = "recent", since: float = 0.0) -> list[dict]:
        if sort not in self.DOG_ORDER:
            raise ValueError(f"sort must be one of {list(self.DOG_ORDER)}")
        sql = "SELECT * FROM dogs WHERE (last_seen - first_seen) >= ? AND last_seen >= ?"
        params: list = [min_seconds, since]
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        sql += f" ORDER BY {self.DOG_ORDER[sort]}, id DESC LIMIT ?"     # ORDER from a fixed list only
        params.append(limit)
        return self._read(sql, tuple(params))

    def dog_path(self, dog_id: int, max_points: int = 300) -> list[dict]:
        """Where the dog went: evenly thinned positions (0..1 of the frame), oldest first."""
        rows = self._read(
            "SELECT ts, center_x AS x, center_y AS y, activity FROM observations "
            "WHERE dog_id = ? AND center_x <= 1 AND center_y <= 1 ORDER BY ts", (dog_id,))
        if len(rows) > max_points:
            step = len(rows) / max_points
            rows = [rows[int(i * step)] for i in range(max_points - 1)] + [rows[-1]]
        return rows

    def dog_events(self, dog_id: int, limit: int = 100) -> list[dict]:
        return self._read("SELECT * FROM events WHERE dog_id = ? ORDER BY id DESC LIMIT ?", (dog_id, limit))

    # -- observations ----------------------------------------------------------

    def add_observation(self, dog_id: int, ts: float, center: tuple[float, float],
                        speed: float, activity: str, confidence: float) -> None:
        self._write(
            "INSERT INTO observations (dog_id, ts, center_x, center_y, speed, activity, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dog_id, ts, center[0], center[1], speed, activity, confidence),
        )

    def observations(self, dog_id: int | None = None, since: float = 0.0,
                     limit: int = 5000) -> list[dict]:
        sql = "SELECT * FROM observations WHERE ts >= ?"
        params: list = [since]
        if dog_id is not None:
            sql += " AND dog_id = ?"
            params.append(dog_id)
        sql += " ORDER BY ts LIMIT ?"
        params.append(limit)
        return self._read(sql, tuple(params))

    def activity_summary(self, since: float = 0.0) -> dict:
        """Seconds of observations per activity (each observation ≈ 1 s)."""
        rows = self._read(
            "SELECT activity, COUNT(*) AS n FROM observations WHERE ts >= ? GROUP BY activity",
            (since,),
        )
        out = {"RESTING": 0, "WALKING": 0, "RUNNING": 0}
        out.update({r["activity"]: r["n"] for r in rows})
        return out

    # -- analytics -------------------------------------------------------------
    # Observations are ~1 per dog per second, so a count of rows ≈ dog-seconds.

    def _obs_filter(self, since: float, source_id: str | None) -> tuple[str, list]:
        sql = " FROM observations o JOIN dogs d ON d.id = o.dog_id WHERE o.ts >= ?"
        params: list = [since]
        if source_id:
            sql += " AND d.source_id = ?"
            params.append(source_id)
        return sql, params

    def activity_timeline(self, since: float, bucket: float, source_id: str | None = None) -> list[dict]:
        """Dog-seconds per activity in time buckets of ``bucket`` seconds."""
        where, params = self._obs_filter(since, source_id)
        rows = self._read(
            "SELECT CAST((o.ts - ?) / ? AS INTEGER) AS b, o.activity AS activity, COUNT(*) AS n"
            + where + " GROUP BY b, o.activity ORDER BY b",
            tuple([since, bucket] + params),
        )
        out: dict[int, dict] = {}
        for r in rows:
            item = out.setdefault(r["b"], {"start": since + r["b"] * bucket,
                                           "RESTING": 0, "WALKING": 0, "RUNNING": 0})
            item[r["activity"]] = r["n"]
        return [out[b] for b in sorted(out)]

    def speed_histogram(self, since: float, bin_width: float, max_speed: float,
                        source_id: str | None = None) -> list[int]:
        """Counts of observed speeds in bins [0, w), [w, 2w), …; the last bin holds everything above."""
        bins = max(1, int(round(max_speed / bin_width)))
        where, params = self._obs_filter(since, source_id)
        rows = self._read(
            "SELECT MIN(CAST(o.speed / ? AS INTEGER), ?) AS b, COUNT(*) AS n" + where + " GROUP BY b",
            tuple([bin_width, bins - 1] + params),
        )
        counts = [0] * bins
        for r in rows:
            counts[max(0, r["b"])] += r["n"]
        return counts

    def position_grid(self, since: float, cols: int, rows_: int,
                      source_id: str | None = None) -> list[list[int]]:
        """How often a dog was seen in each cell of a cols × rows grid over the frame."""
        where, params = self._obs_filter(since, source_id)
        rows = self._read(
            "SELECT MIN(CAST(o.center_x * ? AS INTEGER), ?) AS cx, MIN(CAST(o.center_y * ? AS INTEGER), ?) AS cy,"
            " COUNT(*) AS n" + where + " AND o.center_x BETWEEN 0 AND 1 AND o.center_y BETWEEN 0 AND 1"
            " GROUP BY cx, cy",
            tuple([cols, cols - 1, rows_, rows_ - 1] + params),
        )
        grid = [[0] * cols for _ in range(rows_)]
        for r in rows:
            grid[r["cy"]][r["cx"]] += r["n"]
        return grid

    def summary(self, since: float) -> dict:
        dogs = self._read("SELECT COUNT(*) AS n FROM dogs WHERE last_seen >= ? "
                          "AND last_seen - first_seen >= 1", (since,))[0]["n"]
        types = self._read("SELECT type, COUNT(*) AS n FROM events WHERE ts >= ? GROUP BY type", (since,))
        busiest = self._read(
            "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour, COUNT(*) AS n "
            "FROM observations WHERE ts >= ? GROUP BY hour ORDER BY n DESC LIMIT 1", (since,))
        return {"dogs_seen": dogs, "events": {r["type"]: r["n"] for r in types},
                "busiest_hour": busiest[0]["hour"] if busiest else None}

    # -- events ----------------------------------------------------------------

    def add_event(self, source_id: str, type_: str, message: str,
                  dog_id: int | None = None, snapshot: str | None = None,
                  ts: float | None = None) -> int:
        return self._write(
            "INSERT INTO events (ts, source_id, type, dog_id, message, snapshot) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts or time.time(), source_id, type_, dog_id, message, snapshot),
        )

    def events_since(self, since: float, types: tuple[str, ...] | None = None, limit: int = 100) -> list[dict]:
        """Events at or after `since`, newest first (optionally only some types)."""
        sql, params = "SELECT * FROM events WHERE ts >= ?", [since]
        if types:
            sql += f" AND type IN ({', '.join('?' * len(types))})"
            params.extend(types)
        return self._read(sql + " ORDER BY ts DESC LIMIT ?", tuple(params + [limit]))

    def set_event_clip(self, event_id: int, clip: str) -> None:
        self._write("UPDATE events SET clip = ? WHERE id = ?", (clip, event_id))

    def list_events(self, limit: int = 100, type_: str | None = None,
                    after_id: int = 0, types: tuple[str, ...] | None = None) -> list[dict]:
        sql = "SELECT * FROM events WHERE id > ?"
        params: list = [after_id]
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        if types:
            sql += f" AND type IN ({', '.join('?' * len(types))})"
            params.extend(types)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self._read(sql, tuple(params))

    # -- housekeeping ----------------------------------------------------------

    def counts(self) -> dict:
        with self._lock:
            return {t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("dogs", "observations", "events", "zones")}

    def delete_before(self, cutoff: float, dry_run: bool = False) -> dict:
        """
        Remove data older than `cutoff` (a timestamp): dogs last seen before it
        (with their per-second rows), older per-second rows of other dogs, and
        older events. Zones are kept. Returns the counts and the files
        (snapshots, alert photos and clips) that belonged to the removed rows,
        so the caller can delete them.
        """
        with self._lock:
            q = lambda sql: self._conn.execute(sql, (cutoff,)).fetchall()     # noqa: E731
            dog_files = [r[0] for r in q("SELECT snapshot FROM dogs WHERE last_seen < ? AND snapshot IS NOT NULL")]
            event_files = [f for r in q("SELECT snapshot, clip FROM events WHERE ts < ?") for f in r if f]
            result = {
                "dogs": q("SELECT COUNT(*) FROM dogs WHERE last_seen < ?")[0][0],
                "observations": self._conn.execute(
                    "SELECT COUNT(*) FROM observations WHERE ts < ? OR dog_id IN "
                    "(SELECT id FROM dogs WHERE last_seen < ?)", (cutoff, cutoff)).fetchone()[0],
                "events": q("SELECT COUNT(*) FROM events WHERE ts < ?")[0][0],
                "files": dog_files + event_files,
            }
            if not dry_run:
                try:
                    self._conn.execute("DELETE FROM observations WHERE ts < ?", (cutoff,))
                    self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                    self._conn.execute("DELETE FROM dogs WHERE last_seen < ?", (cutoff,))   # cascades
                    self._conn.commit()
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return result

    def referenced_files(self) -> set[str]:
        """Every snapshot / clip path the database still points to."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT snapshot FROM dogs UNION SELECT snapshot FROM events UNION SELECT clip FROM events").fetchall()
        return {r[0] for r in rows if r[0]}

    def vacuum(self) -> None:
        """Give freed space back to the disk (can take a few seconds on a big database)."""
        with self._lock:
            self._conn.execute("VACUUM")

    # -- export ----------------------------------------------------------------

    EXPORTS = {
        "dogs": ("SELECT id, source_id, track_id, first_seen, last_seen, "
                 "ROUND(last_seen - first_seen, 1) AS seconds_visible, ROUND(resting_s, 1) AS resting_s, "
                 "ROUND(walking_s, 1) AS walking_s, ROUND(running_s, 1) AS running_s, "
                 "ROUND(max_speed, 3) AS max_speed, ROUND(best_confidence, 3) AS best_confidence, snapshot "
                 "FROM dogs WHERE last_seen >= ? ORDER BY id"),
        "observations": ("SELECT o.id, o.dog_id, d.source_id, o.ts, o.center_x, o.center_y, o.speed, "
                         "o.activity, o.confidence FROM observations o JOIN dogs d ON d.id = o.dog_id "
                         "WHERE o.ts >= ? ORDER BY o.id"),
        "events": ("SELECT id, ts, source_id, type, dog_id, message, snapshot, clip FROM events "
                   "WHERE ts >= ? ORDER BY id"),
    }

    def export_rows(self, name: str, since: float = 0.0):
        """
        Yields the column names, then each row, from its own read-only
        connection, so a big export doesn't block the camera writing to the DB.
        """
        if name not in self.EXPORTS:
            raise ValueError(f"export must be one of {list(self.EXPORTS)}")
        uri = f"file:{quote(self.path.resolve().as_posix(), safe='/:')}?mode=ro"     # spaces etc. escaped
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            cur = conn.execute(self.EXPORTS[name], (since,))
            yield [c[0] for c in cur.description]
            while batch := cur.fetchmany(500):
                yield from batch
        finally:
            conn.close()

    # -- zones -----------------------------------------------------------------

    def add_zone(self, camera_key: str, name: str, points: list) -> int:
        return self._write(
            "INSERT INTO zones (camera_key, name, points, created) VALUES (?, ?, ?, ?)",
            (camera_key, name, json.dumps(points), time.time()),
        )

    def list_zones(self, camera_key: str | None = None) -> list[dict]:
        if camera_key is None:
            rows = self._read("SELECT * FROM zones ORDER BY id")
        else:
            rows = self._read("SELECT * FROM zones WHERE camera_key = ? ORDER BY id", (camera_key,))
        for r in rows:
            r["points"] = json.loads(r["points"])
        return rows

    def get_zone(self, zone_id: int) -> dict | None:
        rows = self._read("SELECT * FROM zones WHERE id = ?", (zone_id,))
        if not rows:
            return None
        rows[0]["points"] = json.loads(rows[0]["points"])
        return rows[0]

    def delete_zone(self, zone_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
            self._conn.commit()
            return cur.rowcount > 0
