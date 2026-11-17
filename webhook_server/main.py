"""main.py - the FastAPI sidecar: the approval mailbox, the two doors in, and the scheduler.

W2 put the approval mailbox here (`bridge.wait_for_approval()` polls
`GET /approval/{agent_id}`, `server/biz-events.js` posts a card's button to
`/approval-callback`). W4 adds the way business work arrives and the periodic
jobs:

- `POST /webhook` - `X-Webhook-Secret`, then one of `SUPPORTED_TRIGGERS`
  (`webhook_server/triggers.py`). Answered `{"status":"queued"}` as soon as the
  trigger is handed to a worker thread, which draws the Orchestrator and then the
  role the trigger belongs to. An unmapped type is a 400, never a fallback.
- `POST /webhook/payment` - Midtrans notification, verified with SHA-512 over
  `order_id + status_code + gross_amount + MIDTRANS_SERVER_KEY`, recorded once per
  notification (`webhook_server/payments.py`) and then handed to PaymentAgent
  (`hermes_agents/finance.py`, W9), whose handoff to RevenueTracker or SecOps is
  followed in the same call. A `refund_request` blocks on a card, so only that
  one is raised in a worker thread.
- `POST /command` (W7) - the chat's business slash commands, relayed by
  `server/biz-events.js`. Loopback-only, like `/approval-callback`.
- `GET /health` - also lists the scheduler's jobs, and the ones waiting on W5-W9.

Both secrets are required: startup raises `MissingSecrets` rather than run a
payment endpoint that cannot verify a signature (SECURITY.md §5). `.env` at the
repository root is read here, once, before anything looks at a variable
(`hermes_bridge.env.load_env()`, ENV-VARS.md §5); a variable already in the
environment wins.

Run: `uvicorn webhook_server.main:app --host 127.0.0.1 --port 8765`
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from hermes_bridge.env import load_env

from . import payments, triggers
from .approval import store

# One loader for the sidecar: the file first, the real environment wins
load_env()

log = logging.getLogger(__name__)

#: Background triggers in flight, kept referenced until done (a bare
#: `create_task` result may be garbage-collected mid-flight)
_running: set[asyncio.Task] = set()


class ApprovalCallback(BaseModel):
    agentId: str
    decision: str


class WebhookBody(BaseModel):
    type: str
    data: object | None = None
    source: str | None = None


class CommandBody(BaseModel):
    text: str


def _configure_logging() -> None:
    """`LOG_LEVEL` for the sidecar's own lines (ENV-VARS.md §2).

    uvicorn configures only its own loggers, so without this the scheduler's
    "scheduler jalan" line, every `trigger=<type> source=<source>` line and each
    job's duration never reach stdout - and SCHEDULER.md §5 promises all three.
    """
    level = (os.environ.get('LOG_LEVEL') or 'INFO').strip().upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format='%(levelname)s %(name)s: %(message)s',
    )
    # APScheduler announces every job twice at INFO; the scheduler logs its own
    # "scheduler jalan" line, so its chatter only hides the sidecar's own lines
    logging.getLogger('apscheduler').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Fail fast on a missing secret, then start the scheduler (never at import)."""
    triggers.require_secrets()
    _configure_logging()
    from .scheduler import shutdown_scheduler, start_scheduler

    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(title='Hermes Office sidecar', version='0.5.0', lifespan=lifespan)


def _business_db():
    """The business DB (`hermes.db`), initialised once per call (idempotent DDL)."""
    from hermes_bridge import db as bdb

    bdb.init_db()
    return bdb.connect()


def _queue(coroutine) -> None:
    """Run `coroutine` off the event loop without blocking the response."""
    task = asyncio.create_task(coroutine)
    _running.add(task)
    task.add_done_callback(_running.discard)


@app.get('/health')
def health() -> dict:
    """Liveness, the approval mailbox, the scheduler and the mail channel.

    `pending_approvals` counts *decisions waiting to be collected*, not cards on
    screen: the sidecar only hears about a card when its button is pressed.

    `mail` is the outbound reply channel: whether SMTP is configured, and the
    last attempt (sent or failed) with its reason. That is the fastest answer to
    "why did Support not answer that ticket".
    """
    from .scheduler import pending_jobs, registered_jobs

    from hermes_agents.mailer import status as mail_status

    return {
        'status': 'ok',
        'pending_approvals': store().pending(),
        'jobs': registered_jobs(),
        'pending_jobs': pending_jobs(),
        'mail': mail_status(),
    }


