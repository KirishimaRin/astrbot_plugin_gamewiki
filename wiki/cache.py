"""Bounded persistent cache. SQLite connections stay inside worker threads."""

import asyncio
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path


class Cache:
    def __init__(
        self, directory: Path, max_entries: int = 128, max_bytes: int = 64 << 20
    ):
        self.path = directory / "wiki-cache.sqlite3"
        self.max_entries = max_entries
        self.max_bytes = max_bytes

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=3)
        # WAL lets concurrent readers and the touch/eviction writers coexist
        # instead of turning hits into OperationalError misses under load.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, expires REAL, touched REAL, value TEXT)"
        )
        return conn

    def _get(self, key: str):
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT value FROM cache WHERE key=? AND expires>?",
                (key, time.time()),
            ).fetchone()
            if row:
                # Refreshing touched turns plain FIFO eviction into LRU; WAL
                # keeps this small write from blocking concurrent readers.
                conn.execute(
                    "UPDATE cache SET touched=? WHERE key=?", (time.time(), key)
                )
        return json.loads(row[0]) if row else None

    async def get(self, key: str):
        try:
            return await asyncio.to_thread(self._get, key)
        except (OSError, sqlite3.Error, ValueError):
            # Cache availability must not prevent a live lookup.
            return None

    def _put(self, key: str, value: dict, ttl: float):
        now = time.time()
        payload = json.dumps(value, ensure_ascii=False)
        if len(payload.encode()) > self.max_bytes:
            return
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM cache WHERE expires<=?", (now,))
            conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                (key, now + ttl, now, payload),
            )
            conn.execute(
                "DELETE FROM cache WHERE key NOT IN "
                "(SELECT key FROM cache ORDER BY touched DESC LIMIT ?)",
                (self.max_entries,),
            )
            total = 0
            rows = conn.execute(
                "SELECT key, length(CAST(value AS BLOB)) FROM cache "
                "ORDER BY touched DESC"
            ).fetchall()
            for evict_key, size in rows:
                total += size
                if total > self.max_bytes:
                    conn.execute("DELETE FROM cache WHERE key=?", (evict_key,))

    async def put(self, key: str, value: dict, ttl: float):
        if ttl <= 0:
            return
        try:
            await asyncio.to_thread(self._put, key, value, ttl)
        except (OSError, sqlite3.Error):
            pass

    def _clear(self) -> int:
        with closing(self._connect()) as conn, conn:
            deleted = conn.execute("SELECT count(*) FROM cache").fetchone()[0]
            conn.execute("DELETE FROM cache")
        return deleted

    async def clear(self) -> int:
        """Drop every cached HTTP body; used by the admin 清缓存 command."""
        try:
            return await asyncio.to_thread(self._clear)
        except (OSError, sqlite3.Error):
            return 0

    def _health(self) -> dict:
        result = {"readable": True, "writable": False, "entries": 0, "bytes": 0}
        try:
            if self.path.exists():
                # Inspect the real cache without changing schema, LRU, or content.
                uri = self.path.resolve().as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True, timeout=3)) as conn:
                    row = conn.execute(
                        "SELECT count(*), coalesce(sum(length(CAST(value AS BLOB))), 0) "
                        "FROM cache WHERE expires>?",
                        (time.time(),),
                    ).fetchone()
                    result.update(entries=row[0], bytes=row[1])
        except (OSError, sqlite3.Error):
            result["readable"] = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Test SQLite writes in a disposable database, preserving cached pages.
            with tempfile.TemporaryDirectory(
                prefix=".doctor-", dir=self.path.parent
            ) as directory:
                with (
                    closing(sqlite3.connect(Path(directory) / "probe.sqlite3")) as conn,
                    conn,
                ):
                    conn.execute("CREATE TABLE probe (value INTEGER)")
                    conn.execute("INSERT INTO probe VALUES (1)")
                    result["writable"] = conn.execute(
                        "SELECT value FROM probe"
                    ).fetchone() == (1,)
        except (OSError, sqlite3.Error):
            result["writable"] = False
        return result

    async def health(self) -> dict:
        return await asyncio.to_thread(self._health)
