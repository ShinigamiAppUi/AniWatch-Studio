"""triggers.py - the one door a business trigger comes in through (W4).

`POST /webhook` (webhook_server/main.py) checks the secret and hands the body
here. Two things live in this file:

1. `TRIGGER_ROLES` - which character a trigger belongs to. It is an explicit
   table, not a lookup with a fallback: a trigger nobody mapped is a 400, not
   "send it to Ops" (PLAN.md W4: "tidak ada yang jatuh ke fallback `ops`").
2. `run_trigger` - the office side: Orchestrator first, then the routed role, so
   every trigger is visible as work being coordinated
   (docs/hermes-office/API-REFERENCE.md §4, fix Rev 3 #4).

What a trigger does: the business work, through the agents that exist so far.
`support_ticket`/`new_email` go to `hermes_agents.support` (triage -> KB -> reply
or escalate) and `user_report` to `hermes_agents.user_report`. The rest have no
tool yet (W6-W9) and only draw the two characters, which is honest: the trigger
was accepted, the work is not built. Work is called from here, never from the
webhook route.

Headless by design (ADR-3): without `OFFICE_TOKEN` nothing is sent to the
office, but the *work still runs* - a ticket must not need an office window to
be recorded.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

#: `type` in a `POST /webhook` body -> the role key in `BUSINESS_AGENT_CONFIGS`
#: (src/types.ts). All 13 come from API-REFERENCE.md §4; `escalate` is internal
#: to `handoff_check` and is deliberately *not* accepted over the webhook.
TRIGGER_ROLES: dict[str, str] = {
    'new_lead': 'Sales',
    'form_submit': 'Sales',
    'deal_stage_change': 'Sales',
    'analytics_ready': 'Analytics',
    'content_schedule': 'SocialMedia',
    'support_ticket': 'Support',
    'new_email': 'Support',
    'episode_released': 'Notifier',
    'weekly_analytics': 'Marketing',
    'announce_episode': 'SocialMedia',
    'retention_check': 'Retention',
    'chargeback_received': 'PaymentAgent',
    'user_report': 'UserReportAgent',
}

#: The `type` values `/webhook` accepts, in the order API-REFERENCE.md lists them
SUPPORTED_TRIGGERS = tuple(TRIGGER_ROLES)

#: How much of a trigger's `data` is allowed into a bubble or a log line
MAX_SUMMARY = 120


class UnknownTrigger(ValueError):
    """`type` is not in `SUPPORTED_TRIGGERS`; the route turns this into a 400."""


class MissingSecrets(RuntimeError):
    """A required sidecar secret is unset, so the sidecar must not start."""


def route_trigger(trigger: str) -> str:
    """The role a trigger belongs to.

    Raises:
        UnknownTrigger: the type is not one of the 13. Never guessed, never
            defaulted - a typo must reach the caller as a 400, not as an Ops
            character doing the wrong work.
    """
    role = TRIGGER_ROLES.get(str(trigger or '').strip())
    if role is None:
        raise UnknownTrigger(
            f'trigger tidak dikenal: {trigger!r} (yang sah: {", ".join(SUPPORTED_TRIGGERS)})'
        )
    return role


def require_secrets(env: dict[str, str] | None = None) -> None:
    """Fail fast when a secret the sidecar's routes depend on is empty.

    Why at startup and not per request: `/webhook/payment` without
    `MIDTRANS_SERVER_KEY` cannot verify a signature, so it would accept a forged
    notification. A sidecar that refuses to start is the safe failure
    (SECURITY.md §5, ENV-VARS.md §1 rule 4).

    Raises:
        MissingSecrets: naming every missing variable, never its value.
    """
    source = os.environ if env is None else env
    missing = [
        name for name in ('WEBHOOK_SECRET', 'MIDTRANS_SERVER_KEY')
        if not str(source.get(name) or '').strip()
    ]
    if missing:
        raise MissingSecrets(
            'sidecar tidak bisa start: ' + ', '.join(missing) + ' kosong. Isi di .env '
            '(salin dari .env.example) - jangan pernah mengosongkan verifikasi '
            'signature (docs/hermes-office/SECURITY.md §5).'
        )


def webhook_secret() -> str:
    """`WEBHOOK_SECRET` as it is now (an empty value means "not configured")."""
    return str(os.environ.get('WEBHOOK_SECRET') or '').strip()


def summary(data: object, limit: int = MAX_SUMMARY) -> str:
    """One short line from a trigger's `data`, for a bubble and a log."""
    if isinstance(data, dict):
        for key in ('subject', 'title', 'name', 'email', 'id', 'episode_id'):
            value = data.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                return ' '.join(str(value).split())[:limit]
    try:
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(data)
    return ' '.join(text.split())[:limit]


def office_enabled() -> bool:
    """True when the office can be reached at all: the token is what it needs."""
    return bool(os.environ.get('OFFICE_TOKEN', '').strip())


