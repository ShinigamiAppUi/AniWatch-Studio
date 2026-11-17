"""ops.py - Ops: the hourly health check nobody asked for until something breaks.

AGENTS.md §? defines the trigger: "system check tiap jam (langsung, bukan lewat
Orchestrator karena tidak menghasilkan karakter)". So this module never draws a
character and never goes through the bridge - it reads the machine and the
databases, returns findings, and optionally pings Discord when a `critical` one
shows up.

Why findings and not booleans: an alert that only says "unhealthy" is useless at
3 a.m. Each finding carries `level`, `check`, `detail` and what to do about it,
and `run_ops_check` logs them in one line each.

Nothing here is destructive: no cleanup, no rotation, no killing processes. The
checks that *fix* things live in `webhook_server/jobs.py` (cleanup, sweep,
backup), and Ops only reports what it sees.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

#: Below this share of free space on the data disk, `disk` is critical
DISK_MIN_FREE = 0.10

#: A business DB bigger than this is a warning (backup time, not breakage)
DB_WARN_BYTES = 500 * 1024 * 1024

LEVELS = ('ok', 'warn', 'critical')


def _db_path() -> Path:
    from hermes_bridge import db as bdb

    return Path(bdb.db_path())


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _finding(level: str, check: str, detail: str, action: str = '') -> dict:
    if level not in LEVELS:
        raise ValueError(f'level tidak dikenal: {level}')
    return {'level': level, 'check': check, 'detail': detail, 'action': action}


class OpsAgent:
    """The system check, as a list of findings."""

    def __init__(self, now: float | None = None) -> None:
        self.at = time.time() if now is None else float(now)

    def check_system(self) -> list[dict]:
        """Every check, always returned (an `ok` row is information too)."""
        findings = [
            self._disk(),
            self._database(),
            self._dlq(),
            self._shared_context(),
            self._scheduler(),
            self._mail(),
        ]
        return findings

    # -- individual checks --------------------------------------------------

    def _disk(self) -> dict:
        target = _db_path().parent
        try:
            usage = shutil.disk_usage(str(target))
        except OSError as err:
            return _finding('warn', 'disk', f'tidak bisa membaca {target}: {err}', 'cek mount data')
        free_share = usage.free / usage.total if usage.total else 0.0
        detail = f'{free_share * 100:.1f}% bebas dari {usage.total / 1e9:.1f} GB'
        if free_share < DISK_MIN_FREE:
            return _finding('critical', 'disk', detail, 'hapus backup lama atau pindahkan media')
        if free_share < DISK_MIN_FREE * 2:
            return _finding('warn', 'disk', detail, 'siapkan ruang sebelum backup malam')
        return _finding('ok', 'disk', detail)

    def _database(self) -> dict:
        path = _db_path()
        if not path.exists():
            return _finding('critical', 'database', f'{path} tidak ada', 'jalankan init_db')
        size = _size(path)
        detail = f'{path.name} {size / 1e6:.1f} MB'
        try:
            con = sqlite3.connect(str(path))
            try:
                integrity = con.execute('PRAGMA quick_check').fetchone()[0]
                rows = con.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error as err:
            return _finding('critical', 'database', f'{detail}: {err}', 'pulihkan dari backup')
        if integrity != 'ok':
            return _finding('critical', 'database', f'{detail}: quick_check={integrity}', 'pulihkan dari backup')
        if size > DB_WARN_BYTES:
            return _finding('warn', 'database', f'{detail}, {rows} tiket', 'jadwalkan arsip tiket lama')
        return _finding('ok', 'database', f'{detail}, {rows} tiket')

    def _dlq(self) -> dict:
        from hermes_bridge.queue import default_path as dlq_path

        path = Path(dlq_path())
        if not path.exists():
            return _finding('ok', 'dlq', 'kosong')
        try:
            con = sqlite3.connect(str(path))
            try:
                pending = con.execute('SELECT COUNT(*) FROM dlq').fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error as err:
            return _finding('warn', 'dlq', f'tidak bisa dibaca: {err}', 'cek DLQ_DB')
        if pending:
            return _finding('warn', 'dlq', f'{pending} event menunggu',
                            'pastikan OFFICE_TOKEN benar lalu `bridge.flush_queue()`')
        return _finding('ok', 'dlq', 'kosong')

    def _shared_context(self) -> dict:
        from hermes_bridge.shared_context import default_path as shared_path

        path = Path(shared_path())
        if not path.exists():
            return _finding('ok', 'context', 'belum ada file')
        try:
            con = sqlite3.connect(str(path))
            try:
                rows = con.execute('SELECT COUNT(*) FROM context').fetchone()[0]
                oldest = con.execute('SELECT MIN(ts) FROM context').fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error as err:
            return _finding('warn', 'context', f'tidak bisa dibaca: {err}', 'cek SHARED_DB')
        if rows and oldest and self.at - float(oldest) > 26 * 3600:
            return _finding('warn', 'context', f'{rows} baris, tertua {((self.at - oldest) / 3600):.0f} jam',
                            'job shared_context_cleanup mungkin tidak jalan')
        return _finding('ok', 'context', f'{rows} baris')

    def _scheduler(self) -> dict:
        from webhook_server.scheduler import registered_jobs

        jobs = registered_jobs()
        if not jobs:
            # Not an error outside the sidecar (a CLI run has no scheduler), but
            # inside the sidecar it means the lifespan never started it
            return _finding('warn', 'scheduler', 'tidak ada job terdaftar',
                            'jalankan lewat uvicorn (lifespan) atau cek log start')
        missing = [job['id'] for job in jobs if not job.get('next_run_time')]
        if missing:
            return _finding('warn', 'scheduler', f'job tanpa next_run_time: {", ".join(missing)}',
                            'restart sidecar')
        return _finding('ok', 'scheduler', f'{len(jobs)} job terdaftar')

    def _mail(self) -> dict:
        from . import mailer

        if not mailer.configured():
            return _finding('warn', 'mail', 'SMTP_HOST kosong: balasan Support akan gagal',
                            'isi SMTP_HOST di .env (ENV-VARS.md §3b)')
        attempts = mailer.attempts(50)
        failed = [a for a in attempts if not a.get('sent') and float(a.get('at') or 0) > self.at - 86400]
        if failed:
            return _finding('warn', 'mail', f'{len(failed)} kiriman gagal dalam 24 jam',
                            f'lihat {mailer.outbox_path()}')
        return _finding('ok', 'mail', 'SMTP siap')

    # -- reporting ----------------------------------------------------------

    def summary(self, findings: list[dict]) -> str:
        """One line for the log: `4 ok, 1 warn, 0 critical`."""
        counts = {level: sum(1 for f in findings if f['level'] == level) for level in LEVELS}
        return f"{counts['ok']} ok, {counts['warn']} warn, {counts['critical']} critical"

    def send_alert(self, findings: list[dict]) -> bool:
        """Post the non-ok findings to Discord, when a webhook is configured.

        Returns True when something was actually posted. No webhook means no
        alert - the log line is the record, not a fake notification.
        """
        from . import config

        url = config.discord_webhook()
        bad = [f for f in findings if f['level'] != 'ok']
        if not url or not bad:
            return False
        lines = [f"**Ops** {self.summary(findings)}"] + [
            f"- `{f['check']}` {f['level']}: {f['detail']}" + (f" → {f['action']}" if f['action'] else '')
            for f in bad
        ]
        try:
            import httpx

            res = httpx.post(url, json={'content': '\n'.join(lines)[:1900]}, timeout=15)
            res.raise_for_status()
            return True
        except Exception as err:  # noqa: BLE001 - an alert must not fail the job
            log.warning('ops: alert Discord gagal: %s', err)
            return False


def run_ops_check(now: float | None = None) -> dict:
    """One hourly round: check, log every finding, alert the bad ones.

    Returns `{summary, findings, alerted}` so the selfcheck and `/health`-style
    callers can assert on it without parsing logs.
    """
    ops = OpsAgent(now=now)
    findings = ops.check_system()
    for item in findings:
        log.info('ops: %s %s - %s%s', item['level'], item['check'], item['detail'],
                 f" (saran: {item['action']})" if item['action'] else '')
    alerted = ops.send_alert(findings)
    summary = ops.summary(findings)
    log.info('ops: %s', summary)
    return {'summary': summary, 'findings': findings, 'alerted': alerted}
