"""moderator.py - Moderator: is this comment allowed, and who gets banned.

The three tools AGENTS.md §? lists, with the one rule that makes them usable as
evidence: `ban_account` writes an append-only row with the *rule* it broke and
the reason (SECURITY.md §10 - "audit yang bisa dihapus oleh agent bukan audit").
Nothing here ever deletes or edits a `moderation_events` row.

Why a rule table and not an LLM: a ban has to be explainable to the person it
hits. The rules are short, deterministic and testable; when a real model joins,
it can suggest a verdict, but the row still records a rule key.

There is no comment webhook yet (the 13 triggers in `triggers.py` are the
business ones), so this runs from whatever moderation queue is added later - or
from a test, which is how it is checked today.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

MAX_TEXT = 2000

#: `rule` -> the words that make a comment break it. Order matters: first wins.
RULES: dict[str, tuple[str, ...]] = {
    'piracy': ('download gratis', 'nonton gratis', 'link torrent', 'bajakan', 'streaming ilegal',
               'situs bajakan', 'mirror', 'telegram gratis'),
    'abuse': ('anjing', 'bangsat', 'kontol', 'idiot', 'goblok', 'mati aja', 'bunuh diri'),
    'spam': ('promo', 'judi', 'slot', 'casino', 'follow back', 'wa.me', 'bit.ly', 'iklan'),
    'spoiler': ('spoiler', 'akhir cerita', 'mati di episode', 'plot twist'),
}

#: What a verdict means for the account
BAN_RULES = ('piracy', 'abuse')


def _text(value: object, limit: int = MAX_TEXT) -> str:
    if isinstance(value, dict):
        for key in ('comment', 'body', 'message', 'text', 'description'):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return ' '.join(found.split())[:limit]
        return ''
    return ' '.join(str(value or '').split())[:limit]


def classify(text: str) -> str | None:
    """The first `rule` the text breaks, or None when it looks clean."""
    lowered = (text or '').lower()
    for rule, words in RULES.items():
        if any(word in lowered for word in words):
            return rule
    return None


class ModeratorAgent:
    """Filter, flag, ban - and remember why."""

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

    # -- the tools ----------------------------------------------------------

    def filter_comment(self, comment: object, *, subject: str | None = None) -> dict:
        """`clean` or the rule it breaks; `action` says what should happen.

        `action` is `allow` for clean text, `flag` for a spoiler/spam (visible,
        not banned) and `ban` for piracy/abuse.
        """
        text = _text(comment)
        rule = classify(text)
        if rule is None:
            return {'verdict': 'clean', 'rule': None, 'action': 'allow', 'subject': subject}
        return {'verdict': rule, 'rule': rule,
                'action': 'ban' if rule in BAN_RULES else 'flag', 'subject': subject}

    def flag_content(self, subject: str, rule: str, reason: str = '', *, actor: str = 'Moderator',
                     now: float | None = None) -> dict:
        """Record a flag without touching the account."""
        return self._record('flag', user_id=None, subject=subject, rule=rule, reason=reason,
                            actor=actor, now=now)

    def ban_account(self, user_id: str, rule: str, reason: str = '', *, subject: str | None = None,
                    actor: str = 'Moderator', now: float | None = None) -> dict:
        """Ban with the rule and the reason stored; append-only, never deletes."""
        if not str(user_id or '').strip():
            raise ValueError('ban_account butuh user_id')
        if not str(rule or '').strip():
            raise ValueError('ban_account butuh rule yang dilanggar (SECURITY.md §10)')
        return self._record('ban', user_id=str(user_id).strip(), subject=subject, rule=rule,
                            reason=reason, actor=actor, now=now)

    def is_banned(self, user_id: str) -> bool:
        """True when the newest event for this account is a ban (nothing deletes)."""
        row = self.con().execute(
            "SELECT kind FROM moderation_events WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (str(user_id or '').strip(),),
        ).fetchone()
        return bool(row) and row['kind'] == 'ban'

    def history(self, user_id: str, limit: int = 20) -> list[dict]:
        rows = self.con().execute(
            'SELECT id, kind, user_id, subject, rule, reason, actor, created_at '
            'FROM moderation_events WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
            (str(user_id or '').strip(), int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- the whole comment --------------------------------------------------

    def handle_comment(self, payload: object, char: Any = None, now: float | None = None) -> dict:
        """Judge one comment and do what the verdict says. Never raises."""
        data = payload if isinstance(payload, dict) else {}
        text = _text(data.get('comment') or data.get('body') or data.get('message') or payload)
        user_id = _text(data.get('user_id') or data.get('author') or '', 100)
        subject = _text(data.get('comment_id') or data.get('id') or '', 80) or None

        if char:
            char.update(f'filter komentar: {text[:40]}')
        verdict = self.filter_comment(text, subject=subject)
        if verdict['action'] == 'allow':
            return {'verdict': 'clean', 'action': 'allow', 'subject': subject}

        if verdict['action'] == 'flag':
            event = self.flag_content(subject or '(tanpa id)', verdict['rule'],
                                      reason=text[:200], now=now)
            if char:
                char.update(f'{verdict["rule"]}: ditandai, tidak di-ban')
            return {'verdict': verdict['rule'], 'action': 'flag', 'event': event['id']}

        if not user_id:
            # Without an account there is nobody to ban: flag it and say so
            event = self.flag_content(subject or '(tanpa id)', verdict['rule'],
                                      reason=text[:200], now=now)
            if char:
                char.update(f'{verdict["rule"]}: tanpa user_id, hanya ditandai')
            return {'verdict': verdict['rule'], 'action': 'flag', 'event': event['id']}

        event = self.ban_account(user_id, verdict['rule'], reason=text[:200], subject=subject, now=now)
        if char:
            char.update(f'ban {user_id}: {verdict["rule"]}')
        return {'verdict': verdict['rule'], 'action': 'ban', 'event': event['id'], 'user_id': user_id}

    # -- internals ----------------------------------------------------------

    def _record(self, kind: str, *, user_id: str | None, subject: str | None, rule: str,
                reason: str, actor: str, now: float | None) -> dict:
        at = time.time() if now is None else float(now)
        event = {
            'id': f'md-{uuid.uuid4().hex[:10]}',
            'kind': kind,
            'user_id': user_id,
            'subject': (subject or '')[:80] or None,
            'rule': rule[:40],
            'reason': _text(reason, 400),
            'actor': actor,
            'created_at': at,
        }
        self.con().execute(
            'INSERT INTO moderation_events (id, kind, user_id, subject, rule, reason, actor, created_at) '
            'VALUES (:id, :kind, :user_id, :subject, :rule, :reason, :actor, :created_at)',
            event,
        )
        self.con().commit()
        log.info('moderator: %s user=%s rule=%s subject=%s', kind, user_id or '-', rule, subject or '-')
        return event
