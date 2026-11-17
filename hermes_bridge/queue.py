"""queue.py - the dead-letter queue for events the office could not take.

Why a queue at all: the office server can be restarting, or the bridge can be
started before it, and a business agent must not lose the `agent_start` that
puts its character on screen. Every failed POST is written to `dlq.db` and
retried; after ten attempts it stays on disk for a human to inspect instead of
being dropped.

Two rules from DB-SCHEMA.md §10 that this file keeps:

- The flusher replays with the *single-attempt* senders it was given, never
  with the retrying path, so a replay that fails does not add a second row.
- A row is `payload` JSON, `ts`, `attempts`, `last_err` - nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 10
FLUSH_GAP_S = 30.0
FLUSH_LIMIT = 50
BACKOFF_S = 30.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS dlq (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    payload  TEXT NOT NULL,
    ts       REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_err TEXT
);
CREATE INDEX IF NOT EXISTS idx_dlq_ts ON dlq (ts);
"""


def default_path() -> Path:
    """`$DLQ_DB`, else `~/.hermes-office/dlq.db`."""
    explicit = os.environ.get('DLQ_DB')
    if explicit:
        return Path(explicit)
    return Path.home() / '.hermes-office' / 'dlq.db'


class DeadLetterQueue:
    """A small SQLite queue with a background flusher.

    Args:
        post_event: sends one event payload to `/event` and raises on failure
        post_metrics: sends one metrics delta to `/biz-metrics`
        path: the database file (defaults to `default_path()`)
    """

    def __init__(
        self,
        post_event: Callable[[dict], None],
        post_metrics: Callable[[dict], None],
        path: Path | None = None,
    ) -> None:
        self._post_event = post_event
        self._post_metrics = post_metrics
        self._path = Path(path) if path else default_path()
        self._lock = threading.Lock()
        self._last_flush = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._path), timeout=5.0)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(SCHEMA)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def push(self, payload: dict, error: str = '') -> None:
        """Keep a payload the office refused, and start the flusher once."""
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        try:
            with self._lock, self._connect() as con:
                con.execute(
                    'INSERT INTO dlq (payload, ts, attempts, last_err) VALUES (?, ?, 0, ?)',
                    (body, time.time(), error[:500]),
                )
        except sqlite3.Error as err:  # a full disk must not mask the original error
            log.error('dlq: could not store %s: %s', payload.get('type', '?'), err)
            return
        self._ensure_flusher()

    def pending(self) -> int:
        """Rows still waiting, including the ones out of attempts."""
        with self._lock, self._connect() as con:
            return int(con.execute('SELECT COUNT(*) FROM dlq').fetchone()[0])

    def flush(self, force: bool = False) -> int:
        """Replay due rows; returns how many the office accepted.

        Called before every send (throttled to `FLUSH_GAP_S`) and by the
        background thread, so a queue left by an earlier process drains as soon
        as the office is back.
        """
        now = time.time()
        if not force and now - self._last_flush < FLUSH_GAP_S:
            return 0
        with self._lock:
            self._last_flush = now
            try:
                con = self._connect()
            except sqlite3.Error:
                return 0
            sent = 0
            try:
                rows = con.execute(
                    'SELECT id, payload, ts, attempts FROM dlq WHERE attempts < ? ORDER BY id LIMIT ?',
                    (MAX_ATTEMPTS, FLUSH_LIMIT),
                ).fetchall()
                for row in rows:
                    # Backoff per row: a sidecar that is down stays down for a while
                    if now - float(row['ts']) < min(BACKOFF_S * (int(row['attempts']) + 1), 600.0):
                        continue
                    try:
                        payload = json.loads(row['payload'])
                        self._replay(payload)
                    except Exception as err:  # noqa: BLE001 - any failure means "try later"
                        con.execute(
                            'UPDATE dlq SET attempts = attempts + 1, last_err = ? WHERE id = ?',
                            (str(err)[:500], row['id']),
                        )
                        con.commit()
                        continue
                    con.execute('DELETE FROM dlq WHERE id = ?', (row['id'],))
                    con.commit()
                    sent += 1
            finally:
                con.close()
        return sent

    def _replay(self, payload: dict) -> None:
        if payload.get('__type') == 'biz_metrics':
            self._post_metrics(dict(payload.get('delta') or {}))
        else:
            self._post_event(payload)

    def _ensure_flusher(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name='hermes-dlq', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(FLUSH_GAP_S):
            try:
                self.flush(force=True)
            except Exception as err:  # noqa: BLE001 - the flusher must never die
                log.warning('dlq: flush failed: %s', err)

    def stop(self) -> None:
        """Ask the flusher to finish (used by tests and the smoke run)."""
        self._stop.set()
