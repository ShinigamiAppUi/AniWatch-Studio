"""finance.py - PaymentAgent and RevenueTracker: money in, and the trail it leaves.

One module for two agents because they answer one question between them - what
happened to an order. PaymentAgent acts (grace, downgrade, refund, chargeback);
RevenueTracker records it (`payment_events`) and reports it (a snapshot file).

Three rules this module keeps:

- **A plan change needs a payment event.** `subscription_status` is written only
  by `handle_success()` and `handle_failure()`, exactly as DB-SCHEMA.md §7 says,
  so `retention.py`'s lapsed segment has a real source instead of a guess.
- **A refund is a decision, not a side effect.** It has a 7-day window, an
  approval card (`REFUND_OPTIONS`, timeout 24 hours - a money decision does not
  inherit the 300 s default, AGENTS.md §4.6) and `decide_refund()` as the single
  writer out of `pending`.
- **Nothing is revoked that cannot be named.** `premium_items` has no owner
  column, so a chargeback revokes an item only when the notification carries
  `item_id`, and the result says so when it does not.

Handoffs follow AGENT-HANDOFFS.md §3 exactly: a settled payment leaves one to
RevenueTracker (`payment_settled`), a chargeback one to SecOps (`chargeback`).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from hermes_bridge import handoff

from . import config, store

log = logging.getLogger(__name__)

#: A failed renewal gets this long to be paid before the plan drops (AGENTS §4.6)
GRACE_DAYS = 3
GRACE_S = GRACE_DAYS * 86400.0

#: A refund is only considered inside this window after the settled payment
REFUND_DAYS = 7
REFUND_WINDOW_S = REFUND_DAYS * 86400.0

#: The card's button labels are what comes back; a money decision gets 24 hours
REFUND_OPTIONS = ('Approve', 'Tolak', 'Minta Info')
REFUND_TIMEOUT_S = 86400.0

#: retry_count below this is a grace period; at this value the plan is downgraded
MAX_RETRY = 2

#: Below this many paid orders a refund rate is not a rate, it is noise
MIN_SAMPLE = 5

#: Above this share of refunds, RevenueTracker reports an anomaly (rule stated)
REFUND_ALERT_RATE = 0.2

#: Two chargebacks on one account is the threshold AGENTS.md §4.6 documents
CHARGEBACK_ALERT = 2


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _at(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _con(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return con if con is not None else store.connect()


def _text(value: object, limit: int = 200) -> str:
    return ' '.join(str(value or '').split())[:limit]


def _order(payload: dict) -> str:
    return _text(payload.get('order_id'), 120)


def _user(payload: dict) -> str:
    return _text(payload.get('user_id') or payload.get('customer_id'), 200)


def _plan(payload: dict, fallback: str = 'premium') -> str:
    plan = _text(payload.get('plan') or fallback, 40).lower()
    return plan if plan in ('free', 'premium', 'premium_plus') else fallback


def rupiah(value: object) -> str:
    """`149000` -> `Rp149.000`, for a chat line or a log message."""
    try:
        return f'Rp{int(value):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return 'Rp0'


def _metric(delta: dict) -> None:
    """Send one counter; a metrics failure never fails the money work."""
    from hermes_bridge import bridge

    try:
        bridge.update_biz_metrics(delta)
    except Exception as err:  # noqa: BLE001 - the row is the record, not the panel
        log.warning('finance: metric %s tidak terkirim: %s', delta, err)


def _notify(user: str, subject: str, body: str) -> dict:
    """Mail a subscriber, only when the id really is an address.

    `subscription_status` has no email column, so a user id that is not an
    address is reported as skipped instead of guessed (same rule as
    `retention.py`).
    """
    if '@' not in user:
        return {'sent': False, 'reason': 'user_id bukan alamat email'}
    from . import mailer

    result = mailer.send(user, subject, body)
    return {'sent': bool(result.get('sent')), 'reason': result.get('error')}


# ---------------------------------------------------------------------------
# payment_events / subscription_status (DB-SCHEMA.md §7)
# ---------------------------------------------------------------------------

def settled_payment(con: sqlite3.Connection, order_id: str) -> dict | None:
    """The successful notification for an order, newest first."""
    row = con.execute(
        "SELECT * FROM payment_events WHERE order_id = ? AND status = 'processed' "
        'ORDER BY created_at DESC LIMIT 1',
        (order_id,),
    ).fetchone()
    return dict(row) if row else None


def refund_row(con: sqlite3.Connection, order_id: str) -> dict | None:
    """The refund request row for an order, if one was recorded."""
    row = con.execute(
        "SELECT * FROM payment_events WHERE order_id = ? AND event_type = 'refund_request' "
        'ORDER BY created_at DESC LIMIT 1',
        (order_id,),
    ).fetchone()
    return dict(row) if row else None


def subscription(con: sqlite3.Connection, user_id: str) -> dict | None:
    row = con.execute('SELECT * FROM subscription_status WHERE user_id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def _save_subscription(con: sqlite3.Connection, user_id: str, *, plan: str,
                       expires_at: float | None, retry_count: int,
                       grace_until: float | None, now: float) -> dict:
    con.execute(
        'INSERT INTO subscription_status (user_id, plan, expires_at, retry_count, grace_until, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(user_id) DO UPDATE SET plan = excluded.plan, expires_at = excluded.expires_at, '
        'retry_count = excluded.retry_count, grace_until = excluded.grace_until, '
        'updated_at = excluded.updated_at',
        (user_id, plan, expires_at, retry_count, grace_until, now),
    )
    con.commit()
    return subscription(con, user_id) or {}


# ---------------------------------------------------------------------------
# PaymentAgent - the five tools from AGENTS.md §4.6
# ---------------------------------------------------------------------------

def handle_success(payload: dict, *, now: float | None = None, con: sqlite3.Connection | None = None,
                   char: Any = None) -> dict:
    """`payment.success`: the subscription is paid, then RevenueTracker hears of it.

    `expires_at` is taken from the notification when it carries one and kept
    otherwise: this fork has no billing calendar and inventing a renewal date
    would be a number nobody can check.
    """
    at = _at(now)
    connection = _con(con)
    order, user = _order(payload), _user(payload)
    if not order or not user:
        return {'action': 'ignored', 'reason': 'order_id/user_id kosong'}

    before = subscription(connection, user) or {}
    plan = _plan(payload, str(before.get('plan') or 'premium'))
    expires = payload.get('expires_at')
    try:
        expires_at = float(expires) if expires is not None else before.get('expires_at')
    except (TypeError, ValueError):
        expires_at = before.get('expires_at')
    row = _save_subscription(connection, user, plan=plan, expires_at=expires_at,
                             retry_count=0, grace_until=None, now=at)
    if char:
        char.update(f'{plan} aktif untuk {user[:40]}', tool='handle_success')

    amount = payload.get('amount')
    if amount is None:
        from webhook_server.payments import amount_of

        amount = amount_of(payload)
    key = None
    reason = None
    if amount is None:
        reason = 'gross_amount tidak ada, jadi tidak ada handoff payment_settled'
    else:
        try:
            key = handoff.hand_off(
                'PaymentAgent', 'RevenueTracker', 'payment_settled',
                f'order:{order}',
                {'order_id': order, 'amount': int(amount),
                 'method': _text(payload.get('payment_type'), 60)},
                now=at,
            )
        except (ValueError, handoff.UnknownHandoff) as err:
            reason = f'handoff tidak ditulis: {err}'
            log.warning('finance: %s', reason)
    log.info('finance: %s sukses untuk %s (%s)', order, user, plan)
    return {'action': 'settled', 'order_id': order, 'user_id': user, 'plan': plan,
            'subscription': row, 'metric': None, 'handoff': key, 'handoff_reason': reason}


def handle_failure(payload: dict, *, now: float | None = None, con: sqlite3.Connection | None = None,
                   char: Any = None, transport=None) -> dict:
    """`payment.failed` / `subscription.renewal_failed`: grace first, then `free`.

    retry_count below MAX_RETRY sets `grace_until = now + 3 days` and mails the
    subscriber an alternative-payment hint; at MAX_RETRY the plan drops to
    `free` and `subscriptions_lost` counts it. Nothing is deleted - the row keeps
    `retry_count` so a person can see why the plan changed.
    """
    at = _at(now)
    connection = _con(con)
    order, user = _order(payload), _user(payload)
    if not user:
        return {'action': 'ignored', 'reason': 'user_id kosong'}

    before = subscription(connection, user) or {}
    retries = int(before.get('retry_count') or 0) + 1
    if retries < MAX_RETRY:
        in_grace = _save_subscription(
            connection, user, plan=str(before.get('plan') or _plan(payload)),
            expires_at=before.get('expires_at'), retry_count=retries,
            grace_until=at + GRACE_S, now=at,
        )
        notice = (_notify(
            user,
            'Pembayaran langganan belum masuk',
            'Halo,\n\nPembayaran langganan AniWatch Anda belum masuk. Akun Anda masih bisa '
            f'dipakai sampai {GRACE_DAYS} hari ke depan.\n'
            'Silakan perbarui metode pembayaran (kartu lain, transfer bank, atau e-wallet) '
            'di halaman langganan agar tidak turun ke paket gratis.\n\nSalam,\nAniWatch',
        ) if transport is None else _notify_with(user, transport))
        if char:
            char.update(f'grace {GRACE_DAYS} hari untuk {user[:40]} (percobaan {retries})',
                        tool='retry_subscription')
        log.info('finance: %s gagal, grace sampai +%d hari (percobaan %d)', order or user,
                 GRACE_DAYS, retries)
        return {'action': 'grace', 'order_id': order, 'user_id': user, 'retry_count': retries,
                'grace_until': at + GRACE_S, 'plan': in_grace.get('plan'),
                'notified': notice.get('sent'), 'notify_reason': notice.get('reason')}

    downgraded = _save_subscription(
        connection, user, plan='free', expires_at=None, retry_count=retries,
        grace_until=None, now=at,
    )
    _metric({'subscriptions_lost': 1})
    if char:
        char.update(f'downgrade {user[:40]} ke free setelah {retries} percobaan',
                    tool='handle_failure')
    log.info('finance: %s turun ke free setelah %d percobaan', user, retries)
    return {'action': 'downgrade', 'order_id': order, 'user_id': user, 'retry_count': retries,
            'plan': downgraded.get('plan'), 'metric': {'subscriptions_lost': 1}}


def _notify_with(user: str, transport) -> dict:
    """Same letter as `_notify`, through a test transport (selfcheck uses it)."""
    from . import mailer

    result = mailer.send(
        user,
        'Pembayaran langganan belum masuk',
        'Halo,\n\nPembayaran langganan AniWatch Anda belum masuk. Akun Anda masih bisa dipakai '
        f'sampai {GRACE_DAYS} hari ke depan. Perbarui metode pembayaran Anda.\n\nSalam,\nAniWatch',
        transport=transport,
    )
    return {'sent': bool(result.get('sent')), 'reason': result.get('error')}


def refund_request(payload: dict, *, now: float | None = None,
                   con: sqlite3.Connection | None = None, char: Any = None) -> dict:
    """`refund.requested`: inside the window, record one `pending` row for the queue.

    The row is the request, not the refund: `decide_refund()` moves it, and only
    a person's Approve sends `refunds_processed`. Refusing here is a value, not
    an exception - the caller gets `reason` and nothing is written.
    """
    at = _at(now)
    connection = _con(con)
    order, user = _order(payload), _user(payload)
    if not order:
        return {'action': 'refused', 'reason': 'order_id kosong'}

    paid = settled_payment(connection, order)
    if paid is None:
        return {'action': 'refused', 'order_id': order,
                'reason': f'order {order} tidak punya pembayaran sukses'}
    age = at - float(paid.get('created_at') or 0)
    if age > REFUND_WINDOW_S:
        return {'action': 'refused', 'order_id': order,
                'reason': f'lewat jendela refund {REFUND_DAYS} hari ({age / 86400:.1f} hari)'}

    existing = refund_row(connection, order)
    if existing and existing.get('status') == 'pending':
        return {'action': 'refund_requested', 'order_id': order, 'id': existing['id'],
                'amount_idr': existing.get('amount_idr'), 'duplicate': True}
    if existing and existing.get('status') == 'refunded':
        return {'action': 'refused', 'order_id': order,
                'reason': 'refund untuk order ini sudah disetujui'}

    ident = f'refund-{order}'[:200]
    connection.execute(
        'INSERT OR REPLACE INTO payment_events '
        '(id, order_id, user_id, event_type, amount_idr, payment_method, status, processed_at, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (ident, order, user or paid.get('user_id'), 'refund_request', paid.get('amount_idr'),
         paid.get('payment_method'), 'pending', None, at),
    )
    connection.commit()
    if char:
        char.update(f'refund {order} menunggu approval', tool='process_refund')
    log.info('finance: refund %s diminta (%s)', order, rupiah(paid.get('amount_idr')))
    return {'action': 'refund_requested', 'order_id': order, 'id': ident,
            'amount_idr': paid.get('amount_idr'), 'window_days': REFUND_DAYS}


def decide_refund(order_id: str, decision: str, *, now: float | None = None,
                  con: sqlite3.Connection | None = None) -> dict:
    """The single writer out of a `pending` refund.

    Approve -> `refunded` + `refunds_processed`; Tolak -> `failed` with the
    reason on the row; Minta Info and a timeout change nothing, so the request
    stays in the queue and can still be answered later (same rule as premium's
    approval: a timeout is not a decision).
    """
    at = _at(now)
    connection = _con(con)
    row = refund_row(connection, order_id)
    if row is None:
        return {'action': 'missing', 'order_id': order_id,
                'reason': f'tidak ada permintaan refund untuk {order_id}'}
    if row.get('status') != 'pending':
        return {'action': 'unchanged', 'order_id': order_id, 'status': row.get('status'),
                'decision': None, 'reason': f'status {row.get("status")} bukan pending'}

    label = str(decision or '').strip()
    if label == 'Approve':
        connection.execute("UPDATE payment_events SET status = 'refunded', processed_at = ? WHERE id = ?",
                           (at, row['id']))
        connection.commit()
        _metric({'refunds_processed': 1})
        log.info('finance: refund %s disetujui (%s)', order_id, rupiah(row.get('amount_idr')))
        return {'action': 'refunded', 'order_id': order_id, 'status': 'refunded',
                'decision': label, 'amount_idr': row.get('amount_idr'),
                'metric': {'refunds_processed': 1}}
    if label == 'Tolak':
        connection.execute("UPDATE payment_events SET status = 'failed', processed_at = ? WHERE id = ?",
                           (at, row['id']))
        connection.commit()
        log.info('finance: refund %s ditolak', order_id)
        return {'action': 'rejected', 'order_id': order_id, 'status': 'failed', 'decision': label}
    return {'action': 'unchanged', 'order_id': order_id, 'status': 'pending', 'decision': label,
            'reason': f'keputusan {label or "kosong"} tidak mengubah status'}


def request_refund_approval(order_id: str, char: Any = None, timeout: float = REFUND_TIMEOUT_S,
                            *, now: float | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Raise the refund card and carry out the answer.

    Blocks until a person answers, so the caller must run it in a worker thread
    (`webhook_server/main.py`) or pass a test character - never inline in a
    request. Three options: Approve / Tolak / Minta Info.
    """
    connection = _con(con)
    row = refund_row(connection, order_id)
    if row is None:
        return {'action': 'missing', 'order_id': order_id,
                'reason': f'tidak ada permintaan refund untuk {order_id}'}
    if row.get('status') != 'pending':
        return {'action': 'unchanged', 'order_id': order_id, 'status': row.get('status')}
    message = (f'Refund order {order_id} sebesar {rupiah(row.get("amount_idr"))} '
               f'(user {row.get("user_id")}) diminta. Setujui?')

    if char is not None:
        decision = char.ask(message, list(REFUND_OPTIONS), timeout=timeout)
    else:
        from .base import Agent

        with Agent('PaymentAgent', f'Refund {order_id}', name='Payment Agent') as card:
            decision = card.ask(message, list(REFUND_OPTIONS), timeout=timeout)
    log.info('finance: refund %s -> %s', order_id, decision)
    return {**decide_refund(order_id, decision, now=now, con=connection), 'approval': decision}


