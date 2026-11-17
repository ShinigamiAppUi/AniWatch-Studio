"""payments.py - the Midtrans notification door (W4).

Three things, in the order they must happen:

1. `signature()` - `sha512(order_id + status_code + gross_amount + SERVER_KEY)`,
   explicit `utf-8`, `.get('', ...)` for every field, so a missing field is a
   wrong signature (403) instead of a `KeyError` (500). SECURITY.md §5 lists all
   three of those mistakes; none may come back.
2. `verify()` - constant-time compare, never `==`.
3. `record()` - one row per notification in `payment_events`, `INSERT OR IGNORE`
   on a deterministic id, so a notification Midtrans sends twice does not refund
   twice (SECURITY.md §5, DB-SCHEMA.md §7).

No status is acted on here: a refund or a chargeback needs an agent and an
approval card, and those are W9. This file makes the notification trustworthy
and idempotent first.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import time

log = logging.getLogger(__name__)

#: Midtrans' `transaction_status` -> the column value DB-SCHEMA.md §7 defines
STATUS_MAP = {
    'settlement': 'processed',
    'capture': 'processed',
    'pending': 'pending',
    'deny': 'failed',
    'cancel': 'failed',
    'expire': 'failed',
    'failure': 'failed',
    'refund': 'refunded',
    'partial_refund': 'refunded',
    'chargeback': 'chargeback',
    'partial_chargeback': 'chargeback',
}


class BadSignature(ValueError):
    """The header does not match the payload; the route turns this into a 403."""


def server_key() -> str:
    """`MIDTRANS_SERVER_KEY` as it is now."""
    return str(os.environ.get('MIDTRANS_SERVER_KEY') or '').strip()


def signature(payload: dict, key: str) -> str:
    """sha512 of `order_id + status_code + gross_amount + key`, hex."""
    raw = (
        f"{payload.get('order_id', '')}"
        f"{payload.get('status_code', '')}"
        f"{payload.get('gross_amount', '')}"
        f"{key}"
    )
    return hashlib.sha512(raw.encode('utf-8')).hexdigest()


def verify(payload: dict, header: str | None, key: str | None = None) -> bool:
    """True when `header` is this payload's signature. Never raises on a bad body."""
    expected = signature(payload if isinstance(payload, dict) else {}, key if key is not None else server_key())
    return secrets.compare_digest(str(header or ''), expected)


def event_id(payload: dict) -> str:
    """Deterministic id: the same notification twice is one row."""
    parts = (
        str(payload.get('order_id', '')),
        str(payload.get('status_code', '')),
        str(payload.get('transaction_status', '')),
    )
    return ':'.join(part.strip() for part in parts)


def status_of(payload: dict) -> str:
    """`payment_events.status` for a notification; unknown statuses stay `pending`."""
    return STATUS_MAP.get(str(payload.get('transaction_status', '')).strip().lower(), 'pending')


def amount_of(payload: dict) -> int | None:
    """`gross_amount` as whole rupiah, or None when it is not a number."""
    try:
        return int(float(str(payload.get('gross_amount', '')).replace(',', '')))
    except (TypeError, ValueError):
        return None


def record(con: sqlite3.Connection, payload: dict, now: float | None = None) -> bool:
    """Insert the notification once. Returns False when it was already there.

    The row is written before anything else looks at the payment: a retried
    notification finds the id taken and changes nothing.
    """
    ident = event_id(payload)
    if not ident or not payload.get('order_id'):
        return False
    cur = con.execute(
        'INSERT OR IGNORE INTO payment_events '
        '(id, order_id, user_id, event_type, amount_idr, payment_method, status, processed_at, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            ident[:200],
            str(payload.get('order_id'))[:200],
            str(payload.get('customer_id') or payload.get('user_id') or 'unknown')[:200],
            str(payload.get('transaction_status') or 'notification')[:60],
            amount_of(payload),
            str(payload.get('payment_type') or '')[:60] or None,
            status_of(payload),
            time.time() if status_of(payload) != 'pending' else None,
            time.time() if now is None else now,
        ),
    )
    con.commit()
    return cur.rowcount > 0
