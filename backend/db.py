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
    snapshot  TEXT
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

    def list_dogs(self, limit: int = 100, source_id: str | None = None,
                  min_seconds: float = 0.0) -> list[dict]:
        sql = "SELECT * FROM dogs WHERE (last_seen - first_seen) >= ?"
        params: list = [min_seconds]
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        sql += " ORDER BY last_seen DESC LIMIT ?"
        params.append(limit)
        return self._read(sql, tuple(params))

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