def flag_chargeback(payload: dict, *, now: float | None = None,
                    con: sqlite3.Connection | None = None, char: Any = None) -> dict:
    """`chargeback.received`: mark it, revoke a named item, hand the account to SecOps.

    The revocation is honest about its limit: only an `item_id` in the
    notification can be revoked, because `premium_items` does not record who
    bought what.
    """
    at = _at(now)
    connection = _con(con)
    order, user = _order(payload), _user(payload)
    if not order:
        return {'action': 'ignored', 'reason': 'order_id kosong'}

    from webhook_server import payments as payment_events

    # `record()` is `INSERT OR IGNORE` on a deterministic id, so a notification
    # Midtrans sends twice does not produce a second chargeback row
    if not payment_events.record(connection, {'order_id': order, 'customer_id': user,
                                              'transaction_status': 'chargeback',
                                              'gross_amount': payload.get('gross_amount') or 0,
                                              'status_code': payload.get('status_code') or '200',
                                              'payment_type': payload.get('payment_type')},
                                 now=at):
        it_was_there = True
    else:
        it_was_there = False

    revoked: dict | None = None
    item_id = _text(payload.get('item_id') or payload.get('premium_item_id'), 80)
    if item_id:
        from . import premium

        revoked = premium.revoke_item(item_id, f'chargeback {order}', now=at)
    _metric({'chargebacks': 1})

    key = None
    reason = None
    if not user:
        reason = 'user_id kosong, jadi tidak ada handoff ke SecOps'
    else:
        try:
            key = handoff.hand_off(
                'PaymentAgent', 'SecOps', 'chargeback', f'order:{order}',
                {'order_id': order, 'user_id': user,
                 'reason': _text(payload.get('reason') or 'chargeback dari provider', 120)},
                now=at,
            )
        except (ValueError, handoff.UnknownHandoff) as err:
            reason = f'handoff tidak ditulis: {err}'
            log.warning('finance: %s', reason)
    if char:
        char.update(f'chargeback {order} ditandai' + (f', item {item_id} dicabut' if revoked else ''),
                    tool='flag_chargeback')
    log.info('finance: chargeback %s (user %s, baru=%s)', order, user or '-', not it_was_there)
    return {'action': 'chargeback', 'order_id': order, 'user_id': user,
            'revoked': revoked, 'revoke_reason': None if revoked else
            'payload tanpa item_id (premium_items tidak menyimpan pemilik)',
            'handoff': key, 'handoff_reason': reason, 'metric': {'chargebacks': 1}}


