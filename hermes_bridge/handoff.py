"""handoff.py - passing one piece of work from one agent to another.

An agent never calls another agent. It writes a handoff envelope into
SharedContext and the Orchestrator (or the recipient's own trigger) decides what
happens next (AGENT-HANDOFFS.md §2).

The envelope shape is fixed by `ENVELOPE_FIELDS`, and the transitions are fixed by
`HANDOFF_TABLE` - the table in AGENT-HANDOFFS.md §3. A handoff that is not a row
in that table raises `UnknownHandoff` instead of quietly inventing a new flow:
"selain itu = desain baru, harus punya baris di tabel sebelum masuk kode".

`take()` deletes after reading. A handoff is a transition, not state; the
recipient that needs the facts again reads the `subject` key (`lead:42`,
`ticket:tk-9`), which the sender keeps in the same context.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .shared_context import SharedContext, default as default_context

log = logging.getLogger(__name__)

#: Every envelope carries exactly these fields (AGENT-HANDOFFS.md §2)
ENVELOPE_FIELDS = ('from', 'to', 'reason', 'subject', 'payload', 'expects', 'deadline', 'created_at')

#: (from, to, reason) -> (expects, payload fields the table requires)
HANDOFF_TABLE: dict[tuple[str, str, str], tuple[str, tuple[str, ...]]] = {
    ('Sales', 'Marketing', 'lead_converted'): ('welcome_email_campaign', ('name', 'email', 'score', 'plan')),
    ('Sales', 'Support', 'meeting_scheduled'): ('pre_meeting_brief', ('when', 'timezone')),
    ('Marketing', 'Support', 'customer_onboarding'): ('onboarding_followup', ('plan', 'channel')),
    ('Support', 'Orchestrator', 'ticket_unresolved'): ('escalate_to_human', ('ticket', 'reason')),
    ('UserReportAgent', 'Support', 'report_account'): ('handle_billing', ('category', 'user_id')),
    ('UserReportAgent', 'QualityChecker', 'report_technical'): ('recheck_episode', ('episode_id',)),
    ('PaymentAgent', 'RevenueTracker', 'payment_settled'): ('record_transaction', ('order_id', 'amount')),
    ('PaymentAgent', 'SecOps', 'chargeback'): ('flag_account', ('order_id', 'user_id')),
    ('DMCA', 'EpisodeScheduler', 'takedown'): ('cancel_schedule', ('episode_id',)),
    ('Scraper', 'Metadata', 'episode_fetched'): ('enrich_metadata', ('episode_id',)),
    ('QualityChecker', 'Orchestrator', 'qc_failed'): ('retry_or_escalate', ('episode_id', 'damage')),
    ('Orchestrator', 'Manusia', 'escalate'): ('decide', ('summary', 'options')),
}

#: Ready-made deadlines: a handoff nobody took in this long is late
DEFAULT_DEADLINE_S = 3600.0


class UnknownHandoff(ValueError):
    """The (from, to, reason) triple is not a row in AGENT-HANDOFFS.md §3."""


def _slug(subject: str) -> str:
    """The last part of `subject`, safe for a key: `ticket:tk-1` -> `tk-1`."""
    tail = str(subject or '').strip().split(':')[-1] or 'x'
    safe = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in tail.lower())
    return safe.strip('-') or 'x'


def key_for(from_role: str, to_role: str, subject: str) -> str:
    """`handoff:<from>:<to>:<subject tail>`, all lower case (§2)."""
    return f'handoff:{from_role.lower()}:{to_role.lower()}:{_slug(subject)}'


def transition(from_role: str, to_role: str, reason: str) -> tuple[str, tuple[str, ...]]:
    """Look the triple up in the official table.

    Raises:
        UnknownHandoff: not a row. Never guessed - a new flow needs a row first.
    """
    row = HANDOFF_TABLE.get((from_role, to_role, reason))
    if row is None:
        allowed = [f'{f}->{t} ({r})' for (f, t, r) in HANDOFF_TABLE if f == from_role]
        raise UnknownHandoff(
            f'handoff {from_role}->{to_role} ({reason}) tidak ada di tabel AGENT-HANDOFFS.md §3'
            + (f'; dari {from_role} yang sah: {", ".join(allowed)}' if allowed else '')
        )
    return row


def hand_off(from_role: str, to_role: str, reason: str, subject: str, payload: dict,
             expects: str | None = None, deadline: float | None = None, *,
             context: SharedContext | None = None, now: float | None = None) -> str:
    """Write one handoff envelope and return its key.

    The transition is validated against the table, `expects` must match what the
    table says, and the payload must carry the fields the recipient is promised.
    A handoff that cannot be acted on is worse than no handoff at all.

    Raises:
        UnknownHandoff: the transition is not in the table.
        ValueError: expects mismatch, or the payload is missing promised fields.
    """
    table_expects, required = transition(from_role, to_role, reason)
    if expects is not None and expects != table_expects:
        raise ValueError(f'expects untuk {reason} harus {table_expects!r}, bukan {expects!r}')
    if not isinstance(payload, dict):
        raise ValueError('payload harus dict')
    missing = [name for name in required if not str(payload.get(name) or '').strip()]
    if missing:
        raise ValueError(f'payload {reason} kurang: {", ".join(missing)}')

    at = time.time() if now is None else float(now)
    if deadline is None:
        deadline = at + DEFAULT_DEADLINE_S
    key = key_for(from_role, to_role, subject)
    ctx = context or default_context()
    ctx.set(key, {
        'from': from_role,
        'to': to_role,
        'reason': reason,
        'subject': subject,
        'payload': payload,
        'expects': table_expects,
        'deadline': float(deadline) if deadline is not None else None,
        'created_at': at,
    }, from_role)
    log.info('handoff: %s -> %s (%s) key=%s', from_role, to_role, reason, key)
    return key


def get(key: str, *, context: SharedContext | None = None) -> dict | None:
    """The envelope, without consuming it (for inspection and `/handoffs`)."""
    return (context or default_context()).get(key)


def take(key: str, owner: str, *, context: SharedContext | None = None) -> dict | None:
    """Read and delete, but only for the role it was addressed to.

    Returns None when the key is gone or belongs to someone else - a recipient
    that picks up somebody else's work is worse than one that finds nothing.
    """
    ctx = context or default_context()
    envelope = ctx.get(key)
    if not isinstance(envelope, dict) or envelope.get('to') != owner:
        return None
    ctx.delete(key)
    log.info('handoff: %s diterima %s (%s)', envelope.get('from'), owner, envelope.get('subject'))
    return envelope


def pending(*, context: SharedContext | None = None) -> dict[str, dict]:
    """Every handoff nobody has taken yet, newest first."""
    return (context or default_context()).find('handoff:')


def pending_from(role: str, *, context: SharedContext | None = None) -> dict[str, dict]:
    """Handoffs left by `role` (used by the Orchestrator to follow the chain)."""
    return {key: env for key, env in pending(context=context).items()
            if isinstance(env, dict) and env.get('from') == role}


def expired(now: float | None = None, *, context: SharedContext | None = None) -> dict[str, dict]:
    """Handoffs past their `deadline` and still untaken (AGENT-HANDOFFS.md §5.5)."""
    at = time.time() if now is None else float(now)
    return {key: env for key, env in pending(context=context).items()
            if isinstance(env, dict) and env.get('deadline') and float(env['deadline']) < at}


def extend(key: str, seconds: float, *, context: SharedContext | None = None,
           now: float | None = None) -> dict | None:
    """Push a late handoff's deadline out; the human said "try again"."""
    ctx = context or default_context()
    envelope = ctx.get(key)
    if not isinstance(envelope, dict):
        return None
    at = time.time() if now is None else float(now)
    envelope['deadline'] = at + float(seconds)
    ctx.set(key, envelope, envelope.get('from') or 'Orchestrator')
    return envelope


def drop(key: str, *, context: SharedContext | None = None) -> bool:
    """Throw away a handoff the human decided to ignore."""
    removed = (context or default_context()).delete(key)
    if removed:
        log.info('handoff: %s dibuang atas keputusan manusia', key)
    return removed


def stats(*, context: SharedContext | None = None) -> dict[str, Any]:
    """`{pending, expired}` for `/health` and the orchestrator card."""
    now = time.time()
    everything = pending(context=context)
    late = expired(now, context=context)
    return {'pending': len(everything), 'expired': len(late), 'by_to': _by_to(everything)}


def _by_to(handoffs: dict[str, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for env in handoffs.values():
        role = str((env or {}).get('to') or '?')
        counts[role] = counts.get(role, 0) + 1
    return counts
