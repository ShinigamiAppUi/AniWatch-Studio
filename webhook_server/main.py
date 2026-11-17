"""main.py - the sidecar's approval endpoints.

This is the part of the sidecar W2 needs: `bridge.wait_for_approval()` polls
`GET /approval/{agent_id}`, and `server/biz-events.js` forwards a card's button
to `POST /approval-callback`. The webhook routes (`/webhook`,
`/webhook/payment`, the trigger fan-out) are W3 (PLAN.md) and are not here yet.

Run: `uvicorn webhook_server.main:app --host 127.0.0.1 --port 8765`
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .approval import store

app = FastAPI(title='Hermes Office sidecar', version='0.2.0')


class ApprovalCallback(BaseModel):
    agentId: str
    decision: str


@app.get('/health')
def health() -> dict:
    """Does not touch the office; the doctor and the bridge use it only to see if we are up."""
    return {'status': 'ok', 'pending_approvals': store().pending()}


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