def refund_completed(payload: dict, *, now: float | None = None,
                     con: sqlite3.Connection | None = None, char: Any = None) -> dict:
    """A provider `refund` notification: close the request if we had one.

    It does **not** count `refunds_processed`: that metric is our approvals, and
    a refund the provider performed on its own is a different fact. When no
    request exists, the notification is still recorded (the audit trail keeps
    it) and the result says no approval was involved.
    """
    at = _at(now)
    connection = _con(con)
    order = _order(payload)
    if not order:
        return {'action': 'ignored', 'reason': 'order_id kosong'}
    row = refund_row(connection, order)
    if row is None:
        if char:
            char.update(f'refund {order} dari provider tanpa permintaan', tool='handle_success')
        return {'action': 'refund_from_provider', 'order_id': order,
                'reason': 'tidak ada permintaan refund yang disetujui fork ini'}
    if row.get('status') == 'refunded':
        return {'action': 'refunded', 'order_id': order, 'duplicate': True}
    connection.execute("UPDATE payment_events SET status = 'refunded', processed_at = ? WHERE id = ?",
                       (at, row['id']))
    connection.commit()
    return {'action': 'refunded', 'order_id': order, 'approved': row.get('status') == 'pending',
            'decision': 'provider'}


def handle_payment_webhook(payload: dict, *, now: float | None = None,
                           con: sqlite3.Connection | None = None, char: Any = None) -> dict:
    """One verified notification -> the tool that belongs to it.

    `refund_request` is not a Midtrans status: it is how a refund is *asked for*
    through the same verified door (`POST /webhook/payment`), so the request path
    is authenticated exactly like the notifications around it. Everything else
    maps through `payments.status_of()`.
    """
    from webhook_server import payments as payment_events

    data = payload if isinstance(payload, dict) else {}
    event = str(data.get('transaction_status') or '').strip().lower()
    if event == 'refund_request':
        return refund_request(data, now=now, con=con, char=char)

    status = payment_events.status_of(data)
    if status == 'processed':
        return handle_success(data, now=now, con=con, char=char)
    if status == 'failed':
        return handle_failure(data, now=now, con=con, char=char)
    if status == 'refunded':
        return refund_completed(data, now=now, con=con, char=char)
    if status == 'chargeback':
        return flag_chargeback(data, now=now, con=con, char=char)
    return {'action': 'ignored', 'order_id': _order(data),
            'reason': f'status {status} tidak mengubah apa pun'}


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point `webhook_server/triggers.py` calls for `chargeback_received`.

    The trigger carries a chargeback, so that is the default; a payload that
    names another notification status is still routed by it, so one handler
    serves both doors honestly.
    """
    data = payload if isinstance(payload, dict) else {}
    if not str(data.get('transaction_status') or '').strip():
        data = {**data, 'transaction_status': 'chargeback'}
    return handle_payment_webhook(data, char=char)


# ---------------------------------------------------------------------------
# RevenueTracker - the snapshot, the anomaly rule, the numbers /revenue shows
# ---------------------------------------------------------------------------

def _latest_per_order(rows: list[dict]) -> dict[str, dict]:
    """One row per order: the newest notification decides that order's status."""
    latest: dict[str, dict] = {}
    for row in rows:
        order = str(row.get('order_id') or '')
        if not order:
            continue
        if order not in latest or float(row.get('created_at') or 0) >= float(latest[order].get('created_at') or 0):
            latest[order] = row
    return latest


