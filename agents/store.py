"""store.py - the two places the pipeline writes: shared context and the DB.

An episode's working state lives in `context` (`episode:<id>`, DB-SCHEMA.md §11)
so any agent can pick it up; the durable facts live in `hermes.db`
(`subtitle_tracks`, `episode_schedule`). Both come from hermes_bridge, so the
paths and the schema stay in one place.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from hermes_bridge import db as bdb
from hermes_bridge.shared_context import SharedContext, default as default_context

_initialised = False


def context() -> SharedContext:
    return default_context()


def connect() -> sqlite3.Connection:
    """The business DB, initialised once per process."""
    global _initialised
    if not _initialised:
        bdb.init_db()
        _initialised = True
    return bdb.connect()


def key(episode_id: str) -> str:
    return f'episode:{episode_id}'


def get_episode(episode_id: str) -> dict | None:
    value = context().get(key(episode_id))
    return value if isinstance(value, dict) else None


def save_episode(episode_id: str, data: dict, owner: str) -> dict:
    context().set(key(episode_id), data, owner)
    return data


def update_episode(episode_id: str, patch: dict, owner: str) -> dict:
    return context().update(key(episode_id), patch, owner)


# ---------------------------------------------------------------------------
# subtitle_tracks (DB-SCHEMA.md §6)
# ---------------------------------------------------------------------------

def upsert_track(con: sqlite3.Connection, episode_id: str, lang: str, path: str, *,
                 source: str, status: str, qa_score: float | None = None, updated_at: float) -> None:
    con.execute(
        'INSERT INTO subtitle_tracks (episode_id, lang, source, path, qa_score, status, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(episode_id, lang) DO UPDATE SET source = excluded.source, path = excluded.path, '
        'qa_score = excluded.qa_score, status = excluded.status, updated_at = excluded.updated_at',
        (episode_id, lang, source, path, qa_score, status, updated_at),
    )
    con.commit()


def set_track_status(con: sqlite3.Connection, episode_id: str, lang: str, status: str, updated_at: float) -> None:
    con.execute(
        'UPDATE subtitle_tracks SET status = ?, updated_at = ? WHERE episode_id = ? AND lang = ?',
        (status, updated_at, episode_id, lang),
    )
    con.commit()


def tracks(con: sqlite3.Connection, episode_id: str) -> list[dict[str, Any]]:
    rows = con.execute(
        'SELECT episode_id, lang, source, path, qa_score, status, updated_at '
        'FROM subtitle_tracks WHERE episode_id = ? ORDER BY lang',
        (episode_id,),
    ).fetchall()
    return [dict(r) for r in rows]
