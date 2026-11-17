"""webhook_server - the FastAPI sidecar (port 8765).

W2 shipped the approval mailbox a permission card answers into
(`approval.py`). W4 adds the two doors business work arrives through
(`triggers.py` for `POST /webhook`, `payments.py` for the Midtrans
notification), the four periodic jobs whose work exists (`jobs.py`) and the
APScheduler wiring that runs them from the app's lifespan (`scheduler.py`).

The seven jobs still waiting on an agent from W5-W9 are listed in
`scheduler.PENDING_JOBS` instead of being registered as no-ops.
"""

from .approval import ApprovalStore, store

__all__ = ['ApprovalStore', 'store']
