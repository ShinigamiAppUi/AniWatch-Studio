"""sales.py - SalesAgent: a lead becomes a score, a stage, and a handoff.

AGENTS.md §4.1 gives Sales three triggers (`new_lead`, `form_submit`,
`deal_stage_change`) and five tools. This module is those tools, and the rule
that makes them checkable:

- **A score is a list of reasons, not a feeling.** `qualify_lead()` adds points
  from the payload only (paid plan, budget, company size, referral source, a
  corporate mail domain, a named company) and returns every rule it applied.
  The threshold is `QUALIFY_MIN_SCORE`; a lead under it is `new`, not qualified,
  and nothing is handed to Marketing. There is no LLM call here on purpose: a
  score nobody can recompute is not a metric, it is an opinion.
- **The CRM is SharedContext.** `lead:<id>` is the record (DB-SCHEMA.md §11);
  `update_crm()` writes there and says so. No HubSpot call is made and
  `HUBSPOT_API_KEY` is not read - a fork that claimed to have written a CRM row
  nobody can open would be lying to the person reading the bubble.
- **Mail is SMTP, and a skip is a value.** `send_email()` goes through
  `mailer.send()`, the same channel Support uses; without `SMTP_HOST` the result
  is `sent: False` with the reason. A converted lead is still converted - the
  missing acknowledgement is reported, not hidden.
- **A stage change either happens completely or not at all.** `meeting` without
  `when`/`timezone` is refused (the handoff table promises both), and a stage
  that is not in `STAGES` is refused with the list of what is. Aliases
  (`closed_won`, `demo`) are mapped, not guessed.

Handoffs follow AGENT-HANDOFFS.md §3 exactly: a qualified lead leaves one to
Marketing (`lead_converted`), a booked meeting one to Support
(`meeting_scheduled`). Sales never calls Marketing; the Orchestrator follows the
handoff (`hermes_agents/orchestrator.py`).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from hermes_bridge import handoff

from . import store

log = logging.getLogger(__name__)

#: At or above this the lead is qualified and Marketing hears about it
QUALIFY_MIN_SCORE = 0.5

#: The stages a lead can be in; `deal_stage_change` accepts nothing else
STAGES = ('new', 'contacted', 'qualified', 'meeting', 'won', 'lost')

#: CRM tools name deals differently; map the obvious ones instead of guessing
STAGE_ALIASES = {
    'converted': 'won',
    'closed_won': 'won',
    'closed-won': 'won',
    'closed_lost': 'lost',
    'closed-lost': 'lost',
    'demo': 'meeting',
    'meeting_scheduled': 'meeting',
}

#: A free mailbox says nothing about buying intent, a company domain says a little
FREE_DOMAINS = frozenset({
    'gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
    'live.com', 'icloud.com', 'protonmail.com', 'proton.me', 'mail.com',
})

#: The two plans this fork sells (AGENTS.md §4.6 / DB-SCHEMA.md §7)
PAID_PLANS = ('premium', 'premium_plus')


def _at(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _text(value: object, limit: int = 200) -> str:
    return ' '.join(str(value or '').split())[:limit]


def _number(value: object) -> float | None:
    """A payload number, or None when it is missing/garbage - never a silent 0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace('.', '').replace(',', '')) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None


def _metric(delta: dict) -> None:
    """Send one counter; a closed office must not fail the lead work."""
    from hermes_bridge import bridge

    try:
        bridge.update_biz_metrics(delta)
    except Exception as err:  # noqa: BLE001 - the context record is the source, not the panel
        log.warning('sales: metric %s tidak terkirim: %s', delta, err)


# ---------------------------------------------------------------------------
# Identity and scoring
# ---------------------------------------------------------------------------

def lead_key(lead_id: str) -> str:
    return f'lead:{lead_id}'


def lead_id_of(payload: dict) -> str:
    """A stable id from the payload: `lead_id`/`id`, else the email, else the name.

    Derived from the address so a double form submit - the same person, no id -
    lands on the same record instead of becoming two leads.
    """
    explicit = _text(payload.get('lead_id') or payload.get('id'), 80)
    if explicit:
        return explicit
    source = _text(payload.get('email') or payload.get('name'), 120).lower()
    slug = re.sub(r'[^a-z0-9]+', '-', source).strip('-')
    return slug[:60] or 'tanpa-id'


