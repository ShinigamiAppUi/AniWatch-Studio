"""sec_ops.py - SecOps: four rules, an incident log, and no event storm.

The rules and the actions are AGENTS.md §4.6's table, unchanged:

    login_attempts      5 / 60 s     ban_ip
    concurrent_devices  3 / 300 s    soft_lock
    request_rate      120 / 60 s     rate_limit
    chargeback_count    2 / -        flag_account

Where the events come from matters, and this module refuses to pretend:

- `SECURITY_EVENT_FEED` is a JSONL file of access events
  (`{"at": epoch, "type": "login_failed"|"session_open"|"request", "ip"?, "user_id"?}`).
  This fork has no web-server access log of its own, so **without the file the
  three request rules cannot run** - `insufficient` says so by name instead of
  reporting zero violations as if the traffic were clean.
- `chargeback_count` is read from `payment_events` (status `chargeback`), which
  is real data written by PaymentAgent, so that rule works on a bare install.

Two more rules the office's own docs demand:

- **No event storm.** `monitor()` only touches the character when there is a
  violation (PLAN.md §Risiko; a 10-second loop that draws a character every
  round floods the office).
- **Audit is append-only.** `security_incidents` gets a row per action, and
  `unban` is a new row, never a delete (SECURITY.md §10).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from . import config, store

log = logging.getLogger(__name__)

#: (rule, event type in the feed, threshold, window seconds, action)
RULES: tuple[dict[str, Any], ...] = (
    {'rule': 'login_attempts', 'type': 'login_failed', 'threshold': 5, 'window_s': 60,
     'action': 'ban_ip'},
    {'rule': 'concurrent_devices', 'type': 'session_open', 'threshold': 3, 'window_s': 300,
     'action': 'soft_lock'},
    {'rule': 'request_rate', 'type': 'request', 'threshold': 120, 'window_s': 60,
     'action': 'rate_limit'},
    {'rule': 'chargeback_count', 'type': None, 'threshold': 2, 'window_s': None,
     'action': 'flag_account'},
)

#: Same rule on the same target inside this window is one incident, not a stream
COOLDOWN_S = 300.0

#: How much of the feed is read in one pass; older lines are not needed for a 5-minute window
MAX_EVENTS = 5000

#: Actions that keep a target out until an `unban` row says otherwise
BLOCKING_ACTIONS = ('ban_ip', 'soft_lock', 'rate_limit', 'flag_account')


def _at(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _con(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return con if con is not None else store.connect()


def feed_path() -> Path | None:
    """`SECURITY_EVENT_FEED`, or None when it is not configured."""
    raw = config.security_event_feed()
    return Path(raw).expanduser() if raw else None


def load_events(path: Path | None = None, limit: int = MAX_EVENTS) -> tuple[list[dict], str | None]:
    """Read the access feed. Returns `(events, why it is empty)` - never raises.

    A bad line is skipped and counted in the log, because one truncated write
    must not blind SecOps to the rest of the file.
    """
    target = path if path is not None else feed_path()
    if target is None:
        return [], 'SECURITY_EVENT_FEED kosong, jadi rule login/devices/rate tidak bisa dihitung'
    try:
        lines = target.read_text(encoding='utf-8').splitlines()[-limit:]
    except OSError as err:
        return [], f'SECURITY_EVENT_FEED tidak terbaca: {err}'
    events: list[dict] = []
    broken = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            broken += 1
            continue
        if isinstance(entry, dict) and entry.get('type'):
            events.append(entry)
    if broken:
        log.warning('sec_ops: %d baris feed tidak terbaca di %s', broken, target)
    return events, None


def _recent(events: list[dict], kind: str, now: float, window_s: float) -> list[dict]:
    return [event for event in events
            if str(event.get('type')) == kind
            and now - float(event.get('at') or 0) <= window_s]


def _chargeback_counts(con: sqlite3.Connection) -> dict[str, int]:
    """Chargebacks per account, from the table PaymentAgent writes."""
    rows = con.execute(
        "SELECT user_id, COUNT(*) AS n FROM payment_events WHERE status = 'chargeback' "
        "AND user_id IS NOT NULL AND user_id != '' GROUP BY user_id"
    ).fetchall()
    return {str(row['user_id']): int(row['n']) for row in rows}


def _latest_incident(con: sqlite3.Connection, rule: str, target: str) -> dict | None:
    row = con.execute(
        'SELECT * FROM security_incidents WHERE rule = ? AND target = ? '
        'ORDER BY created_at DESC LIMIT 1',
        (rule, target),
    ).fetchone()
    return dict(row) if row else None


def apply_rule(rule: str, target: str, action: str, reason: str, *,
               now: float | None = None, con: sqlite3.Connection | None = None,
               actor: str = 'SecOps') -> dict:
    """Record one action. Append-only, and the same rule on the same target is one row.

    Returns `{recorded, id, rule, target, action}`; `recorded: False` means this
    action was already taken inside `COOLDOWN_S`, which is what keeps a repeated
    threshold breach from writing a row per second.
    """
    at = _at(now)
    connection = _con(con)
    previous = _latest_incident(connection, rule, target)
    if previous and action != 'unban' and at - float(previous.get('created_at') or 0) < COOLDOWN_S:
        return {'recorded': False, 'id': previous['id'], 'rule': rule, 'target': target,
                'action': previous.get('action'),
                'reason': f'aksi yang sama sudah dicatat {COOLDOWN_S:.0f} dtk lalu'}

    ident = f'sc-{uuid.uuid4().hex[:10]}'
    connection.execute(
        'INSERT INTO security_incidents (id, rule, target, action, reason, actor, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (ident, rule[:60], target[:200], action[:40], reason[:300], actor[:40], at),
    )
    connection.commit()
    log.warning('sec_ops: %s %s (%s) - %s', action, target, rule, reason)
    return {'recorded': True, 'id': ident, 'rule': rule, 'target': target, 'action': action,
            'reason': reason, 'at': at}


def flag_account(user_id: str, reason: str, *, now: float | None = None,
                 con: sqlite3.Connection | None = None) -> dict:
    """What the chargeback handoff asks for: flag the account, keep the evidence."""
    return apply_rule('chargeback_count', str(user_id or '').strip(), 'flag_account', reason,
                      now=now, con=con)


def monitor(now: float | None = None, con: sqlite3.Connection | None = None,
            char: Any = None, events: list[dict] | None = None) -> dict:
    """One round: evaluate every rule, record the new breaches, draw nothing else.

    `char.update` is called only when at least one violation was recorded, so an
    idle round is one log line and zero office events.
    """
    at = _at(now)
    connection = _con(con)
    if events is None:
        loaded, missing = load_events()
    else:
        loaded, missing = events, None
    insufficient = [missing] if missing else []

    violations: list[dict] = []
    for spec in RULES:
        kind = spec['type']
        if kind is None:
            continue
        window = _recent(loaded, str(kind), at, float(spec['window_s']))
        counts: dict[str, int] = {}
        for event in window:
            target = str(event.get('ip') or event.get('user_id') or '').strip()
            if target:
                counts[target] = counts.get(target, 0) + 1
        for target, count in counts.items():
            if count < int(spec['threshold']):
                continue
            record = apply_rule(
                str(spec['rule']), target, str(spec['action']),
                f'{count} {kind} dalam {int(spec["window_s"])} dtk (ambang {spec["threshold"]})',
                now=at, con=connection,
            )
            if record.get('recorded'):
                violations.append(record)

    for user, count in _chargeback_counts(connection).items():
        if count < 2:
            continue
        record = flag_account(user, f'{count} chargeback diterima (ambang 2)', now=at, con=connection)
        if record.get('recorded'):
            violations.append(record)

    if char and violations:
        char.update(f'{len(violations)} pelanggaran, {len(violations)} aksi', tool='apply_rule')
    log.info('sec_ops: %d pelanggaran baru, feed=%s', len(violations),
             'ya' if missing is None else 'tidak')
    return {'violations': violations, 'blocked': len(violations),
            'source': 'feed' if missing is None else 'payment_events',
            'insufficient': insufficient}


def incidents(hours: float = 24.0, now: float | None = None,
              con: sqlite3.Connection | None = None, limit: int = 50) -> list[dict]:
    at = _at(now)
    rows = _con(con).execute(
        'SELECT * FROM security_incidents WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?',
        (at - float(hours) * 3600.0, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def is_banned(target: str, con: sqlite3.Connection | None = None) -> bool:
    """True when the newest row for `target` is a blocking action, not an `unban`."""
    row = _con(con).execute(
        'SELECT action FROM security_incidents WHERE target = ? ORDER BY created_at DESC LIMIT 1',
        (str(target or '').strip(),),
    ).fetchone()
    return bool(row) and str(row['action']) in BLOCKING_ACTIONS


def unban(target: str, *, now: float | None = None, con: sqlite3.Connection | None = None,
          actor: str = 'CEO') -> dict:
    """A person lifts a block. A new row, never a delete (SECURITY.md §10)."""
    clean = str(target or '').strip()
    if not clean:
        return {'action': 'unban', 'ok': False, 'reason': 'target kosong'}
    record = apply_rule('manual', clean, 'unban', 'unban manual', now=now, con=con, actor=actor)
    return {**record, 'action': 'unban', 'ok': bool(record.get('recorded') or record.get('id'))}


def summary(hours: float = 24.0, now: float | None = None,
            con: sqlite3.Connection | None = None) -> dict:
    """`/security`: what happened in the window, and whether the feed is there."""
    at = _at(now)
    rows = incidents(hours, now=at, con=con, limit=200)
    by_action: dict[str, int] = {}
    for row in rows:
        by_action[str(row.get('action'))] = by_action.get(str(row.get('action')), 0) + 1
    feed = feed_path()
    return {'hours': float(hours), 'incidents': len(rows), 'by_action': by_action,
            'latest': rows[:5], 'feed': str(feed) if feed else None,
            'feed_missing': None if feed else
            'SECURITY_EVENT_FEED kosong: rule login/devices/rate tidak berjalan',
            'chargebacks': _chargeback_counts(_con(con))}


def flag_account_node(payload: object, now: float | None = None) -> dict:
    """The SecOps node the Orchestrator reaches through the chargeback handoff."""
    data = payload if isinstance(payload, dict) else {}
    user = str(data.get('user_id') or '').strip()
    if not user:
        return {'error': 'user_id kosong', 'handoff_key': data.get('handoff_key')}
    order = str(data.get('order_id') or '').strip()
    reason = str(data.get('reason') or '').strip()
    detail = f'chargeback order {order}' + (f': {reason}' if reason else '')
    return flag_account(user, detail, now=now)
