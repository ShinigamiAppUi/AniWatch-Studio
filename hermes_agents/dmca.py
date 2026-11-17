"""dmca.py - DMCA: a takedown request becomes a cancelled schedule, and an audit row.

Two decisions worth knowing:

- **The request is recorded before it is judged.** `dmca_requests` keeps the
  requester, the reason and the evidence for every request, including the ones
  this fork refuses. SECURITY.md §10: evidence is never deleted, only statuses
  change.
- **DMCA does not cancel anything itself.** It verifies, writes the
  `DMCA -> EpisodeScheduler` handoff from AGENT-HANDOFFS.md §3 and lets the
  Orchestrator carry it to the EpisodeScheduler node
  (`cancel_from_takedown()`), which is the same chain the office draws. One
  writer for `episode_schedule`, and the office shows who did it.

What is not implemented, and is said out loud: a notice that names only an anime
(`anime_id`) cannot be acted on here, because this fork schedules one
`episode_id` at a time; the request is recorded with `refused` and the reply
names what a person has to do. A purge on the CDN has no endpoint in this fork,
so `cancel_from_takedown()` reports `cdn_purged: false` and why.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from typing import Any

from hermes_bridge import handoff

from . import store
from . import episode_scheduler as sched

log = logging.getLogger(__name__)

#: What a takedown must name before anything can be cancelled
REQUIRED = ('episode_id', 'requester', 'reason')

#: `dmca_requests.status`, in the order they can happen
STATUSES = ('received', 'cancelled', 'unpublished', 'duplicate', 'unknown_episode', 'refused')


def _at(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _con(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return con if con is not None else store.connect()


def _text(value: object, limit: int = 200) -> str:
    return ' '.join(str(value or '').split())[:limit]


def new_id() -> str:
    """`dmca-1a2b3c4d5e`."""
    return f'dmca-{uuid.uuid4().hex[:10]}'


def verify_request(payload: dict) -> dict:
    """Every field a cancellable takedown needs; missing ones are named, not guessed."""
    data = payload if isinstance(payload, dict) else {}
    missing = [name for name in REQUIRED if not _text(data.get(name))]
    return {
        'valid': not missing,
        'missing': missing,
        'episode_id': _text(data.get('episode_id'), 120),
        'requester': _text(data.get('requester'), 200),
        'reason': _text(data.get('reason'), 300),
        'evidence': _text(data.get('evidence'), 500),
        'anime_id': _text(data.get('anime_id'), 120),
    }


def record_request(con: sqlite3.Connection, data: dict, verdict: dict, *,
                   status: str, detail: str = '', now: float | None = None,
                   request_id: str | None = None) -> str:
    """Insert one audit row and return its id. Append-only."""
    at = _at(now)
    ident = request_id or new_id()
    con.execute(
        'INSERT INTO dmca_requests '
        '(id, episode_id, anime_id, requester, reason, evidence, status, detail, created_at, handled_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (ident, verdict.get('episode_id') or None, verdict.get('anime_id') or None,
         verdict.get('requester') or 'tidak disebut', verdict.get('reason') or '',
         verdict.get('evidence') or None, status[:40], detail[:400], at,
         at if status != 'received' else None),
    )
    con.commit()
    return ident


def _update_request(con: sqlite3.Connection, request_id: str, status: str, detail: str,
                    now: float) -> None:
    con.execute(
        'UPDATE dmca_requests SET status = ?, detail = ?, handled_at = ? WHERE id = ?',
        (status[:40], detail[:400], now, request_id),
    )
    con.commit()


def requests(limit: int = 20, con: sqlite3.Connection | None = None) -> list[dict]:
    rows = _con(con).execute(
        'SELECT * FROM dmca_requests ORDER BY created_at DESC LIMIT ?', (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def cancel_from_takedown(payload: object, now: float | None = None) -> dict:
    """The EpisodeScheduler node: cancel a scheduled episode, unpublish a live one.

    `cancel_schedule()` is the atomic `UPDATE ... WHERE status='scheduled'`, so a
    publish round and a takedown cannot both win (episode_scheduler.py).
    """
    data = payload if isinstance(payload, dict) else {}
    episode_id = _text(data.get('episode_id'), 120)
    if not episode_id:
        return {'error': 'episode_id kosong', 'handoff_key': data.get('handoff_key')}
    con = store.connect()
    schedule = sched.get_schedule(con, episode_id)
    if schedule is None:
        return {'error': f'schedule {episode_id} tidak ada', 'episode_id': episode_id}
    if schedule['status'] == 'scheduled':
        cancelled = sched.cancel_schedule(con, episode_id, 'DMCA takedown')
        return {'action': 'cancelled', 'episode_id': episode_id,
                'changes': 1 if cancelled else 0, 'cdn_purged': False}
    if schedule['status'] == 'live':
        return unpublish_episode(episode_id, 'DMCA takedown', now=now, con=con)
    return {'action': 'noop', 'episode_id': episode_id, 'status': schedule['status']}


def unpublish_episode(episode_id: str, reason: str, *, now: float | None = None,
                      con: sqlite3.Connection | None = None) -> dict:
    """A live episode becomes `cancelled`; the row and its files stay for the record."""
    at = _at(now)
    connection = _con(con)
    cur = connection.execute(
        "UPDATE episode_schedule SET status = 'cancelled', cancel_reason = ? "
        "WHERE episode_id = ? AND status = 'live'",
        (f'DMCA: {_text(reason, 120)}', episode_id),
    )
    connection.commit()
    log.warning('dmca: %s unpublished (%d baris)', episode_id, cur.rowcount)
    return {'action': 'unpublished', 'episode_id': episode_id, 'changes': cur.rowcount,
            'cdn_purged': False, 'cdn_reason':
            'purge CDN belum diimplementasikan: fork ini tidak punya endpoint purge',
            'at': at}


def handle_takedown(payload: object, now: float | None = None,
                    con: sqlite3.Connection | None = None, char: Any = None) -> dict:
    """Verify -> record -> hand off to EpisodeScheduler -> follow the chain.

    The returned `action` is what the chain actually did: `cancelled` (never
    live), `unpublished` (was live), `duplicate`, `unknown_episode` or `refused`.
    """
    at = _at(now)
    data = payload if isinstance(payload, dict) else {}
    connection = _con(con)
    verdict = verify_request(data)
    if not verdict['valid']:
        detail = 'kurang: ' + ', '.join(verdict['missing'])
        if verdict['anime_id'] and 'episode_id' in verdict['missing']:
            detail += ' (takedown per anime belum bisa dijalankan fork ini; sebut episode_id)'
        ident = record_request(connection, data, verdict, status='refused', detail=detail, now=at)
        log.warning('dmca: permintaan ditolak (%s)', detail)
        return {'action': 'refused', 'id': ident, 'missing': verdict['missing'],
                'reason': detail}

    episode_id = verdict['episode_id']
    ident = record_request(connection, data, verdict, status='received', now=at)
    schedule = sched.get_schedule(connection, episode_id)
    if schedule is None:
        detail = f'tidak ada jadwal untuk {episode_id}; tidak ada yang dibatalkan'
        _update_request(connection, ident, 'unknown_episode', detail, at)
        return {'action': 'unknown_episode', 'id': ident, 'episode_id': episode_id,
                'reason': detail}
    if schedule['status'] == 'cancelled':
        detail = f'{episode_id} sudah cancelled sebelumnya'
        _update_request(connection, ident, 'duplicate', detail, at)
        return {'action': 'duplicate', 'id': ident, 'episode_id': episode_id,
                'reason': detail, 'cancel_reason': schedule.get('cancel_reason')}

    if char:
        char.update(f'verifikasi takedown {episode_id}', tool='verify_request')
    try:
        key = handoff.hand_off('DMCA', 'EpisodeScheduler', 'takedown', f'episode:{episode_id}',
                               {'episode_id': episode_id}, now=at)
    except (ValueError, handoff.UnknownHandoff) as err:  # noqa: BLE001 - never invent a flow
        detail = f'handoff tidak ditulis: {err}'
        _update_request(connection, ident, 'refused', detail, at)
        return {'action': 'refused', 'id': ident, 'episode_id': episode_id, 'reason': detail}

    chain: list[dict] = []
    try:
        from .orchestrator import follow_handoffs

        chain = follow_handoffs('DMCA')
    except Exception as err:  # noqa: BLE001 - a broken chain must not lose the request
        log.warning('dmca: rantai EpisodeScheduler gagal: %s', err)
    work = (chain[-1].get('work') if chain else None) or {}
    status = str(work.get('action') or 'received')
    if status not in STATUSES:
        status = 'received'
    detail = (f'{episode_id} -> {status}'
              + (f'; cdn_purged={work.get("cdn_purged")}' if work.get('cdn_purged') is not None else ''))
    _update_request(connection, ident, status, detail, at)
    log.warning('dmca: %s %s (%s)', episode_id, status, verdict['requester'])
    return {'action': status, 'id': ident, 'episode_id': episode_id, 'handoff': key,
            'chain': chain, 'cdn_purged': bool(work.get('cdn_purged')),
            'cdn_reason': work.get('cdn_reason'), 'work': work}