def plan_of(payload: dict) -> str:
    plan = _text(payload.get('plan') or 'free', 40).lower()
    return plan if plan in ('free',) + PAID_PLANS else 'free'


def qualify_lead(payload: dict) -> dict:
    """Score a lead from the payload, with one reason per point awarded.

    Pure: it writes nothing. Callers can recompute the same score from the same
    payload, which is the only kind of sales score worth showing a CEO.
    """
    reasons: list[dict] = []

    def add(rule: str, points: float, detail: str) -> None:
        reasons.append({'rule': rule, 'points': points, 'detail': detail})

    plan = plan_of(payload)
    if plan in PAID_PLANS:
        add('plan', 0.30, f'memilih paket berbayar ({plan})')

    budget = _number(payload.get('budget_idr') or payload.get('budget'))
    if budget is not None and budget >= 150000:
        add('budget', 0.20, f'anggaran Rp{int(budget):,}'.replace(',', '.'))
    elif budget is not None and budget >= 50000:
        add('budget', 0.10, f'anggaran Rp{int(budget):,}'.replace(',', '.'))

    size = _number(payload.get('company_size') or payload.get('employees'))
    if size is not None and size >= 10:
        add('company_size', 0.15, f'{int(size)} orang di perusahaan')

    source = _text(payload.get('source'), 40).lower()
    if source in ('referral', 'partner', 'community'):
        add('source', 0.15, f'datang dari {source}')

    email = _text(payload.get('email'), 200).lower()
    domain = email.rsplit('@', 1)[-1] if '@' in email else ''
    if domain and domain not in FREE_DOMAINS:
        add('domain', 0.10, f'domain perusahaan ({domain})')

    if _text(payload.get('company'), 120):
        add('company', 0.10, 'nama perusahaan diisi')

    score = min(1.0, round(sum(row['points'] for row in reasons), 3))
    return {'score': score, 'reasons': reasons, 'qualified': score >= QUALIFY_MIN_SCORE,
            'threshold': QUALIFY_MIN_SCORE}


# ---------------------------------------------------------------------------
# The five tools from AGENTS.md §4.1
# ---------------------------------------------------------------------------

def update_crm(lead_id: str, patch: dict, *, now: float | None = None) -> dict:
    """`update_crm`: merge fields into the lead record in SharedContext.

    There is no CRM API in this fork. The result says `backend: shared_context`
    and repeats why, so "CRM updated" in a bubble always points at a row a
    person can read (`/leads`, `sqlite3 shared.db`).
    """
    at = _at(now)
    merged = store.context().update(lead_key(lead_id), {**patch, 'updated_at': at}, 'Sales')
    _metric({'crm_updates': 1})
    log.info('sales: lead %s diperbarui (%s)', lead_id, ', '.join(sorted(patch)))
    return {'lead': lead_id, 'record': merged, 'backend': 'shared_context',
            'note': 'tidak ada API CRM yang terhubung; HUBSPOT_API_KEY tidak dibaca fork ini'}


def draft_email(lead: dict) -> tuple[str, str]:
    """The acknowledgement a qualified lead gets: short, and only what is true."""
    name = _text(lead.get('name'), 80) or 'Halo'
    plan = plan_of(lead)
    subject = 'Terima kasih sudah menghubungi AniWatch'
    body = (
        f'Halo {name},\n\n'
        'Terima kasih sudah menghubungi AniWatch. Kami sudah menerima data Anda'
        + (f' dan mencatat minat pada paket {plan}' if plan in PAID_PLANS else '')
        + '.\n\n'
        'Tim kami akan menghubungi Anda untuk menjawab pertanyaan dan, kalau cocok, '
        'mengatur waktu demo singkat. Kalau ada kebutuhan khusus, balas email ini '
        'dan kami siapkan sebelum menghubungi Anda.\n\n'
        'Salam,\nTim AniWatch'
    )
    return subject, body


def send_email(email: str, subject: str, body: str, *, transport=None,
               now: float | None = None) -> dict:
    """`send_email`: one letter through `mailer`, counted only when it left."""
    from . import mailer

    result = mailer.send(email, subject, body, transport=transport, now=now)
    sent = bool(result.get('sent'))
    if sent:
        _metric({'emails_sent': 1})
    return {'sent': sent, 'reason': result.get('error'), 'to': result.get('to'),
            'outbox': result.get('outbox')}


