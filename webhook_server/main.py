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
  `order_id + status_code + gross_amount + MIDTRANS_SERVER_KEY` and recorded once
  per notification (`webhook_server/payments.py`).
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
    """Midtrans notification: verify the signature, then record it once."""
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
    if fresh and status == 'chargeback':
        _queue(asyncio.to_thread(triggers.run_trigger, 'chargeback_received', payload, 'midtrans'))
    return {'status': 'queued'}
