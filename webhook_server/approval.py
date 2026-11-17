"""approval.py - the one-shot mailbox between a permission card and its agent.

The card is drawn from `agent_waiting`; its button arrives at the sidecar
(`POST /approval-callback`) and `bridge.wait_for_approval()` polls
`GET /approval/{agent_id}`. A decision is handed out exactly once (`pop`), so a
retry after a crash cannot approve a refund twice.

Stays in memory on purpose: a decision that outlives a sidecar restart is a
decision nobody is waiting for. Entries older than `TTL_S` are dropped, so a
card answered hours later cannot wake a finished agent.
"""

from __future__ import annotations

import threading
import time

TTL_S = 6 * 3600.0
MAX_ENTRIES = 1000


class ApprovalStore:
    """Thread-safe `agent_id -> decision` mailbox with a TTL."""

    def __init__(self, ttl_s: float = TTL_S) -> None:
        self._ttl = float(ttl_s)
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, float]] = {}

    def _sweep(self, now: float) -> None:
        stale = [k for k, (_, ts) in self._entries.items() if now - ts > self._ttl]
        for key in stale:
            self._entries.pop(key, None)

    def set_decision(self, agent_id: str, decision: str) -> None:
        """Record what the person chose; a newer answer replaces an older one."""
        agent_id = (agent_id or '').strip()
        decision = (decision or '').strip()[:80]
        if not agent_id or not decision:
            raise ValueError('agent_id and decision are both required')
        now = time.time()
        with self._lock:
            self._sweep(now)
            if len(self._entries) >= MAX_ENTRIES:
                oldest = min(self._entries, key=lambda k: self._entries[k][1])
                self._entries.pop(oldest, None)
            self._entries[agent_id] = (decision, now)

    def pop_decision(self, agent_id: str) -> str | None:
        """Take the decision, or None while the card is still unanswered."""
        now = time.time()
        with self._lock:
            self._sweep(now)
            entry = self._entries.pop((agent_id or '').strip(), None)
        return entry[0] if entry else None

    def pending(self) -> int:
        """How many cards are waiting for an answer."""
        with self._lock:
            self._sweep(time.time())
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_store = ApprovalStore()


def store() -> ApprovalStore:
    """The process-wide mailbox."""
    return _store