@app.get('/approval/{agent_id}')
def read_approval(agent_id: str) -> dict:
    """One-shot read: the decision the person made, then `None` ever after."""
    return {'decision': store().pop_decision(agent_id)}


@app.post('/approval-callback')
def approval_callback(body: ApprovalCallback) -> dict:
    """Called by `server/biz-events.js` when a permission card's button is pressed."""
    try:
        store().set_decision(body.agentId, body.decision)
    except ValueError:
        raise HTTPException(status_code=400, detail='agentId dan decision wajib diisi')
    return {'ok': True}


def _request_approval(item_id: str) -> None:
    """Raise one premium item's card; runs in a worker thread, never inline."""
    from hermes_agents import premium

    premium.request_approval(item_id)


def _process_payment(payload: dict) -> dict:
    """PaymentAgent's work for one verified notification, plus its handoff chain.

    `handle_payment_webhook` returns a value for every status, so a notification
    that changes nothing (an unknown status, a missing order id) is a log line
    and a `reason` rather than an exception in a worker thread.
    """
    from hermes_agents import finance

    result = finance.handle_payment_webhook(payload)
    if result.get('action') == 'refund_requested' and result.get('order_id'):
        result['approval'] = finance.request_refund_approval(str(result['order_id']))
    try:
        from hermes_agents.orchestrator import follow_handoffs

        result['chain'] = follow_handoffs('PaymentAgent')
    except Exception as err:  # noqa: BLE001 - the payment is recorded either way
        log.warning('payment: rantai handoff PaymentAgent gagal: %s', err)
    return result


@app.post('/command')
async def command(body: CommandBody) -> dict:
    """The chat's business slash commands (`/design`, `/pending-items`, `/approve`).

    Loopback-only and secret-free for the same reason `/approval-callback` is
    (SECURITY.md §4.2): the caller is `server/biz-events.js` on this machine, and
    the sidecar must never bind a non-loopback interface.

    `/design` answers at once; the card that follows blocks, so it is raised in a
    worker thread (`_request_approval`)."""
    from . import commands

    result = commands.handle_command(body.text)
    if result.get('approval'):
        _queue(asyncio.to_thread(_request_approval, str(result['approval'])))
    return {'handled': bool(result.get('handled')), 'ok': bool(result.get('ok')),
            'reply': str(result.get('reply') or '')}


@app.post('/webhook')
async def webhook(
    body: WebhookBody,
    x_webhook_secret: str | None = Header(default=None),
) -> dict:
    """Accept one business trigger. 403 wrong secret, 400 unknown type, else queued."""
    expected = triggers.webhook_secret()
    if not expected:
        # The sidecar refuses to start without it; reaching here means the
        # environment changed under a running process. Refuse, never accept.
        raise HTTPException(status_code=503, detail='WEBHOOK_SECRET belum diset')
    if not secrets.compare_digest(x_webhook_secret or '', expected):
        raise HTTPException(status_code=403, detail='invalid secret')
    try:
        triggers.route_trigger(body.type)
    except triggers.UnknownTrigger as err:
        raise HTTPException(status_code=400, detail=str(err))

    _queue(asyncio.to_thread(triggers.run_trigger, body.type, body.data, body.source or 'webhook'))
    return {'status': 'queued'}


@app.post('/webhook/payment')
async def webhook_payment(
    request: Request,
    x_signature_key: str | None = Header(default=None),
) -> dict:
    """Midtrans notification: verify the signature, record it once, then act on it.

    The answer stays `{"status":"queued"}`, with the `action` PaymentAgent took,
    so the caller never waits for a refund card: that one is queued.
    """
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail='body harus JSON')
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='body harus object JSON')
    if not payments.verify(payload, x_signature_key):
        raise HTTPException(status_code=403, detail='invalid signature')

    con = _business_db()
    try:
        fresh = payments.record(con, payload)
    finally:
        con.close()

    status = payments.status_of(payload)
    log.info(
        'payment order=%s status=%s baru=%s',
        payload.get('order_id'), status, fresh,
    )
    if not fresh:
        # Midtrans retries; the first notification already did the work
        return {'status': 'queued', 'action': 'duplicate'}
    if payments.wants_card(payload):
        _queue(asyncio.to_thread(_process_payment, payload))
        return {'status': 'queued', 'action': 'refund_requested'}
    work = await asyncio.to_thread(_process_payment, payload)
    return {'status': 'queued', 'action': work.get('action')}
