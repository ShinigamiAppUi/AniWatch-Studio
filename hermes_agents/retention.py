"""retention.py - RetentionAgent: the re-engagement campaign, to real addresses only.

Tools from AGENTS.md §4.4: `segment_users`, `draft_email`, `send_campaign`.

Who is a candidate: a row in `subscription_status` (DB-SCHEMA.md §7) whose plan
expired or is inside the grace window - that table is written by PaymentAgent
(W9), so before then the segment is empty and the agent says so instead of
inventing users to mail.

Who actually gets a letter: only a user whose id is an email address. The table
has no `email` column, and guessing an address from a user id would send someone
else's campaign to a stranger; a row without an address is reported as skipped
with that reason. A delivered campaign records `retention:<user_id>` so the same
person is not mailed again inside COOLDOWN_S, while a failed send records nothing
and is retried on the next run.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

log = logging.getLogger(__name__)

#: No second campaign to the same person inside this window
COOLDOWN_S = 7 * 86400.0

MAX_SEGMENT = 50


class RetentionAgent:
    """Segment lapsed subscribers, draft a letter, send it through the mailer."""

    def __init__(self, con: sqlite3.Connection | None = None, transport=None) -> None:
        self._con = con
        self._own = con is None
        self._transport = transport

    def con(self) -> sqlite3.Connection:
        if self._con is None:
            from . import store

            self._con = store.connect()
        return self._con

    def close(self) -> None:
        if self._own and self._con is not None:
            self._con.close()
            self._con = None

    # -- the tools ----------------------------------------------------------

    def segment_users(self, now: float | None = None) -> list[dict]:
        """Expired or in-grace subscribers not already mailed inside the cooldown."""
        at = time.time() if now is None else float(now)
        rows = self.con().execute(
            'SELECT user_id, plan, expires_at, grace_until, retry_count FROM subscription_status '
            'WHERE (expires_at IS NOT NULL AND expires_at <= ?) OR grace_until IS NOT NULL '
            'ORDER BY COALESCE(grace_until, expires_at) ASC LIMIT ?',
            (at, MAX_SEGMENT),
        ).fetchall()
        context = self._context()
        segment: list[dict] = []
        for row in rows:
            user = dict(row)
            last = context.get(f'retention:{user["user_id"]}') if context is not None else None
            contacted = float((last or {}).get('contacted_at') or 0)
            if at - contacted < COOLDOWN_S:
                continue
            user['in_grace'] = user.get('grace_until') is not None
            segment.append(user)
        return segment

    def draft_email(self, user: dict) -> dict:
        """A short, honest letter: what happened and how to keep watching."""
        plan = user.get('plan') or 'premium'
        if user.get('in_grace'):
            subject = f'Langganan {plan} Anda menunggu pembayaran'
            body = (
                f'Halo,\n\nPembayaran langganan {plan} Anda belum masuk, jadi akun Anda masih '
                'bisa dipakai sampai masa tenggang berakhir.\n'
                'Perbarui metode pembayaran di halaman langganan agar tidak turun ke paket gratis.\n\n'
                'Salam,\nAniWatch'
            )
        else:
            subject = f'Langganan {plan} Anda sudah berakhir'
            body = (
                f'Halo,\n\nLangganan {plan} Anda sudah berakhir. Episode baru tetap tayang setiap '
                'hari - aktifkan lagi kapan pun Anda siap.\n\n'
                'Salam,\nAniWatch'
            )
        return {'subject': subject, 'body': body, 'to': str(user.get('user_id') or '')}

    def send_campaign(self, users: list[dict], now: float | None = None) -> dict:
        """Send one letter per user; `sent`/`skipped` describe what really happened."""
        from . import mailer
        from hermes_bridge import bridge

        at = time.time() if now is None else float(now)
        sent: list[str] = []
        skipped: dict[str, str] = {}
        for user in users:
            user_id = str(user.get('user_id') or '')
            letter = self.draft_email(user)
            to = letter['to']
            if '@' not in to:
                skipped[user_id] = 'alamat email tidak tersedia (subscription_status tanpa email)'
                continue
            result = mailer.send(to, letter['subject'], letter['body'], transport=self._transport)
            if not result.get('sent'):
                skipped[user_id] = str(result.get('error') or 'gagal kirim')
                continue
            sent.append(user_id)
            context = self._context()
            if context is not None:
                try:
                    context.set(f'retention:{user_id}', {'contacted_at': at,
                                                         'subject': letter['subject']},
                                'Retention')
                except Exception as err:  # noqa: BLE001 - the mail already left
                    log.warning('retention: %s terkirim tapi tidak tercatat: %s', user_id, err)

        if sent:
            try:
                bridge.update_biz_metrics({'emails_sent': len(sent)})
            except Exception as err:  # noqa: BLE001 - metrics never fail a campaign
                log.warning('retention: metric emails_sent tidak terkirim: %s', err)
        log.info('retention: %d terkirim, %d dilewati', len(sent), len(skipped))
        return {'sent': len(sent), 'sent_to': sent, 'skipped': skipped}

    # -- internals ----------------------------------------------------------

    def _context(self):
        try:
            from . import store

            return store.context()
        except Exception as err:  # noqa: BLE001 - without context the run is just less careful
            log.debug('retention: context tidak tersedia: %s', err)
            return None


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point `webhook_server/triggers.py` calls for `retention_check`."""
    data = payload if isinstance(payload, dict) else {}
    now = data.get('now')
    agent = RetentionAgent()
    try:
        if char:
            char.update('segment_users', tool='segment_users')
        segment = agent.segment_users(now=now if isinstance(now, (int, float)) else None)
        if char:
            char.update(f'send_campaign ke {len(segment)} user', tool='send_campaign')
        result = agent.send_campaign(segment, now=now if isinstance(now, (int, float)) else None)
        return {'action': 'campaign' if result['sent'] else 'no_segment',
                'segments': len(segment), **result}
    finally:
        agent.close()
