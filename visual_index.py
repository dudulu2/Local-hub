from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from visual_encoder import pack_vector, unpack_vector


SCHEMA_VERSION = 1


class VisualIndex:
    def __init__(self, root: Path) -> None:
        self.path = root / ".localhub" / "visual-index.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=8.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _init_db(self) -> None:
        with self.lock, self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS media (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    duration REAL NOT NULL DEFAULT 0,
                    encoder TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    frame_count INTEGER NOT NULL,
                    analyzed_at INTEGER NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS frames (
                    path TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    ratio REAL NOT NULL,
                    vector BLOB NOT NULL,
                    quality REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(path, slot)
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS frames_path_idx ON frames(path)")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    path TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    value INTEGER NOT NULL,
                    at INTEGER NOT NULL,
                    PRIMARY KEY(path, tag)
                )
                """
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )

    def signature_matches(self, path: str, size: int, mtime_ns: int, encoder: str) -> bool:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM media WHERE path=? AND size=? AND mtime_ns=? AND encoder=?",
                (path, int(size), int(mtime_ns), encoder),
            ).fetchone()
            return row is not None

    def save_media(
        self,
        path: str,
        *,
        size: int,
        mtime_ns: int,
        duration: float,
        encoder: str,
        vector: tuple[float, ...],
        frames: list[tuple[int, float, tuple[float, ...], float]],
    ) -> None:
        now = int(time.time() * 1000)
        packed = pack_vector(vector)
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """
                    INSERT INTO media(path,size,mtime_ns,duration,encoder,vector,frame_count,analyzed_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(path) DO UPDATE SET
                        size=excluded.size,
                        mtime_ns=excluded.mtime_ns,
                        duration=excluded.duration,
                        encoder=excluded.encoder,
                        vector=excluded.vector,
                        frame_count=excluded.frame_count,
                        analyzed_at=excluded.analyzed_at
                    """,
                    (path, int(size), int(mtime_ns), float(duration or 0), encoder, packed, len(frames), now),
                )
                db.execute("DELETE FROM frames WHERE path=?", (path,))
                db.executemany(
                    "INSERT INTO frames(path,slot,ratio,vector,quality) VALUES(?,?,?,?,?)",
                    [
                        (path, int(slot), float(ratio), pack_vector(frame_vector), float(quality))
                        for slot, ratio, frame_vector, quality in frames
                    ],
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def remove(self, path: str) -> None:
        with self.lock, self._connect() as db:
            db.execute("DELETE FROM frames WHERE path=?", (path,))
            db.execute("DELETE FROM media WHERE path=?", (path,))
            db.execute("DELETE FROM feedback WHERE path=?", (path,))

    def media_vector(self, path: str, encoder: str | None = None) -> tuple[float, ...]:
        with self.lock, self._connect() as db:
            if encoder:
                row = db.execute("SELECT vector FROM media WHERE path=? AND encoder=?", (path, encoder)).fetchone()
            else:
                row = db.execute("SELECT vector FROM media WHERE path=?", (path,)).fetchone()
        return unpack_vector(row["vector"]) if row else ()

    def frame_vectors(self, path: str) -> list[tuple[int, float, tuple[float, ...], float]]:
        with self.lock, self._connect() as db:
            rows = db.execute(
                "SELECT slot,ratio,vector,quality FROM frames WHERE path=? ORDER BY slot",
                (path,),
            ).fetchall()
        return [
            (int(row["slot"]), float(row["ratio"]), unpack_vector(row["vector"]), float(row["quality"]))
            for row in rows
        ]

    def all_media(self, encoder: str | None = None) -> list[dict]:
        with self.lock, self._connect() as db:
            if encoder:
                rows = db.execute(
                    "SELECT path,size,mtime_ns,duration,encoder,vector,frame_count,analyzed_at FROM media WHERE encoder=?",
                    (encoder,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT path,size,mtime_ns,duration,encoder,vector,frame_count,analyzed_at FROM media"
                ).fetchall()
        return [
            {
                "path": row["path"],
                "size": int(row["size"]),
                "mtime_ns": int(row["mtime_ns"]),
                "duration": float(row["duration"]),
                "encoder": row["encoder"],
                "vector": unpack_vector(row["vector"]),
                "frame_count": int(row["frame_count"]),
                "analyzed_at": int(row["analyzed_at"]),
            }
            for row in rows
        ]

    def feedback_for(self, path: str) -> dict[str, int]:
        with self.lock, self._connect() as db:
            rows = db.execute("SELECT tag,value FROM feedback WHERE path=?", (path,)).fetchall()
        return {str(row["tag"]): int(row["value"]) for row in rows}

    def set_feedback(self, path: str, tag: str, value: int) -> None:
        clean = str(tag).strip()
        if not clean:
            return
        value = 1 if int(value) > 0 else -1
        with self.lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO feedback(path,tag,value,at) VALUES(?,?,?,?)
                ON CONFLICT(path,tag) DO UPDATE SET value=excluded.value, at=excluded.at
                """,
                (path, clean, value, int(time.time() * 1000)),
            )

    def stats(self, encoder: str | None = None) -> dict:
        with self.lock, self._connect() as db:
            if encoder:
                row = db.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(frame_count),0) AS frames FROM media WHERE encoder=?",
                    (encoder,),
                ).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(frame_count),0) AS frames FROM media").fetchone()
        return {"media": int(row["n"]), "frames": int(row["frames"])}
