"""orchestrator.py - the Orchestrator's two jobs: route, and carry work on.

AGENTS.md §? says the Orchestrator does not work; it routes, and it owns
`delegate` / `monitor_agents` / `escalate_to_human`. This module is that half:

- `build_orchestrator_graph()` returns a small deterministic graph: a node per
  role plus one `Orchestrator` node. `invoke()` runs the routed node, then follows
  whatever handoff that node left, until nothing is pending.
- `run_orchestrator(trigger, data)` is the entry a caller uses when it has a
  trigger, not a role.
- `escalate_to_human(payload)` is the Orchestrator node: it records a decision
  nobody can make on its own, and never raises an approval card from inside a
  trigger (that would block a worker thread for the whole timeout).

Why not LangGraph: it is not a dependency of this fork, and the graph here is a
short walk over a dict - four hops at most, no state machine, no checkpointer. A
library would add a dependency and hide the rule that matters (only handoffs in
AGENT-HANDOFFS.md §3 exist).

The graph follows a handoff by *taking* it: one handoff, one recipient
(AGENT-HANDOFFS.md §5.1). A node whose agent is not built yet reports `skipped`
and the chain stops there - honest, and nothing is invented on its behalf. W9
fills in the money side: PaymentAgent, RevenueTracker, SecOps and
EpisodeScheduler are nodes now, so a chargeback and a takedown are two visible
hops instead of a note in the code.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from hermes_bridge import handoff

log = logging.getLogger(__name__)

#: A chain longer than this is a loop, not a workflow
MAX_HOPS = 4

#: What the Orchestrator node says when it hands something to a human
HUMAN_OPTIONS = ('Tinjau sekarang', 'Tunda 1 jam', 'Tutup tanpa tindakan')

Node = Callable[[dict], dict | None]


def escalate_to_human(payload: object, now: float | None = None) -> dict:
    """Record that a human has to decide; no card, no blocking.

    The record lands in SharedContext as `escalation:<key>` so a person (or the
    `handoff_check` job) can find it later, and a Support ticket stays
    `escalated` with `assignee='Orchestrator'` in the meantime.
    """
    from . import store

    data = payload if isinstance(payload, dict) else {}
    subject = str(data.get('subject') or data.get('ticket') or 'umum')[:80]
    at = time.time() if now is None else float(now)
    key = f"escalation:{handoff._slug(subject)}"
    record = {
        'subject': subject,
        'reason': str(data.get('reason') or 'ticket_unresolved')[:120],
        'summary': str(data.get('summary') or data.get('message') or '')[:400],
        'ticket': data.get('ticket'),
        'at': at,
        'options': list(HUMAN_OPTIONS),
    }
    try:
        store.context().set(key, record, 'Orchestrator')
    except Exception as err:  # noqa: BLE001 - an escalation that cannot be stored is still logged
        log.warning('orchestrator: eskalasi %s tidak tersimpan: %s', subject, err)
    log.warning('orchestrator: %s perlu keputusan manusia (%s)', subject, record['reason'])
    return {'escalated': True, 'subject': subject, 'key': key, 'ticket': record['ticket']}


def _default_handler(role: str) -> Node | None:
    """The agent that actually does `role`'s work, when it exists (W3-W5)."""
    if role == 'Support':
        from .support import handle_trigger

        return lambda data: handle_trigger(data)
    if role == 'UserReportAgent':
        from .user_report import handle_trigger

        return lambda data: handle_trigger(data)
    if role == 'PaymentAgent':
        from .finance import handle_trigger

        return lambda data: handle_trigger(data)
    if role == 'RevenueTracker':
        from .finance import record_transaction

        return record_transaction
    if role == 'SecOps':
        from .sec_ops import flag_account_node

        return flag_account_node
    if role == 'EpisodeScheduler':
        from .dmca import cancel_from_takedown

        return cancel_from_takedown
    if role == 'Orchestrator':
        return lambda data: escalate_to_human(data)
    return None


