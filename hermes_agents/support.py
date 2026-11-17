"""support.py - Support: one ticket from inbox to an answer or an escalation.

The flow AGENTS.md §4.1 defines, in order:

    tiket masuk -> triage (kategori + prioritas) -> kb.search(subject, top_k=3)
       |- skor >= KB_MIN_SCORE -> draft_reply -> send_reply
       +- skor <  KB_MIN_SCORE -> escalate

Two rules are load-bearing here:

1. `check_sla_breaches` raises **one** card for the whole batch of late tickets,
   with three options, and calls `wait_for_approval` exactly once (fix Rev 3 #1).
   One card per ticket would bury the office in hands and wake the same agent
   twice.
2. `send_reply` really sends, through `hermes_agents.mailer` (SMTP). It returns
   `{sent, error}`, and the ticket's state follows the outcome: `pending` when
   the mail left, still `open` when it did not, so the next SLA run bills an
   unanswered ticket instead of a failed one looking answered. Every attempt is
   in the outbox either way.

Headless: every office call goes through the `char` object the caller passes
(`Agent` from base.py, or a thin wrapper in triggers.py). Without one nothing is
drawn and `ask` never blocks - the work still runs.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

#: AGENTS.md §4.1: `received_at + 3600` (1 jam)
SLA_SECONDS = 3600.0

#: The third button's effect, SCHEDULER.md §2 `sla_check`
EXTEND_SECONDS = 1800.0

#: The three options, in the order the card shows them
SLA_OPTIONS = ('Handle sekarang', 'Extend SLA +30 menit', 'Close as resolved')

MAX_BODY = 4000
MAX_REPLY = 2000

#: Triage words. Order matters: the first list that matches wins.
_URGENT = ('mendesak', 'urgent', 'tidak bisa', 'gagal total', 'kehilangan akses', 'chargeback', 'refund')
_HIGH = ('error', '404', 'buffering', 'subtitle', 'crash', 'premium', 'pembayaran', 'tidak muncul')
_LOW = ('pertanyaan', 'saran', 'fitur', 'kapan')


def priority_of(subject: str, body: str = '') -> str:
    """`urgent` / `high` / `low` / `normal` from the words in the ticket."""
    text = f'{subject} {body}'.lower()
    if any(word in text for word in _URGENT):
        return 'urgent'
    if any(word in text for word in _HIGH):
        return 'high'
    if any(word in text for word in _LOW):
        return 'low'
    return 'normal'


def new_ticket_id() -> str:
    """`tk-1a2b3c4d5e`: short enough for a chat line, unique enough to merge on."""
    return f'tk-{uuid.uuid4().hex[:10]}'


def _text(value: object, limit: int = MAX_BODY) -> str:
    """One line of text from whatever the trigger carried."""
    if isinstance(value, dict):
        for key in ('subject', 'title', 'description', 'message', 'body'):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return ' '.join(found.split())[:limit]
        return ''
    return ' '.join(str(value or '').split())[:limit]


def _report(delta: dict) -> None:
    """Send counters/gauges to the office; a headless run sends nothing."""
    if not os.environ.get('OFFICE_TOKEN', '').strip():
        return
    try:
        from hermes_bridge import bridge

        bridge.update_biz_metrics(delta)
    except Exception as err:  # noqa: BLE001 - metrics must never fail a ticket
        log.debug('support: metrics tidak terkirim: %s', err)


class SupportAgent:
    """Support's tools, one ticket at a time."""

    def __init__(self, kb: Any = None, con: sqlite3.Connection | None = None) -> None:
        self._kb = kb
        self._con = con
        self._own = con is None

    # -- dependencies -------------------------------------------------------

    def kb(self):
        if self._kb is None:
            from .kb import default_kb

            self._kb = default_kb()
        return self._kb

    def con(self) -> sqlite3.Connection:
        if self._con is None:
            from . import store

            self._con = store.connect()
        return self._con

    def close(self) -> None:
        if self._own and self._con is not None:
            self._con.close()
            self._con = None

    # -- the tools (AGENTS.md §4.1) -----------------------------------------

    def triage_ticket(self, subject: str, body: str = '', user_id: str = 'unknown',
                      channel: str = 'email', *, ticket: str | None = None,
                      now: float | None = None) -> dict:
        """Write the ticket and decide its priority and SLA deadline."""
        at = time.time() if now is None else float(now)
        tid = ticket or new_ticket_id()
        subject = _text(subject, 200) or '(tanpa subjek)'
        body = _text(body)
        priority = priority_of(subject, body)
        con = self.con()
        con.execute(
            'INSERT INTO tickets (id, user_id, subject, body, channel, priority, status, '
            'received_at, sla_deadline, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (tid, _text(user_id, 100) or 'unknown', subject, body, _text(channel, 20) or 'email',
             priority, 'open', at, at + SLA_SECONDS, at),
        )
        con.commit()
        self._remember(tid, {'subject': subject, 'priority': priority, 'channel': channel, 'triaged_at': at})
        log.info('support: tiket %s %s/%s', tid, priority, channel)
        return {'id': tid, 'subject': subject, 'priority': priority, 'status': 'open',
                'sla_deadline': at + SLA_SECONDS, 'channel': channel}

    def search_kb(self, subject: str, body: str = '', top_k: int = 3) -> list[dict]:
        """The best FAQ articles for this ticket, with their bm25 score."""
        return self.kb().search(f'{subject} {body}'.strip(), top_k=top_k)

    def draft_reply(self, ticket: dict, articles: list[dict]) -> str:
        """A reply built from the best article: its title, then its answer."""
        if not articles:
            return ''
        best = articles[0]
        body = ' '.join(str(best.get('body') or '').split())
        if len(body) > 600:
            cut = body.rfind('. ', 0, 600)
            body = body[:cut + 1] if cut > 0 else body[:600].rstrip() + '…'
        return (
            f'Halo, terima kasih sudah menghubungi AniWatch.\n\n'
            f'{body}\n\n'
            f'Kalau langkah di atas belum menjawab pertanyaan Anda, balas tiket ini dan '
            f'tim support akan mengambil alih.'
        )[:MAX_REPLY]

    def send_reply(self, ticket_id: str, reply: str, *, to: str | None = None,
                   subject: str | None = None, now: float | None = None,
                   transport=None) -> dict:
        """Send the reply over SMTP; the ticket's status follows what happened.

        Sent -> `pending` (waiting on the user) and the `emails_sent` counter
        moves. Not sent -> the ticket stays `open`, the reason is stored with it
        and returned, and the outbox has the failed attempt. `transport` is for
        tests: the default is the SMTP client in `mailer.py`.
        """
        from . import mailer

        at = time.time() if now is None else float(now)
        con = self.con()
        row = con.execute('SELECT subject, user_id, status FROM tickets WHERE id = ?',
                          (ticket_id,)).fetchone()
        if not row:
            return {'id': ticket_id, 'status': None, 'sent': False, 'error': 'tiket tidak ada'}

        recipient = _text(to or (row['user_id'] if mailer.RECIPIENT_RE.match(str(row['user_id'] or '')) else ''), 200)
        line = subject or f'Re: {row["subject"]}'
        result = mailer.send(recipient, line, reply, transport=transport, now=at)

        if result['sent']:
            # `COALESCE` keeps the first reply that left: the SLA gauge measures
            # response time, so a later follow-up must not move the clock.
            con.execute('UPDATE tickets SET status = ?, updated_at = ?, '
                        'first_response_at = COALESCE(first_response_at, ?) WHERE id = ?',
                        ('pending', at, at, ticket_id))
            con.commit()
            self._remember(ticket_id, {'reply': reply, 'replied_at': at, 'sent_to': recipient,
                                       'send_error': None})
            log.info('support: balasan tiket %s terkirim ke %s', ticket_id, recipient)
            _report({'emails_sent': 1, 'tickets_pending': self.pending_count(),
                     'sla_avg_response_min': self.sla_stats(now=at)['avg_response_min']})
            return {'id': ticket_id, 'status': 'pending', 'reply': reply, 'sent': True,
                    'to': recipient, 'error': None}

        # Not sent: keep it open (the SLA card must still bill it) and keep the
        # draft, so a retry does not need a second KB lookup
        con.execute('UPDATE tickets SET updated_at = ? WHERE id = ?', (at, ticket_id))
        con.commit()
        self._remember(ticket_id, {'reply': reply, 'reply_failed_at': at, 'sent_to': None,
                                   'send_error': result['error']})
        log.warning('support: balasan tiket %s GAGAL dikirim: %s', ticket_id, result['error'])
        return {'id': ticket_id, 'status': row['status'], 'reply': reply, 'sent': False,
                'to': recipient, 'error': result['error']}

    def resolve(self, ticket_id: str, note: str = '', now: float | None = None) -> dict:
        """Close the ticket; `resolved_at` is required by DB-SCHEMA.md §3."""
        at = time.time() if now is None else float(now)
        con = self.con()
        con.execute(
            "UPDATE tickets SET status = 'resolved', resolved_at = ?, updated_at = ? WHERE id = ?",
            (at, at, ticket_id),
        )
        con.commit()
        if note:
            self._remember(ticket_id, {'resolution': _text(note, 400), 'resolved_at': at})
        log.info('support: tiket %s resolved', ticket_id)
        _report({'tickets_resolved': 1, 'tickets_pending': self.pending_count(),
                 'sla_avg_response_min': self.sla_stats(now=at)['avg_response_min']})
        return {'id': ticket_id, 'status': 'resolved', 'resolved_at': at}

    def escalate(self, ticket_id: str, reason: str, now: float | None = None) -> dict:
        """Hand the ticket to the Orchestrator; `escalated` needs an assignee."""
        at = time.time() if now is None else float(now)
        con = self.con()
        con.execute(
            "UPDATE tickets SET status = 'escalated', assignee = ?, updated_at = ? WHERE id = ?",
            ('Orchestrator', at, ticket_id),
        )
        con.commit()
        self._remember(ticket_id, {'escalation': _text(reason, 400), 'escalated_at': at})
        # W8: escalation is a handoff, not a function call (AGENT-HANDOFFS.md §3).
        # The Orchestrator picks this up on the same run and records it for a
        # human; without a taker it expires and `handoff_check` bills it.
        try:
            from hermes_bridge import handoff

            handoff.hand_off('Support', 'Orchestrator', 'ticket_unresolved', f'ticket:{ticket_id}',
                            {'ticket': ticket_id, 'reason': _text(reason, 200)}, now=at)
        except Exception as err:  # noqa: BLE001 - the ticket is escalated either way
            log.warning('support: handoff eskalasi %s gagal: %s', ticket_id, err)
        log.info('support: tiket %s dieskalasi: %s', ticket_id, reason)
        return {'id': ticket_id, 'status': 'escalated', 'assignee': 'Orchestrator'}

    def pending_count(self) -> int:
        """Tickets still waiting on somebody: the `tickets_pending` gauge."""
        row = self.con().execute(
            "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'pending')"
        ).fetchone()
        return int(row[0]) if row else 0

    # -- the whole ticket (what triggers.py calls) --------------------------

    def handle_ticket(self, payload: object, char: Any = None, now: float | None = None,
                      transport=None) -> dict:
        """Triage, search, then reply from the KB or escalate. Never raises.

        Returns `{ticket, action, article, score}` where `action` is `replied`,
        `send_failed` (KB answered but the mail did not leave) or `escalated`.
        """
        data = payload if isinstance(payload, dict) else {}
        subject = _text(data.get('subject') or data.get('title') or data.get('name') or payload, 200)
        body = _text(data.get('body') or data.get('message') or data.get('description'))
        user_id = _text(data.get('user_id') or data.get('email') or 'unknown', 100)
        channel = _text(data.get('channel') or 'email', 20)

        if char:
            char.update(f'triage: {subject[:40] or "tiket baru"}')
        ticket = self.triage_ticket(subject, body, user_id=user_id, channel=channel, now=now)

        articles = self.search_kb(ticket['subject'], body)
        from .kb import min_score

        best = articles[0] if articles else None
        if best and float(best.get('score') or 0) >= min_score():
            if char:
                char.update(f'KB {float(best["score"]):.2f}: {str(best["title"])[:40]}')
            reply = self.draft_reply(ticket, articles)
            con = self.con()
            con.execute('UPDATE tickets SET kb_article_id = ? WHERE id = ?', (best.get('id'), ticket['id']))
            con.commit()
            sent = self.send_reply(ticket['id'], reply, to=data.get('email') or user_id,
                                   now=now, transport=transport)
            if sent['sent']:
                return {'ticket': ticket['id'], 'action': 'replied', 'article': best.get('id'),
                        'score': float(best.get('score') or 0), 'to': sent['to']}
            if char:
                char.update(f'balasan gagal: {str(sent["error"])[:40]}')
            return {'ticket': ticket['id'], 'action': 'send_failed', 'article': best.get('id'),
                    'score': float(best.get('score') or 0), 'error': sent['error']}

        if char:
            char.update(f'KB tidak yakin ({float(best["score"]) if best else 0:.2f}) - eskalasi')
        self.escalate(ticket['id'], f'KB di bawah {min_score()}: {ticket["subject"][:60]}', now=now)
        return {'ticket': ticket['id'], 'action': 'escalated', 'article': best.get('id') if best else None,
                'score': float(best.get('score') or 0) if best else 0.0}

    # -- SLA ----------------------------------------------------------------

    def check_sla_breaches(self, char: Any = None, now: float | None = None,
                           timeout: float = 300.0) -> dict:
        """Bill every late ticket on ONE card, then apply what was chosen.

        The card is raised only when there is something to decide, and
        `wait_for_approval` runs once for the whole batch (AGENTS.md §4.1).
        A timeout changes nothing: the next run bills the same tickets again.

        Returns `{breaches, decision, updated}`.
        """
        at = time.time() if now is None else float(now)
        rows = self.con().execute(
            "SELECT id, subject, priority, sla_deadline FROM tickets "
            "WHERE status IN ('open', 'pending') AND sla_deadline < ? ORDER BY sla_deadline",
            (at,),
        ).fetchall()
        if not rows:
            _report({'sla_breach_count': 0, 'tickets_pending': self.pending_count(),
                     'sla_avg_response_min': self.sla_stats(now=at)['avg_response_min']})
            return {'breaches': 0, 'decision': 'none', 'updated': 0}

        oldest_min = int((at - float(rows[0]['sla_deadline'])) // 60)
        message = f'{len(rows)} tiket lewat SLA (terlama {oldest_min} menit)'
        decision = char.ask(message, list(SLA_OPTIONS), timeout=timeout) if char else 'timeout'
        log.info('support: SLA %s -> %s', message, decision)

        updated = 0
        con = self.con()
        if decision == 'Extend SLA +30 menit':
            for row in rows:
                con.execute('UPDATE tickets SET sla_deadline = ?, updated_at = ? WHERE id = ?',
                            (at + EXTEND_SECONDS, at, row['id']))
            updated = len(rows)
        elif decision == 'Handle sekarang':
            for row in rows:
                con.execute("UPDATE tickets SET priority = 'urgent', assignee = ?, updated_at = ? WHERE id = ?",
                            ('Support', at, row['id']))
            updated = len(rows)
        elif decision == 'Close as resolved':
            for row in rows:
                con.execute("UPDATE tickets SET status = 'resolved', resolved_at = ?, updated_at = ? WHERE id = ?",
                            (at, at, row['id']))
            updated = len(rows)
        con.commit()

        remaining = con.execute(
            "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'pending') AND sla_deadline < ?",
            (at,),
        ).fetchone()[0]
        _report({'sla_breach_count': int(remaining), 'tickets_pending': self.pending_count(),
                 'sla_avg_response_min': self.sla_stats(now=at)['avg_response_min']})
        return {'breaches': len(rows), 'decision': decision, 'updated': updated}

    def sla_stats(self, days: float = 7.0, now: float | None = None) -> dict:
        """What `/sla` shows and what the `sla_avg_response_min` gauge carries.

        Compliance is measured only on tickets that are closed: an open ticket
        is not late yet, so it is counted separately as `late`. The average is
        `first_response_at - received_at` over replies that actually left (a
        failed send sets no `first_response_at`), so `avg_response_min: 0` with
        `samples: 0` means "no data", not "instant reply".
        """
        at = time.time() if now is None else float(now)
        since = at - float(days) * 86400.0
        con = self.con()
        closed = con.execute(
            'SELECT received_at, resolved_at, sla_deadline, first_response_at FROM tickets '
            'WHERE resolved_at IS NOT NULL AND resolved_at >= ?',
            (since,),
        ).fetchall()
        pending = int(con.execute(
            "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'pending')").fetchone()[0])
        late = int(con.execute(
            "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'pending') AND sla_deadline < ?",
            (at,)).fetchone()[0])
        on_time = sum(1 for row in closed if float(row['resolved_at']) <= float(row['sla_deadline']))
        replies = [float(row['first_response_at']) - float(row['received_at'])
                   for row in closed if row['first_response_at'] is not None]
        return {
            'days': float(days), 'resolved': len(closed), 'on_time': on_time,
            'compliance': (on_time / len(closed)) if closed else None,
            'pending': pending, 'late': late,
            'avg_response_min': int(round(sum(replies) / len(replies) / 60.0)) if replies else 0,
            'samples': len(replies),
        }

    # -- shared context -----------------------------------------------------

    def _remember(self, ticket_id: str, patch: dict) -> None:
        """`ticket:<id>` in SharedContext, so the next agent has the history."""
        try:
            from . import store

            store.context().update(f'ticket:{ticket_id}', patch, 'SupportAgent')
        except Exception as err:  # noqa: BLE001 - context is a convenience, not the record
            log.debug('support: context tiket %s gagal: %s', ticket_id, err)


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point `webhook_server/triggers.py` calls for `support_ticket`/`new_email`."""
    agent = SupportAgent()
    try:
        return agent.handle_ticket(payload, char=char)
    finally:
        agent.close()
