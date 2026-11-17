"""webhook_server - the FastAPI sidecar (port 8765).

W2 ships the piece the office already needs: the approval mailbox a permission
card answers into (`approval.py`). The webhook routes themselves are the next
work package (PLAN.md W3); `main.py` and the secret checks land there.
"""

from .approval import ApprovalStore, store

__all__ = ['ApprovalStore', 'store']