class OrchestratorGraph:
    """A dict of role nodes plus the rule that follows handoffs between them."""

    def __init__(self, nodes: dict[str, Node], take: Callable[[str, str], dict | None] | None = None,
                 context=None) -> None:
        self.nodes = nodes
        self._take = take or (lambda key, owner: handoff.take(key, owner, context=context))
        self._context = context

    @property
    def node_names(self) -> list[str]:
        return sorted(self.nodes)

    def _next(self, role: str) -> dict | None:
        """The oldest handoff `role` left, already taken for its recipient."""
        left = handoff.pending_from(role, context=self._context)
        if not left:
            return None
        key = min(left, key=lambda k: float((left[k] or {}).get('created_at') or 0))
        envelope = self._take(key, str((left[key] or {}).get('to') or ''))
        if envelope is None:
            return None
        return {'key': key, **envelope}

    def _run(self, role: str, data: dict) -> dict | None:
        node = self.nodes.get(role)
        if node is None:
            log.info('orchestrator: %s belum punya agent - berhenti di sini', role)
            return {'skipped': f'{role} belum punya agent'}
        return node(data)

    def follow_chain(self, role: str, now: float | None = None) -> list[dict]:
        """Follow the handoffs `role` already left; used right after its work ran."""
        hops: list[dict] = []
        current = role
        for _ in range(MAX_HOPS):
            nxt = self._next(current)
            if nxt is None:
                break
            payload = {'handoff_key': nxt['key'], 'reason': nxt.get('reason'),
                       'subject': nxt.get('subject'), 'expects': nxt.get('expects'),
                       'from': nxt.get('from'), **(nxt.get('payload') or {})}
            result = self._run(str(nxt.get('to') or ''), payload)
            hops.append({'from': nxt.get('from'), 'to': nxt.get('to'),
                         'reason': nxt.get('reason'), 'key': nxt['key'], 'work': result})
            current = str(nxt.get('to') or '')
            if isinstance(result, dict) and result.get('skipped'):
                break
        else:
            log.warning('orchestrator: rantai dari %s melewati %d hop - dihentikan', role, MAX_HOPS)
        return hops

    def invoke(self, role: str, data: dict | None = None, now: float | None = None) -> dict:
        """Run `role`'s node, then carry on through any handoffs it leaves."""
        payload = data if isinstance(data, dict) else {}
        work = self._run(role, payload)
        hops = self.follow_chain(role, now=now)
        return {'route': role, 'visited': [role] + [hop['to'] for hop in hops],
                'work': work, 'chain': hops}


def build_orchestrator_graph(handlers: dict[str, Node] | None = None, context=None) -> OrchestratorGraph:
    """One node per role: the ones with an agent, plus the Orchestrator sink.

    `handlers` lets a test (or a future W6 agent) provide nodes without changing
    this module; everything else falls back to `_default_handler`, and a role
    with no agent is a `skipped` node rather than a silent success.
    """
    from webhook_server.triggers import TRIGGER_ROLES

    # Handoff recipients are nodes too: W9's DMCA -> EpisodeScheduler and
    # PaymentAgent -> RevenueTracker/SecOps only appear in the graph because of
    # the transition table, and a recipient without an agent stays `skipped`.
    recipients = {to_role for (_, to_role, _) in handoff.HANDOFF_TABLE}
    nodes: dict[str, Node] = {}
    for role in sorted(set(TRIGGER_ROLES.values()) | recipients | {'Orchestrator'}):
        node = (handlers or {}).get(role) or _default_handler(role)
        if node is not None:
            nodes[role] = node
    for role, node in (handlers or {}).items():
        nodes.setdefault(role, node)
    return OrchestratorGraph(nodes, context=context)


def run_orchestrator(trigger: str, data: object = None, source: str = 'webhook',
                     handlers: dict[str, Node] | None = None) -> dict:
    """`run_orchestrator(trigger_type, data)` from AGENTS.md, headless-safe.

    The trigger is validated by `triggers.route_trigger`, so an unknown type is
    an error here too (a 400 at the route, a log line from a job). Character
    drawing stays in `triggers.run_trigger`; this function is the routing brain.
    """
    from webhook_server.triggers import route_trigger

    role = route_trigger(trigger)
    graph = build_orchestrator_graph(handlers)
    result = graph.invoke(role, data if isinstance(data, dict) else {})
    log.info('orchestrator: trigger=%s source=%s route=%s hops=%d',
             trigger, source, role, len(result['chain']))
    return {'trigger': trigger, 'source': source, **result}


def follow_handoffs(role: str, handlers: dict[str, Node] | None = None) -> list[dict]:
    """What `triggers.run_trigger` calls after an agent's own work finished."""
    try:
        return build_orchestrator_graph(handlers).follow_chain(role)
    except Exception as err:  # noqa: BLE001 - a broken chain must not fail the trigger
        log.warning('orchestrator: rantai %s gagal: %s', role, err)
        return []


def graph_summary() -> dict[str, Any]:
    """`{nodes, hops}` for `/health` and the orchestrator card."""
    graph = build_orchestrator_graph()
    pending = handoff.pending()
    return {'nodes': graph.node_names, 'max_hops': MAX_HOPS,
            'handoffs': {'pending': len(pending), 'expired': len(handoff.expired())}}
