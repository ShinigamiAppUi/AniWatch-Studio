"""scheduler.py - APScheduler in the sidecar process (W4).

Follows SCHEDULER.md §1 and §3:

- started from FastAPI's lifespan, **never at import** (Rev 3.1 #6): `uvicorn
  --reload` imports a module twice, and a scheduler started at import ends up
  with every job twice.
- `start_scheduler()` is idempotent, so a double startup is a no-op.
- jobs get `max_instances=1`, `coalesce=True` and an explicit
  `misfire_grace_time`, so a laptop that slept for two hours runs a job once, not
  twenty-four times.
- one job raising never kills the scheduler (`_guard`).

Jobs implemented in W4: `episode_embargo`, `shared_context_cleanup`,
`approval_sweep`, `db_backup` - the four whose work exists (`jobs.py`). The
other seven in SCHEDULER.md §2 belong to agents from W5-W9; they are listed in
`PENDING_JOBS` with the reason, logged once at startup, and **not** registered:
a job that runs and does nothing would look like a working system.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import jobs

log = logging.getLogger(__name__)

#: SCHEDULER.md §2 defaults, in one place
COMMON = dict(max_instances=1, coalesce=True, misfire_grace_time=300)

#: `id` -> why it is not registered yet. Printed by `pending_jobs()` and at start.
PENDING_JOBS: dict[str, str] = {
    'weekly_report': 'butuh MarketingAgent + Orchestrator (W6/W8)',
    'cache_warmer': 'butuh CacheWarmerAgent (W6)',
    'recommendation_batch': 'butuh RecommendationAgent (W6)',

}

_sched: BackgroundScheduler | None = None
_lock = threading.Lock()


def timezone_name() -> str:
    """`HERMES_TZ`, default the WIB zone SCHEDULER.md §1 pins."""
    return (os.environ.get('HERMES_TZ') or 'Asia/Jakarta').strip() or 'Asia/Jakarta'


def _guard(fn):
    """Wrap a job so its failure is a log line and the scheduler keeps running."""

    def wrapper(*args, **kwargs):
        started = time.monotonic()
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 - SCHEDULER.md §1 rule 4
            log.exception('scheduler job %s gagal', getattr(fn, '__name__', 'job'))
        finally:
            log.info('%s selesai dalam %.2fs', getattr(fn, '__name__', 'job'), time.monotonic() - started)

    wrapper.__name__ = getattr(fn, '__name__', 'job')
    return wrapper


def start_scheduler() -> BackgroundScheduler:
    """Start the scheduler once and return it; a second call is a no-op."""
    global _sched
    with _lock:
        if _sched is not None and _sched.running:
            return _sched

        sched = BackgroundScheduler(timezone=timezone_name())
        sched.add_job(_guard(jobs.run_episode_scheduler), IntervalTrigger(minutes=1),
                      id='episode_embargo', **COMMON)
        sched.add_job(_guard(jobs.cleanup_shared_context), 'cron', hour=3,
                      id='shared_context_cleanup', **COMMON)
        sched.add_job(_guard(jobs.sweep_approvals), IntervalTrigger(hours=1),
                      id='approval_sweep', **COMMON)
        sched.add_job(_guard(jobs.sla_check), IntervalTrigger(minutes=5),
                      id='sla_check', **COMMON)
        sched.add_job(_guard(jobs.check_new_emails), IntervalTrigger(minutes=5),
                      id='email_check', **COMMON)
        sched.add_job(_guard(jobs.run_ops_check), IntervalTrigger(hours=1),
                      id='ops_check', **COMMON)
        sched.add_job(_guard(jobs.check_handoffs), IntervalTrigger(minutes=15),
                      id='handoff_check', **COMMON)
        sched.add_job(_guard(jobs.backup_databases), 'cron', hour=2,
                      id='db_backup', **COMMON)
        sched.start()
        _sched = sched

    log.info('scheduler jalan (%s): %d job', timezone_name(), len(sched.get_jobs()))
    for job_id, reason in PENDING_JOBS.items():
        log.info('scheduler: %s belum didaftarkan - %s', job_id, reason)
    return sched


def shutdown_scheduler() -> None:
    """Stop the scheduler; safe when it was never started."""
    global _sched
    with _lock:
        if _sched is not None and _sched.running:
            _sched.shutdown(wait=False)
        _sched = None


def registered_jobs() -> list[dict]:
    """`[{id, next_run_time}]` for `/health`, empty when not started."""
    sched = _sched
    if sched is None or not sched.running:
        return []
    return [
        {'id': job.id, 'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None}
        for job in sched.get_jobs()
    ]


def pending_jobs() -> list[dict]:
    """`[{id, reason}]` for the jobs waiting on a later week."""
    return [{'id': job_id, 'reason': reason} for job_id, reason in PENDING_JOBS.items()]
