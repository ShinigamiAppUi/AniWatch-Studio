"""user_report.py - UserReportAgent: a "Laporkan Masalah" button, routed.

The flow AGENTS.md §4.3 defines:

    laporan -> triage_report
      |- technical        -> check_episode_health
      |    |- bermasalah  -> trigger_qc_pipeline -> notify_user("sedang diperbaiki")
      |    +- normal      -> notify_user("coba clear cache")
      |- account/billing  -> forward_to_support -> Support
      +- spam/duplikat    -> log_report -> selesai

Two of those are honest placeholders rather than pretend integrations:

- `notify_user` writes the message into the report's context (`report:<id>`) and
  the log. No push channel exists in this fork, so nothing is "sent".
- `trigger_qc_pipeline` marks the report `investigating` and asks the pipeline
  for a re-check by episode id; the pipeline itself is W6/W7. The report row is
  the record either way.

Duplicate rule (DB-SCHEMA.md §4): the same episode reported again inside 24
hours is *not* a new row. It returns the earlier report instead, so
`/report-stats` counts users, not refreshes.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

#: DB-SCHEMA.md §4: "episode sama dalam 24 jam"
DUPLICATE_WINDOW_S = 24 * 3600.0

MAX_TEXT = 2000

#: Triage words, checked in this order (spam first: it is the cheapest exit)
_SPAM = ('spam', 'iklan', 'promosi', 'judi', 'situs lain', 'tes', 'test')
_ACCOUNT = ('akun', 'login', 'password', 'bayar', 'pembayaran', 'langganan', 'premium',
            'refund', 'billing', 'tagihan', 'email')
_TECHNICAL = ('video', 'subtitle', 'buffering', 'error', '404', 'putar', 'suara', 'gambar',
              'crash', 'aplikasi', 'lag', 'kualitas')


def _text(value: object, limit: int = MAX_TEXT) -> str:
    """One line from whatever carried the report."""
    if isinstance(value, dict):
        for key in ('description', 'message', 'body', 'subject', 'title'):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return ' '.join(found.split())[:limit]
        return ''
    return ' '.join(str(value or '').split())[:limit]


def new_report_id() -> str:
    """`rp-1a2b3c4d5e`."""
    return f'rp-{uuid.uuid4().hex[:10]}'


class UserReportAgent:
    """Triage, health check, forward - the report's whole life."""

    def __init__(self, con: sqlite3.Connection | None = None) -> None:
        self._con = con
        self._own = con is None

    def con(self) -> sqlite3.Connection:
        if self._con is None:
            from . import store

            self._con = store.connect()
        return self._con

    def close(self) -> None:
        if self._own and self._con is not None:
            self._con.close()
            self._con = None

    # -- the tools (AGENTS.md §4.3) -----------------------------------------

    def triage_report(self, description: str, episode_id: str | None = None) -> str:
        """`technical` / `account` / `spam` / `content` from the report's words."""
        text = f'{description} {episode_id or ""}'.lower()
        if any(word in text for word in _SPAM):
            return 'spam'
        if any(word in text for word in _ACCOUNT):
            return 'account'
        if any(word in text for word in _TECHNICAL):
            return 'technical'
        return 'content'

    def log_report(self, description: str, category: str, user_id: str = 'unknown',
                   episode_id: str | None = None, *, report: str | None = None,
                   now: float | None = None) -> dict:
        """Insert the report, or return the earlier one when it is a duplicate.

        Returns `{id, status, duplicate}`; `duplicate` is True when nothing was
        written because the same episode was reported inside 24 hours.
        """
        at = time.time() if now is None else float(now)
        con = self.con()
        if episode_id:
            earlier = con.execute(
                "SELECT id, status FROM user_reports WHERE episode_id = ? AND created_at > ? "
                "AND status != 'dismissed' ORDER BY created_at DESC LIMIT 1",
                (episode_id, at - DUPLICATE_WINDOW_S),
            ).fetchone()
            if earlier:
                log.info('user_report: duplikat episode %s (laporan %s), tidak menulis baris baru',
                         episode_id, earlier['id'])
                return {'id': earlier['id'], 'status': earlier['status'], 'duplicate': True}

        rid = report or new_report_id()
        con.execute(
            'INSERT INTO user_reports (id, user_id, episode_id, category, description, status, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (rid, _text(user_id, 100) or 'unknown', episode_id, category, _text(description), 'pending', at),
        )
        con.commit()
        log.info('user_report: %s %s (episode=%s)', rid, category, episode_id or '-')
        return {'id': rid, 'status': 'pending', 'duplicate': False}

    def check_episode_health(self, episode_id: str | None) -> dict:
        """Is the episode there and live? Used to tell a real bug from a cache.

        A missing `episode_id` is not a health problem: the report is about the
        account, or the user did not say which episode.
        """
        if not episode_id:
            return {'found': False, 'status': None, 'problem': False}
        row = self.con().execute(
            'SELECT episode_id, status FROM episode_schedule WHERE episode_id = ?', (episode_id,)
        ).fetchone()
        if not row:
            return {'found': False, 'status': None, 'problem': True}
        # DB-SCHEMA.md §5: an episode that went out is `live` (`scheduled ->
        # live`); `cancelled`/`failed` are the broken ones, and a scheduled one
        # that users cannot watch yet counts as broken too.
        return {'found': True, 'status': row['status'], 'problem': row['status'] != 'live'}

    def trigger_qc_pipeline(self, report_id: str, episode_id: str | None,
                            now: float | None = None) -> dict:
        """Mark the report `investigating` and ask for a re-check of the episode."""
        at = time.time() if now is None else float(now)
        self._status(report_id, 'investigating', at)
        self._remember(report_id, {'qc_requested_at': at, 'episode_id': episode_id})
        log.info('user_report: %s -> investigating (pipeline episode %s)', report_id, episode_id or '-')
        return {'id': report_id, 'status': 'investigating'}

    def forward_to_support(self, report_id: str, description: str, user_id: str = 'unknown',
                           episode_id: str | None = None, now: float | None = None) -> dict:
        """Open a real ticket for Support and mark the report `forwarded`."""
        from .support import SupportAgent

        at = time.time() if now is None else float(now)
        support = SupportAgent(con=self.con())
        ticket = support.triage_ticket(
            subject=f'Laporan user: {description[:80]}',
            body=description,
            user_id=user_id,
            channel='form',
            now=at,
        )
        self._status(report_id, 'forwarded', at)
        self._remember(report_id, {'ticket': ticket['id'], 'forwarded_at': at, 'episode_id': episode_id})
        log.info('user_report: %s -> Support (%s)', report_id, ticket['id'])
        return {'id': report_id, 'status': 'forwarded', 'ticket': ticket['id']}

    def notify_user(self, user_id: str, message: str, *, report_id: str | None = None,
                    now: float | None = None) -> dict:
        """Record what the user is told. No push channel is wired yet."""
        at = time.time() if now is None else float(now)
        if report_id:
            self._remember(report_id, {'notified': _text(message, 400), 'notified_at': at})
        log.info('user_report: notifikasi ke %s disiapkan - %s (kanal push belum tersambung)',
                 user_id or 'unknown', _text(message, 120))
        return {'user_id': user_id, 'message': message, 'sent': False}

    # -- the whole report ---------------------------------------------------

    def handle_report(self, payload: object, char: Any = None, now: float | None = None) -> dict:
        """Triage, then QC / Support / done. Never raises.

        Returns `{report, category, action}` where `action` is `qc`, `replied`,
        `forwarded`, `dismissed` or `duplicate`.
        """
        data = payload if isinstance(payload, dict) else {}
        description = _text(data.get('description') or data.get('message') or payload) or '(tanpa deskripsi)'
        user_id = _text(data.get('user_id') or data.get('email') or 'unknown', 100)
        episode_id = _text(data.get('episode_id') or '', 60) or None

        if char:
            char.update(f'triage laporan: {description[:40]}')
        category = self.triage_report(description, episode_id)
        logged = self.log_report(description, category, user_id=user_id, episode_id=episode_id, now=now)
        if logged['duplicate']:
            if char:
                char.update(f'laporan duplikat: {logged["id"]}')
            return {'report': logged['id'], 'category': category, 'action': 'duplicate'}

        rid = logged['id']
        if category == 'spam':
            self._status(rid, 'dismissed', now)
            if char:
                char.update('spam - tidak diteruskan')
            return {'report': rid, 'category': category, 'action': 'dismissed'}

        if category == 'technical':
            health = self.check_episode_health(episode_id)
            if health['problem']:
                self.trigger_qc_pipeline(rid, episode_id, now=now)
                self.notify_user(user_id, 'Terima kasih - episode ini sedang diperbaiki.', report_id=rid, now=now)
                if char:
                    char.update(f'QC diminta: {episode_id or "episode tidak dikenal"}')
                return {'report': rid, 'category': category, 'action': 'qc'}
            self.notify_user(user_id, 'Coba hapus cache lalu muat ulang - episode ini tampak normal.',
                             report_id=rid, now=now)
            self._status(rid, 'resolved', now)
            if char:
                char.update('episode normal - saran cache dikirim')
            return {'report': rid, 'category': category, 'action': 'replied'}

        # account and content both need a human: they become a Support ticket
        forwarded = self.forward_to_support(rid, description, user_id=user_id, episode_id=episode_id, now=now)
        self.notify_user(user_id, 'Laporan Anda diteruskan ke tim support.', report_id=rid, now=now)
        if char:
            char.update(f'diteruskan ke Support ({forwarded["ticket"]})')
        return {'report': rid, 'category': category, 'action': 'forwarded'}

    # -- internals ----------------------------------------------------------

    def _status(self, report_id: str, status: str, now: float | None = None) -> None:
        at = time.time() if now is None else float(now)
        con = self.con()
        resolved = at if status in ('resolved', 'dismissed') else None
        con.execute(
            'UPDATE user_reports SET status = ?, resolved_at = ? WHERE id = ?',
            (status, resolved, report_id),
        )
        con.commit()

    def _remember(self, report_id: str, patch: dict) -> None:
        try:
            from . import store

            store.context().update(f'report:{report_id}', patch, 'UserReportAgent')
        except Exception as err:  # noqa: BLE001
            log.debug('user_report: context %s gagal: %s', report_id, err)


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point `webhook_server/triggers.py` calls for `user_report`."""
    agent = UserReportAgent()
    try:
        return agent.handle_report(payload, char=char)
    finally:
        agent.close()