def schedule_meeting(lead_id: str, when: str, timezone: str, needs: str = '', *,
                     now: float | None = None) -> dict:
    """`schedule_meeting`: record the slot and hand Support a pre-meeting brief.

    No calendar is written: `GOOGLE_*` credentials are not wired in this fork, so
    the meeting exists as the handoff Support reads, and the result says that.
    """
    at = _at(now)
    key = handoff.hand_off(
        'Sales', 'Support', 'meeting_scheduled', f'lead:{lead_id}',
        {'when': when, 'timezone': timezone, 'needs': _text(needs, 200) or '-'},
        now=at,
    )
    log.info('sales: meeting %s untuk lead %s (%s)', when, lead_id, timezone)
    return {'handoff': key, 'calendar': None,
            'calendar_reason': 'integrasi kalender (GOOGLE_*) belum ada di fork ini'}


# ---------------------------------------------------------------------------
# The three triggers
# ---------------------------------------------------------------------------

def _record_lead(lead_id: str, payload: dict, scored: dict, *, stage: str,
                 now: float) -> dict:
    """Write the lead record once, so `/leads` and Marketing read the same facts."""
    record = {
        'name': _text(payload.get('name'), 120),
        'email': _text(payload.get('email'), 200),
        'company': _text(payload.get('company'), 120),
        'plan': plan_of(payload),
        'source': _text(payload.get('source'), 40) or 'direct',
        'score': scored['score'],
        'score_reasons': scored['reasons'],
        'threshold': scored['threshold'],
        'stage': stage,
        'status': 'qualified' if scored['qualified'] else 'nurture',
        'created_at': now,
        'updated_at': now,
    }
    if stage == 'qualified':
        record['qualified_at'] = now
    merged = update_crm(lead_id, record, now=now)
    return merged['record']


def handle_new_lead(payload: object, *, trigger: str = 'new_lead', char: Any = None,
                    now: float | None = None, transport=None) -> dict:
    """`new_lead` / `form_submit`: score, store, acknowledge, hand to Marketing.

    A repeat submission for a lead already past `new` is a `duplicate`: no second
    letter, no second `leads_qualified`, and no second handoff. Double-clicking a
    form is not a new customer.
    """
    at = _at(now)
    data = payload if isinstance(payload, dict) else {}
    name = _text(data.get('name'), 120)
    email = _text(data.get('email'), 200)
    if not name and not email:
        return {'action': 'refused', 'reason': 'payload tanpa name/email'}

    lead_id = lead_id_of(data)
    existing = store.context().get(lead_key(lead_id)) or {}
    if isinstance(existing, dict) and existing.get('stage') in ('qualified', 'meeting', 'won'):
        log.info('sales: lead %s sudah %s - duplikat diabaikan', lead_id, existing.get('stage'))
        return {'action': 'duplicate', 'lead': lead_id, 'stage': existing.get('stage'),
                'score': existing.get('score'),
                'reason': f"lead ini sudah {existing.get('stage')}"}

    scored = qualify_lead(data)
    stage = 'qualified' if scored['qualified'] else 'new'
    record = _record_lead(lead_id, data, scored, stage=stage, now=at)
    if char:
        char.update(f"skor {scored['score']:.2f} ({len(scored['reasons'])} alasan) untuk "
                    f"{name or email}", tool='qualify_lead')

    result = {'action': 'qualified' if scored['qualified'] else 'nurture',
              'trigger': trigger, 'lead': lead_id, 'score': scored['score'],
              'reasons': scored['reasons'], 'threshold': scored['threshold'],
              'stage': stage, 'email': record.get('email'), 'handoff': None,
              'handoff_reason': None, 'mail': None,
              'metric': {'leads_qualified': 1} if scored['qualified'] else None}

    if not scored['qualified']:
        log.info('sales: lead %s belum qualified (skor %.2f)', lead_id, scored['score'])
        return result
    if not email:
        result['handoff_reason'] = 'tanpa email: tidak ada surat dan tidak ada handoff'
        return result

    try:
        result['handoff'] = handoff.hand_off(
            'Sales', 'Marketing', 'lead_converted', f'lead:{lead_id}',
            {'name': name or email, 'email': email, 'score': scored['score'],
             'plan': plan_of(data), 'channel': record.get('source')},
            now=at,
        )
    except (ValueError, handoff.UnknownHandoff) as err:
        result['handoff_reason'] = f'handoff tidak ditulis: {err}'
        log.warning('sales: %s', result['handoff_reason'])

    subject, body = draft_email({**data, 'plan': record.get('plan')})
    result['mail'] = send_email(email, subject, body, transport=transport, now=at)
    if char:
        char.update('balasan terkirim' if result['mail']['sent']
                    else f"email dilewati: {str(result['mail']['reason'])[:50]}",
                    tool='send_email')
    _metric({'leads_qualified': 1})
    log.info('sales: lead %s qualified (%.2f) -> Marketing', lead_id, scored['score'])
    return result


