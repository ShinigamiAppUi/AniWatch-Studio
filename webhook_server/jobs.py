"""jobs.py - what the scheduler actually runs (W4).

Split out of `scheduler.py` so a job can be called and checked without
APScheduler installed or started (SCHEDULER.md §6: "jalankan satu job manual").

Only the jobs whose work exists are here. The rest in SCHEDULER.md §2 call
agents that land in W6-W9, so they are listed as `PENDING_JOBS` in
`scheduler.py` and logged at startup instead of being registered as no-ops: a
job that pretends to run is worse than one that says it is not built yet.

`email_check` is still pending on purpose even though Support exists: it needs
the Gmail API, and a job that polls nothing would only fill the log.

Every function is safe to call twice and safe to call with no office running -
none of them sends an office event (SCHEDULER.md §1 rule 1: cleanup, sweep and
backup are the internal jobs that produce no character).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

#: Kept out of the DB so "24 jam" and "TTL 24 jam" in the docs stay in one place
CONTEXT_HOURS = 24.0
APPROVAL_SECONDS = 86400.0


def cleanup_shared_context(hours: float = CONTEXT_HOURS) -> int:
    """Drop SharedContext rows older than `hours`; returns how many went.

    The handoff protocol writes `handoff:*` into the same table, so a handoff
    nobody picked up disappears here too (AGENT-HANDOFFS.md §7).
    """
    from hermes_bridge.shared_context import SharedContext

    removed = SharedContext().cleanup_older_than(hours=hours)
    log.info('shared_context cleanup: %d baris lebih tua dari %.0f jam', removed, hours)
    return removed


def sweep_approvals(seconds: float = APPROVAL_SECONDS) -> int:
    """Throw away decisions nobody collected; returns how many.

    Not a replacement for the agent's own timeout: an agent that is still
    waiting has already given up by then (`wait_for_approval`), so a decision
    older than the TTL is a decision nobody is listening for.
    """
    from .approval import sweep_older_than

    removed = sweep_older_than(seconds=seconds)
    if removed:
        log.info('approval sweep: %d keputusan dibuang', removed)
    return removed


def sla_check(timeout: float = 300.0) -> dict:
    """One SLA round: Support bills every late ticket on ONE card (W5).

    The only scheduled job that shows a permission card (SCHEDULER.md §2). The
    order is fixed: the character is drawn by `Agent`, `check_sla_breaches`
    updates the bubble, raises the card, then calls `wait_for_approval` once.

    Returns `{breaches, decision, updated}`; a timeout changes nothing, so the
    next run bills the same tickets again.
    """
    from hermes_agents.base import Agent
    from hermes_agents.support import SupportAgent
    from hermes_bridge import db as bdb

    bdb.init_db()
    with Agent('Support', 'cek SLA') as char:
        return SupportAgent().check_sla_breaches(char=char, timeout=timeout)


def run_episode_scheduler() -> list[dict]:
    """One publish round for the embargo queue; returns what actually went live.

    One round, never a `while True` loop (Rev 3.1 #11): a loop inside an
    APScheduler job blocks the scheduler's thread and makes `max_instances`
    meaningless. Publishing is atomic (`WHERE status='scheduled'`), so a DMCA
    cancel that lands first wins.
    """
    from hermes_bridge import db as bdb
    from hermes_agents.episode_scheduler import publish_due_episodes

    bdb.init_db()
    con = bdb.connect()
    try:
        published = publish_due_episodes(con)
    finally:
        con.close()
    for row in published:
        log.info('episode_embargo: %s live', row.get('episode_id'))
    return published


def backup_databases(dest: Path | None = None, now: float | None = None) -> list[Path]:
    """Copy the three business SQLite files into a dated folder.

    Uses SQLite's own backup API, so a copy is consistent while another process
    is writing (DB-SCHEMA.md §13). A file that does not exist is skipped.
    """
    from hermes_bridge import db as bdb
    from hermes_bridge.queue import default_path as dlq_path
    from hermes_bridge.shared_context import default_path as shared_path

    stamp = time.strftime('%Y-%m-%d', time.localtime(time.time() if now is None else now))
    target = Path(dest) if dest else Path.home() / '.hermes-office' / 'backups' / stamp
    target.mkdir(mode=0o700, parents=True, exist_ok=True)

    written: list[Path] = []
    sources = {'hermes.db': bdb.db_path(), 'shared.db': shared_path(), 'dlq.db': dlq_path()}
    for name, source in sources.items():
        if not Path(source).exists():
            continue
        out = target / name
        src = sqlite3.connect(str(source))
        dst = sqlite3.connect(str(out))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        try:
            os.chmod(out, 0o600)
        except OSError:
            pass
        written.append(out)
    log.info('db_backup: %d file ke %s', len(written), target)
    return written
