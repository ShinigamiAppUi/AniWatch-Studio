"""scraper.py - the Scraper role (W11): run the backend's scraper and report it.

What this role does **not** do: fetch a site, parse HTML, or write
`episode_sources`. AniWatch's Go backend owns the adapters, the queue and the
rows; the office triggers it and reads the answer back
(W11-SCRAPER-RESOLVER.md §2, §5.2). Without `ANIWATCH_API_URL` /
`ANIWATCH_ADMIN_TOKEN` every call says so, because an empty report would look
like a healthy scraper.

`propose_domain()` is the one place a person decides: it raises an approval card
with the evidence and **never** calls the PATCH endpoint (§8: a new domain is an
identity decision, not a machine decision).
"""

from __future__ import annotations

import logging

from . import aniwatch_admin as admin
from . import config

log = logging.getLogger(__name__)

BACKFILL_PATH = '/v1/admin/scrape/backfill'
RUN_PATH = '/v1/admin/scrape/run'
QUEUE_PATH = '/v1/admin/scrape/queue'
HEALTH_PATH = '/v1/admin/sources/health'

#: A source that failed this many times in a row is what §4.6 calls dead
FAIL_THRESHOLD = 3

HEALTH_TIMEOUT_S = 30.0
BACKFILL_TIMEOUT_S = 60.0
RUN_TIMEOUT_S = 120.0

PROPOSE_OPTIONS = ('Setujui ganti base_url', 'Tolak')


def backfill(limit: int | None = None) -> dict:
    """Ask the backend to fill `scraper_queue` from the active sources.

    `limit` defaults to `SCRAPER_BACKFILL_BATCH` (ENV-VARS.md §3f): one hour's
    worth of work, not a thousand sites at once.
    """
    batch = config.scraper_backfill_batch() if limit is None else max(1, int(limit))
    result = admin.request('POST', BACKFILL_PATH, json_body={'limit': batch},
                           timeout=BACKFILL_TIMEOUT_S)
    if not result['ok']:
        return {'ok': False, 'reason': result['reason'], 'limit': batch,
                'queued': 0, 'configured': result.get('configured', True)}
    data = result['data']
    return {'ok': True, 'limit': batch, 'queued': _int(data.get('queued')),
            'data': data}


def run_target(target_id: str, *, content_type: str = 'anime', source: str | None = None,
               dry_run: bool = False) -> dict:
    """Run the runner for one episode/chapter, or one source (`dry_run` = parse only)."""
    target = str(target_id or '').strip()
    if not target:
        return {'ok': False, 'reason': 'target_id kosong'}
    body: dict = {'target_id': target, 'content_type': content_type, 'dry_run': bool(dry_run)}
    if source:
        body['source'] = str(source).strip()
    result = admin.request('POST', RUN_PATH, json_body=body, timeout=RUN_TIMEOUT_S)
    if not result['ok']:
        return {'ok': False, 'reason': result['reason'], 'target': target,
                'configured': result.get('configured', True)}
    return {'ok': True, 'target': target, 'dry_run': bool(dry_run), 'data': result['data']}


def queue_summary(params: dict | None = None) -> dict:
    """`GET /v1/admin/scrape/queue`: what is queued, claimed, done and gave up."""
    result = admin.request('GET', QUEUE_PATH, params=params or None)
    if not result['ok']:
        return {'ok': False, 'reason': result['reason'],
                'configured': result.get('configured', True)}
    data = result['data']
    states = data.get('states') if isinstance(data.get('states'), dict) else {}
    gave_up = data.get('gave_up') if isinstance(data.get('gave_up'), list) else []
    return {'ok': True, 'states': states, 'by_domain': data.get('by_domain') or {},
            'gave_up': gave_up, 'items': data.get('items') or [], 'data': data}


def sources_health(*, threshold: int = FAIL_THRESHOLD) -> dict:
    """Read `GET /v1/admin/sources/health` and count what is dead and degraded.

    `dead` is the backend's own status; `failed` is every row at or past
    `threshold` consecutive failures — the rows the Scraper has to report even
    before the third failure flips the source off.
    """
    result = admin.request('GET', HEALTH_PATH, timeout=HEALTH_TIMEOUT_S)
    if not result['ok']:
        return {'ok': False, 'reason': result['reason'],
                'configured': result.get('configured', True),
                'counts': {}, 'failed': [], 'dead': [], 'sources': []}
    rows = result['data'].get('sources')
    if not isinstance(rows, list):
        return {'ok': False, 'reason': 'balasan sources/health tidak punya daftar `sources`',
                'counts': {}, 'failed': [], 'dead': [], 'sources': []}

    counts: dict[str, int] = {}
    failed: list[dict] = []
    dead: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get('status') or 'unverified')
        counts[status] = counts.get(status, 0) + 1
        fails = _int(row.get('consecutive_fail'))
        if status == 'dead':
            dead.append(row)
        if fails >= max(1, int(threshold)):
            failed.append(row)
    log.info('sources_health: %d sumber, %d mati, %d gagal >= %d',
             len(rows), len(dead), len(failed), threshold)
    return {'ok': True, 'sources': rows, 'counts': counts, 'dead': dead,
            'failed': failed, 'threshold': max(1, int(threshold))}


def propose_domain(source_id: str, new_url: str, *, old_url: str = '',
                   evidence: list | None = None, char=None, timeout: float = 300.0) -> dict:
    """Raise an approval card for a new `base_url`; write nothing either way.

    The card carries the evidence (redirect chain, certificate, canonical
    markers). Approving means a person may run the PATCH themselves — this
    function never does, so no click in the office can change where a source
    points without the audit row that belongs to that decision.
    """
    source = str(source_id or '').strip()
    target = str(new_url or '').strip()
    if not source or not target:
        return {'ok': False, 'reason': 'source_id dan new_url wajib', 'written': False}
    proof = [str(item)[:160] for item in (evidence or []) if str(item).strip()][:5]
    message = f'Usul domain {source}: {old_url or "?"} -> {target}'
    if proof:
        message += ' | bukti: ' + '; '.join(proof)
    decision = char.ask(message[:400], list(PROPOSE_OPTIONS), timeout=timeout) if char else 'timeout'
    approved = decision == PROPOSE_OPTIONS[0]
    log.info('propose_domain: %s -> %s keputusan=%s (tidak menulis DB)', source, target, decision)
    return {'ok': approved, 'action': 'proposed', 'source_id': source, 'old_url': old_url,
            'new_url': target, 'evidence': proof, 'decision': decision,
            'written': False,
            'reason': None if approved else 'belum disetujui manusia - base_url tidak diubah'}


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