def handle_deal_stage(payload: object, *, char: Any = None, now: float | None = None) -> dict:
    """`deal_stage_change`: move the record, and act only on the two stages that act.

    `meeting` needs `when` + `timezone` (the handoff promises both to Support);
    `won` hands the lead to Marketing; everything else is just a new stage. A
    lead nobody wrote is refused, because inventing one would hide a broken
    trigger.
    """
    at = _at(now)
    data = payload if isinstance(payload, dict) else {}
    raw = _text(data.get('stage') or data.get('deal_stage'), 40).lower()
    stage = STAGE_ALIASES.get(raw, raw)
    if stage not in STAGES:
        return {'action': 'refused', 'reason': f'stage {raw or "kosong"} tidak dikenal',
                'allowed': list(STAGES)}

    lead_id = lead_id_of(data)
    existing = store.context().get(lead_key(lead_id))
    if not isinstance(existing, dict):
        return {'action': 'refused', 'lead': lead_id,
                'reason': f'lead {lead_id} tidak ada di SharedContext; kirim new_lead dulu'}

    if stage == 'meeting':
        when = _text(data.get('when') or data.get('scheduled_at'), 60)
        timezone = _text(data.get('timezone') or data.get('tz'), 60)
        if not (when and timezone):
            missing = [name for name, value in (('when', when), ('timezone', timezone)) if not value]
            return {'action': 'refused', 'lead': lead_id, 'stage': existing.get('stage'),
                    'reason': f'stage meeting butuh {", ".join(missing)}',
                    'missing': missing}

    update_crm(lead_id, {'stage': stage,
                         'status': 'converted' if stage == 'won' else existing.get('status')},
               now=at)
    if char:
        char.update(f"lead {lead_id} -> {stage}", tool='update_crm')
    result = {'action': 'stage_changed', 'lead': lead_id, 'from': existing.get('stage'),
              'stage': stage, 'handoff': None, 'handoff_reason': None,
              'calendar': None}

    if stage == 'meeting':
        booked = schedule_meeting(lead_id, _text(data.get('when') or data.get('scheduled_at'), 60),
                                  _text(data.get('timezone') or data.get('tz'), 60),
                                  _text(data.get('needs'), 200), now=at)
        result.update(booked)
    elif stage == 'won':
        email = _text(existing.get('email'), 200)
        try:
            result['handoff'] = handoff.hand_off(
                'Sales', 'Marketing', 'lead_converted', f'lead:{lead_id}',
                {'name': _text(existing.get('name'), 120) or email, 'email': email,
                 'score': existing.get('score') or QUALIFY_MIN_SCORE,
                 'plan': _text(existing.get('plan'), 40) or 'free',
                 'channel': _text(existing.get('source'), 40) or 'direct'},
                now=at,
            )
        except (ValueError, handoff.UnknownHandoff) as err:
            result['handoff_reason'] = f'handoff tidak ditulis: {err}'
            log.warning('sales: %s', result['handoff_reason'])
    log.info('sales: lead %s %s -> %s', lead_id, existing.get('stage'), stage)
    return result


def handle_trigger(trigger: str, payload: object = None, char: Any = None, *,
                   now: float | None = None, transport=None) -> dict:
    """Entry point `webhook_server/triggers.py` calls for the three Sales triggers."""
    name = str(trigger or '').strip()
    if name in ('new_lead', 'form_submit'):
        return handle_new_lead(payload, trigger=name, char=char, now=now, transport=transport)
    if name == 'deal_stage_change':
        return handle_deal_stage(payload, char=char, now=now)
    return {'action': 'ignored', 'reason': f'{trigger} bukan trigger Sales'}