class _RoleCharacter:
    """The role's office character, in the shape the agents expect (`update`, `ask`).

    `hermes_agents.support` and `user_report` are written against `base.Agent`,
    but here the character is already drawn by `run_trigger`; this adapter lets
the agent put its own progress in that bubble instead of opening a second one.
    """

    def __init__(self, agent_id: str) -> None:
        self.id = agent_id

    def update(self, status: str, tool: str | None = None) -> None:
        from hermes_bridge import bridge

        bridge.agent_update(self.id, status, tool=tool)

    def ask(self, message: str, options: list[str], timeout: float = 300.0) -> str:
        from hermes_bridge import bridge

        bridge.agent_waiting(self.id, message, options)
        return bridge.wait_for_approval(self.id, timeout=timeout)


def _support_work(payload: object, char=None) -> dict:
    from hermes_agents.support import handle_trigger

    return handle_trigger(payload, char=char)


def _report_work(payload: object, char=None) -> dict:
    from hermes_agents.user_report import handle_trigger

    return handle_trigger(payload, char=char)


#: trigger -> the agent work that exists. Everything else only draws characters.
AGENT_HANDLERS = {
    'support_ticket': _support_work,
    'new_email': _support_work,
    'user_report': _report_work,
}


def _run_work(trigger: str, data: object, char=None) -> dict | None:
    """Do the trigger's business work; None when no agent has the tool yet."""
    handler = AGENT_HANDLERS.get(trigger)
    if handler is None:
        return None
    try:
        return handler(data, char)
    except Exception as err:  # noqa: BLE001 - one bad trigger must not stop the sidecar
        log.exception('trigger=%s: kerja agent gagal: %s', trigger, err)
        return {'error': str(err)}


def run_trigger(trigger: str, data: object = None, source: str = 'webhook') -> dict:
    """Show one trigger in the office: Orchestrator, then the routed role.

    Never raises: it runs in a worker thread behind a request that has already
    answered `{"status":"queued"}`, so a failure here is a log line, not a 500
    for the caller.

    Args:
        trigger: one of `SUPPORTED_TRIGGERS`
        data: the trigger's payload, any JSON value (only a summary is used)
        source: where it came in from - `webhook`, `scheduler`, `chat`

    Returns:
        `{trigger, role, source, office, agents}` - `office` is False when the
        run was headless (no `OFFICE_TOKEN`), and `agents` holds the ids the
        office handed back.
    """
    try:
        role = route_trigger(trigger)
    except UnknownTrigger as err:
        log.warning('trigger=%s source=%s ditolak: %s', trigger, source, err)
        return {'trigger': trigger, 'role': None, 'source': source, 'office': False, 'agents': []}

    line = summary(data)
    log.info('trigger=%s source=%s role=%s %s', trigger, source, role, line)

    if not office_enabled():
        log.warning('trigger=%s: OFFICE_TOKEN kosong - kerja tetap jalan, tanpa karakter di kantor', trigger)
        work = _run_work(trigger, data, None)
        return {'trigger': trigger, 'role': role, 'source': source, 'office': False,
                'agents': [], 'work': work}

    agents: list[str] = []
    work: dict | None = None
    try:
        from hermes_bridge import bridge

        task = f'{trigger}: {line}' if line else trigger
        orchestrator = bridge.agent_start('Orchestrator', 'Orchestrator', task)
        agents.append(orchestrator)
        bridge.agent_update(orchestrator, f'route_trigger: {trigger} ({source})', tool='route_trigger')

        agent = bridge.agent_start(role, role, task)
        agents.append(agent)
        bridge.agent_update(agent, f'{trigger} dari {source}', tool='handle_trigger')
        # The tool that does the work lives in hermes_agents; until W6-W9 the
        # character is the whole record for the triggers that have none
        work = _run_work(trigger, data, _RoleCharacter(agent))
        bridge.agent_done(agent, _work_line(trigger, source, work))
        bridge.agent_done(orchestrator, f'{trigger} -> {role}')
    except Exception as err:  # noqa: BLE001 - a background trigger must not crash the sidecar
        log.warning('trigger=%s: kantor tidak bisa dihubungi: %s', trigger, err)
        if work is None:
            work = _run_work(trigger, data, None)
        return {'trigger': trigger, 'role': role, 'source': source, 'office': False,
                'agents': agents, 'work': work}

    return {'trigger': trigger, 'role': role, 'source': source, 'office': True,
            'agents': agents, 'work': work}


def _work_line(trigger: str, source: str, work: dict | None) -> str:
    """What the role's bubble says when it finishes: the outcome, not just receipt."""
    if not work:
        return f'{trigger} diterima ({source})'
    if work.get('error'):
        return f'{trigger} gagal: {str(work["error"])[:60]}'
    action = work.get('action')
    ref = work.get('ticket') or work.get('report')
    if action:
        return f'{action} {ref} ({trigger})' if ref else f'{action} ({trigger})'
    if work.get('breaches') is not None:
        return f'SLA: {work["breaches"]} tiket, {work.get("decision")}'
    return f'{trigger} diterima ({source})'
