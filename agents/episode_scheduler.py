"""episode_scheduler.py - the embargo queue (DB-SCHEMA.md §5).

Two transitions must be atomic, because DMCA can cancel while a publish round is
already running:

    publish:  UPDATE ... SET status='live'      WHERE episode_id=? AND status='scheduled'
    cancel:   UPDATE ... SET status='cancelled' WHERE episode_id=? AND status='scheduled'

`changes == 0` on publish means the schedule was cancelled (or already live), so
the caller must not announce it. Times are epoch **seconds** (`time.time()`).
"""

from __future__ import annotations

import sqlite3
import time


def schedule_episode(con: sqlite3.Connection, *, episode_id: str, anime_title: str,
                     episode_number: int, encoded_path: str, embargo_until: float,
                     regions: str = '["*"]') -> bool:
    """Queue an episode, or move its embargo while it is still scheduled.

    Returns True when the row is scheduled afterwards; False when the episode is
    live or cancelled (a reschedule after either is a new episode, not an edit).
    """
    now = time.time()
    con.execute(
        'INSERT INTO episode_schedule '
        '(episode_id, anime_title, episode_number, encoded_path, embargo_until, regions, status, created_at) '
        "VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?) "
        'ON CONFLICT(episode_id) DO UPDATE SET embargo_until = excluded.embargo_until, '
        'encoded_path = excluded.encoded_path, regions = excluded.regions '
        "WHERE episode_schedule.status = 'scheduled'",
        (episode_id, anime_title, episode_number, encoded_path, embargo_until, regions, now),
    )
    con.commit()
    row = con.execute('SELECT status FROM episode_schedule WHERE episode_id = ?', (episode_id,)).fetchone()
    return bool(row) and row['status'] == 'scheduled'


def due_episodes(con: sqlite3.Connection, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    rows = con.execute(
        "SELECT episode_id, anime_title, episode_number, encoded_path, embargo_until "
        "FROM episode_schedule WHERE status = 'scheduled' AND embargo_until <= ? ORDER BY embargo_until",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def publish_episode(con: sqlite3.Connection, episode_id: str, now: float | None = None) -> bool:
    """Publish one episode if it is still scheduled. False means: do not announce."""
    now = time.time() if now is None else now
    cur = con.execute(
        "UPDATE episode_schedule SET status = 'live', published_at = ? "
        "WHERE episode_id = ? AND status = 'scheduled'",
        (now, episode_id),
    )
    con.commit()
    return cur.rowcount > 0


def publish_due_episodes(con: sqlite3.Connection, now: float | None = None) -> list[dict]:
    """Publish everything whose embargo has passed; returns what actually went live."""
    published = []
    for row in due_episodes(con, now):
        if publish_episode(con, row['episode_id'], now):
            published.append(row)
    return published


def cancel_schedule(con: sqlite3.Connection, episode_id: str, reason: str) -> bool:
    """DMCA/manual: only while scheduled. False when it is already live — that
    episode needs unpublish + purge, which is a different operation."""
    cur = con.execute(
        "UPDATE episode_schedule SET status = 'cancelled', cancel_reason = ? "
        "WHERE episode_id = ? AND status = 'scheduled'",
        (reason[:300], episode_id),
    )
    con.commit()
    return cur.rowcount > 0


def get_schedule(con: sqlite3.Connection, episode_id: str) -> dict | None:
    row = con.execute('SELECT * FROM episode_schedule WHERE episode_id = ?', (episode_id,)).fetchone()
    return dict(row) if row else None
