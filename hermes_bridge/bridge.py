"""bridge.py - the seven functions a business agent calls.

Each one turns into the event the office already understands
(`agent_spawned`, `agent_working`, ... - docs/hermes-office/API-REFERENCE.md
§3), so no new event type exists and the office's reducer needs no branch for
the business team. The role string is the only thing that decides where the
character sits: it must be a key of `BUSINESS_AGENT_CONFIGS`
(src/types.ts). A misspelled role draws nothing, with no error anywhere - so
check the spelling first when a character does not appear.

Nothing here reads an API key: the office token comes from `OFFICE_TOKEN` in
the environment (the contents of `~/.agent-office/auth-token`). When it is
missing the send is retried, then kept in the DLQ with that error as its reason
(`python -m hermes_bridge.smoke --all` reports how many are waiting).

Nothing happens at import time: `init()` opens the dead-letter queue when the
first event is sent (or when a script asks for it), and `OFFICE_URL` /
`SIDECAR_URL` are read on every call. So an entry point may load `.env`
(`hermes_bridge.env.load_env()`) or set a variable after importing this module
and the next event uses it - there is no import-order trap.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Iterable

import httpx

from .queue import DeadLetterQueue

log = logging.getLogger(__name__)

DEFAULT_OFFICE_URL = 'http://127.0.0.1:3334'
DEFAULT_SIDECAR_URL = 'http://127.0.0.1:8765'

POST_TIMEOUT_S = 5.0
RETRY_DELAYS_S = (0.5, 1.0, 2.0)
APPROVAL_POLL_S = 3.0

MAX_NAME = 80
MAX_TASK = 200
MAX_STATUS = 200
MAX_TOOL = 64


class BridgeError(RuntimeError):
    """The office cannot be reached, or the configuration cannot work."""


def office_url() -> str:
    """`OFFICE_URL` as it is now - not as it was when this module was imported."""
    return (os.environ.get('OFFICE_URL') or DEFAULT_OFFICE_URL).rstrip('/')


def sidecar_url() -> str:
    """`SIDECAR_URL` as it is now; `server/biz-events.js` reads the same name."""
    return (os.environ.get('SIDECAR_URL') or DEFAULT_SIDECAR_URL).rstrip('/')


def __getattr__(name: str) -> str:
    """Keep `bridge.OFFICE_URL` working, resolved live instead of at import."""
    if name == 'OFFICE_URL':
        return office_url()
    if name == 'SIDECAR_URL':
        return sidecar_url()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def _token() -> str:
    token = os.environ.get('OFFICE_TOKEN', '').strip()
    if not token:
        raise BridgeError(
            'OFFICE_TOKEN is empty. Put the office token in the environment:\n'
            '  export OFFICE_TOKEN=$(cat "${AGENT_OFFICE_HOME:-$HOME/.agent-office}/auth-token")'
        )
    return token


def _post_once(path: str, payload: dict) -> None:
    """One attempt, no retry, no queue. Raises on anything but a 2xx."""
    res = httpx.post(
        f'{office_url()}{path}',
        json=payload,
        headers={'Authorization': f'Bearer {_token()}'},
        timeout=POST_TIMEOUT_S,
    )
    res.raise_for_status()


def _send_event_once(payload: dict) -> None:
    _post_once('/event', payload)


def _send_metrics_once(delta: dict) -> None:
    _post_once('/biz-metrics', {'delta': delta})


_dlq: DeadLetterQueue | None = None
_dlq_lock = threading.Lock()


def init(flush: bool = False) -> DeadLetterQueue:
    """Open the dead-letter queue from the environment as it is now.

    Safe to call more than once: the queue is created once and reused, so a
    process that calls `init()` on startup and an agent that never calls it end
    up with the same queue.

    Args:
        flush: replay what earlier runs left in `dlq.db` right away (the first
            event does this anyway, throttled to once every 30 seconds)

    Returns:
        The queue this module is using.
    """
    global _dlq
    with _dlq_lock:
        if _dlq is None:
            _dlq = DeadLetterQueue(post_event=_send_event_once, post_metrics=_send_metrics_once)
        queue = _dlq
    if flush:
        queue.flush(force=True)
    return queue


def _queue() -> DeadLetterQueue:
    """The queue, opened on first use so importing this module does no I/O."""
    return _dlq if _dlq is not None else init()


def _post(payload: dict) -> None:
    """Send an event, retrying a few times, then keep it in the DLQ.

    Private on purpose (Rev 3.1 #3): an agent calls the named functions below so
    the shape of an event stays in one file.
    """
    _queue().flush()  # drain earlier failures first; throttled inside the queue
    last: Exception | None = None
    for delay in RETRY_DELAYS_S:
        try:
            _send_event_once(payload)
            return
        except Exception as err:  # noqa: BLE001 - every failure is worth a retry
            last = err
            time.sleep(delay)
    log.warning('bridge: could not send %s (%s); keeping it in the DLQ', payload.get('type'), last)
    _queue().push(payload, str(last or 'send failed'))


def _clean(value: str, limit: int) -> str:
    return ' '.join(str(value).split())[:limit]


def agent_start(name: str, role: str, task: str) -> str:
    """Put a character at `role`'s desk and return the id used from now on.

    Args:
        name: what the bubble and inspector show ("Scraper", "Quality Checker")
        role: the exact key in `BUSINESS_AGENT_CONFIGS` (src/types.ts)
        task: one line for the first bubble

    Returns:
        `"{role.lower()}-{uuid6}"`, e.g. `scraper-a1b2c3`
    """
    agent_id = f'{_clean(role, 40).lower()}-{uuid.uuid4().hex[:6]}'
    # `agent_spawned` is the one event whose fields sit under `agent`; the
    # server derives the office id from it (server/index.js resolveAgentId).
    _post({
        'type': 'agent_spawned',
        'agent': {
            'id': agent_id,
            'name': _clean(name or role, MAX_NAME) or role,
            'role': role,
            'task': _clean(task, MAX_TASK),
        },
    })
    return agent_id


def agent_update(agent_id: str, status: str, tool: str | None = None) -> None:
    """Change the bubble; call once per tool call, not per log line."""
    payload = {'type': 'agent_working', 'agentId': agent_id, 'status': _clean(status, MAX_STATUS)}
    if tool:
        payload['tool'] = _clean(tool, MAX_TOOL)
    _post(payload)


def agent_waiting(agent_id: str, message: str, options: Iterable[str]) -> None:
    """Show the permission card. Always call this *before* `wait_for_approval`.

    Args:
        agent_id: the id `agent_start` returned
        message: what the person is deciding
        options: the button labels; the answer comes back as one of these
    """
    labels = [_clean(o, 80) for o in options if str(o).strip()][:6]
    if not labels:
        raise ValueError('agent_waiting needs at least one option label')
    # `agent_waiting` carries the question *and* its buttons, so the office can
    # draw the card (src/bizApproval.ts). The answer comes back through the
    # sidecar, which `wait_for_approval` polls.
    _post({
        'type': 'agent_waiting',
        'agentId': agent_id,
        'message': _clean(message, MAX_STATUS),
        'options': labels,
    })


def wait_for_approval(agent_id: str, timeout: float = 300) -> str:
    """Poll the sidecar until a button is pressed, or `timeout` passes.

    Returns:
        The label exactly as the button showed it, or `"timeout"` - a timeout is
        not an exception, because the agent decides what it means.
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            res = httpx.get(f'{sidecar_url()}/approval/{agent_id}', timeout=POST_TIMEOUT_S)
            res.raise_for_status()
            decision = (res.json() or {}).get('decision')
            if decision:
                _approval_done(agent_id)
                return str(decision)
        except Exception as err:  # noqa: BLE001 - a sleeping sidecar means "not yet"
            log.debug('bridge: approval poll failed: %s', err)
        if time.monotonic() >= deadline:
            _approval_done(agent_id)
            return 'timeout'
        time.sleep(min(APPROVAL_POLL_S, max(0.0, deadline - time.monotonic())))


def _approval_done(agent_id: str) -> None:
    """Take the card off the office: the wait is over, answered or timed out."""
    _post({'type': 'agent_approval_done', 'agentId': agent_id})


def agent_done(agent_id: str, result: str = 'done') -> None:
    """Thumbs up, then walk out. Once per `agent_start`."""
    _post({'type': 'agent_completed', 'agentId': agent_id, 'result': _clean(result, MAX_STATUS)})


def agent_error(agent_id: str, error: str, retrying: bool = False) -> None:
    """A red bubble and a head shake; `retrying=True` keeps the character seated."""
    _post({
        'type': 'agent_working',
        'agentId': agent_id,
        'status': _clean(error, MAX_STATUS),
        'failed': True,
    })
    if not retrying:
        agent_done(agent_id, _clean(f'berhenti: {error}', MAX_STATUS))


def get_biz_metrics(timeout: float = 3.0) -> dict:
    """Read the office's own numbers (`GET /biz-metrics`), for `/biz`.

    The counters live in the office DB (`chat.db`), written by
    `server/biz-events.js`; the sidecar has no business opening that file, so
    it asks the office over the same localhost door. Raises `BridgeError` when
    the office is not answering: `/biz` must say that, not invent a report.
    """
    headers = {}
    token = os.environ.get('OFFICE_TOKEN', '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        res = httpx.get(f'{office_url()}/biz-metrics', headers=headers, timeout=timeout)
        res.raise_for_status()
        body = res.json()
    except Exception as err:  # noqa: BLE001 - the caller turns this into a chat line
        raise BridgeError(f'GET /biz-metrics gagal: {err}') from err
    if not isinstance(body, dict):
        raise BridgeError('GET /biz-metrics menjawab bukan object')
    return body


def update_biz_metrics(delta: dict) -> None:
    """Report counters (added) and gauges (replaced) - never through `/event`.

    Args:
        delta: `{key: int}`, e.g. `{"tickets_resolved": 1}`. Gauge keys
            (`tickets_pending`, `sla_avg_response_min`, `sla_breach_count`)
            carry the current value, not an increment.
    """
    if not isinstance(delta, dict) or not delta:
        raise ValueError('update_biz_metrics needs a non-empty dict of key: int')
    try:
        _send_metrics_once(delta)
    except Exception as err:  # noqa: BLE001 - metrics must not fail an agent's work
        log.warning('bridge: metrics not sent (%s); queued', err)
        _queue().push({'__type': 'biz_metrics', 'delta': delta}, str(err))


def flush_queue() -> int:
    """Replay everything the office refused so far; returns how many landed."""
    return _queue().flush(force=True)


def pending_events() -> int:
    """How many events are still waiting in the DLQ."""
    return _queue().pending()