def snapshot(now: float | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Revenue over the last day and week, from `payment_events` only.

    Orders, not notifications: an order counts once, with the status of its
    newest row, so a chargeback does not also count as revenue. A rate below
    `MIN_SAMPLE` paid orders is `None`, because a percentage of three payments is
    noise, not a signal.
    """
    at = _at(now)
    connection = _con(con)
    rows = [dict(row) for row in connection.execute(
        'SELECT order_id, user_id, amount_idr, event_type, status, created_at FROM payment_events'
    ).fetchall()]
    latest = _latest_per_order([row for row in rows if row.get('event_type') != 'refund_request'])

    def _total(since: float) -> dict:
        paid = [row for row in latest.values()
                if row.get('status') == 'processed' and float(row.get('created_at') or 0) >= since]
        return {'orders': len(paid), 'idr': sum(int(row.get('amount_idr') or 0) for row in paid)}

    week_start = at - 7 * 86400.0
    week_orders = latest.values()
    refunded = [row for row in week_orders
                if row.get('status') == 'refunded' and float(row.get('created_at') or 0) >= week_start]
    charged = [row for row in week_orders
               if row.get('status') == 'chargeback' and float(row.get('created_at') or 0) >= week_start]
    sample = sum(1 for row in week_orders
                 if row.get('status') in ('processed', 'refunded', 'chargeback')
                 and float(row.get('created_at') or 0) >= week_start)
    refund_rate = round(len(refunded) / sample, 3) if sample >= MIN_SAMPLE else None

    result = {
        'generated_at': at,
        'source': 'payment_events',
        'today': _total(at - 86400.0),
        'week': _total(week_start),
        'refunds': {'pending': len(refund_queue(connection)), 'week': len(refunded)},
        'chargebacks': {'week': len(charged)},
        'sample': sample,
        'refund_rate': refund_rate,
    }
    result['anomalies'] = anomalies(result)
    return result


def anomalies(snap: dict) -> list[dict]:
    """The two rules RevenueTracker reports, both read off the snapshot."""
    found: list[dict] = []
    rate = snap.get('refund_rate')
    if rate is not None and rate > REFUND_ALERT_RATE:
        found.append({'rule': 'refund_rate', 'value': rate, 'threshold': REFUND_ALERT_RATE,
                      'detail': f'{rate:.0%} dari {snap.get("sample")} order minggu ini direfund'})
    chargebacks = int((snap.get('chargebacks') or {}).get('week') or 0)
    if chargebacks >= CHARGEBACK_ALERT:
        found.append({'rule': 'chargebacks', 'value': chargebacks, 'threshold': CHARGEBACK_ALERT,
                      'detail': f'{chargebacks} chargeback dalam 7 hari'})
    return found


def snapshot_path(at: float) -> Path:
    """`media/published/revenue/YYYY-MM-DD.json`."""
    return (config.media_root() / 'published' / 'revenue'
            / f'{time.strftime("%Y-%m-%d", time.localtime(at))}.json')


def report(now: float | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Write the snapshot file and return it with its path (`/revenue` uses this)."""
    at = _at(now)
    snap = snapshot(at, con=con)
    path: Path = snapshot_path(at)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    log.info('finance: snapshot revenue %s (%s, %d order hari ini)',
             path.name, rupiah(snap['today']['idr']), snap['today']['orders'])
    return {**snap, 'path': str(path)}


def record_transaction(payload: dict, now: float | None = None) -> dict:
    """RevenueTracker's tool `record_transaction`, as the Orchestrator node.

    The handoff already carries the payment; what this adds is the snapshot a
    person can read, so "recorded" means a file exists with these numbers.
    """
    data = payload if isinstance(payload, dict) else {}
    written = report(now=now)
    return {'action': 'recorded', 'order_id': _text(data.get('order_id'), 120),
            'amount': data.get('amount'), 'today_idr': written['today']['idr'],
            'week_idr': written['week']['idr'], 'path': written['path'],
            'anomalies': written['anomalies']}


def refund_queue(con: sqlite3.Connection | None = None, limit: int = 20) -> list[dict]:
    """Refund requests still waiting for a person."""
    rows = _con(con).execute(
        "SELECT id, order_id, user_id, amount_idr, created_at FROM payment_events "
        "WHERE event_type = 'refund_request' AND status = 'pending' "
        'ORDER BY created_at ASC LIMIT ?',
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def recent_chargebacks(con: sqlite3.Connection | None = None, limit: int = 20) -> list[dict]:
    rows = _con(con).execute(
        "SELECT id, order_id, user_id, amount_idr, created_at FROM payment_events "
        "WHERE status = 'chargeback' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def payment_summary(now: float | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Today's notifications grouped by status - events, not orders, and it says so."""
    at = _at(now)
    rows = _con(con).execute(
        'SELECT status, COUNT(*) AS n FROM payment_events WHERE created_at >= ? GROUP BY status',
        (at - 86400.0,),
    ).fetchall()
    counts = {str(row['status'] or 'pending'): int(row['n']) for row in rows}
    return {'window_s': 86400.0, 'by_status': counts, 'total': sum(counts.values())}


def subscription_summary(now: float | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Active plans, rows in grace, and rows already past `expires_at`."""
    at = _at(now)
    rows = [dict(row) for row in _con(con).execute(
        'SELECT user_id, plan, expires_at, grace_until, retry_count FROM subscription_status'
    ).fetchall()]
    plans: dict[str, int] = {}
    for row in rows:
        plans[str(row.get('plan') or 'free')] = plans.get(str(row.get('plan') or 'free'), 0) + 1
    grace = [row for row in rows if row.get('grace_until')]
    expired = [row for row in rows
               if row.get('expires_at') and float(row['expires_at']) <= at]
    return {'total': len(rows), 'plans': plans, 'in_grace': len(grace), 'expired': len(expired)}


def revenue_summary(now: float | None = None, con: sqlite3.Connection | None = None) -> dict:
    """`/revenue`: the snapshot file, written, plus what is still waiting."""
    written = report(now=now, con=con)
    return {**written, 'refund_queue': len(refund_queue(con)), 'path': written['path']}
