"""shared_context.py - what one agent leaves for another.

A JSON value per key, with the role that wrote it and when (DB-SCHEMA.md §11).
Keys are a convention, not a constraint: `lead:<id>`, `ticket:<id>`,
`episode:<id>`, `handoff:<from>:<to>:<id>`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS context (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    owner TEXT NOT NULL,
    ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_ts ON context (ts);
"""


def default_path() -> Path:
    explicit = os.environ.get('SHARED_DB')
    if explicit:
        return Path(explicit)
    return Path.home() / '.hermes-office' / 'shared.db'


class SharedContext:
    """Thread-safe key/value context in its own SQLite file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else default_path()
        self._lock = threading.Lock()
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._path), timeout=5.0)
        con.row_factory = sqlite3.Row
        return con

    def set(self, key: str, value: Any, owner: str) -> None:
        """Write `value` (any JSON value), replacing what was there."""
        body = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connect() as con:
            con.execute(
                'INSERT INTO context (key, value, owner, ts) VALUES (?, ?, ?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value, owner = excluded.owner, ts = excluded.ts',
                (key, body, owner, time.time()),
            )

    def get(self, key: str) -> Any | None:
        """The value, or None when nobody wrote that key."""
        with self._lock, self._connect() as con:
            row = con.execute('SELECT value FROM context WHERE key = ?', (key,)).fetchone()
        return json.loads(row['value']) if row else None

    def update(self, key: str, patch: dict, owner: str) -> Any:
        """Merge `patch` into a dict value; a missing key starts from `{}`."""
        with self._lock:
            current = self.get(key)
            merged = {**(current if isinstance(current, dict) else {}), **patch}
            self.set(key, merged, owner)
            return merged

    def delete(self, key: str) -> bool:
        with self._lock, self._connect() as con:
            cur = con.execute('DELETE FROM context WHERE key = ?', (key,))
            return cur.rowcount > 0

    def find(self, prefix: str) -> dict[str, Any]:
        """Every key starting with `prefix` (e.g. `lead:`), newest first."""
        with self._lock, self._connect() as con:
            rows = con.execute(
                'SELECT key, value FROM context WHERE key LIKE ? ORDER BY ts DESC',
                (f'{prefix}%',),
            ).fetchall()
        return {r['key']: json.loads(r['value']) for r in rows}

    def cleanup_older_than(self, hours: float = 24.0) -> int:
        """Delete rows last written more than `hours` ago; returns the count."""
        cutoff = time.time() - hours * 3600
        with self._lock, self._connect() as con:
            cur = con.execute('DELETE FROM context WHERE ts < ?', (cutoff,))
            return cur.rowcount


_default: SharedContext | None = None
_default_lock = threading.Lock()


def default() -> SharedContext:
    """The process-wide context, created on first use."""
    global _default
    with _default_lock:
        if _default is None:
            _default = SharedContext()
        return _default
