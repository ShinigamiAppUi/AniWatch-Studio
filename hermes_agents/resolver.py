"""resolver.py - the Resolver role (W11): page -> playable URL, and what blocks it.

Two layers, never mixed (W11-SCRAPER-RESOLVER.md §2.1): `PageResolver` and
`LinkResolver` live in the Go backend; this file only asks
`POST /v1/admin/media/resolve` and reads the answer. No direct URL is stored
here — a signed host link expires, so the resolve is repeated (D-64).

A resolution that no adapter can handle is still a result: it comes back as a
`host_not_supported` warning and is counted in `unsupported`, because a host
nobody can play is work for the next wave, not a silent failure.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

from . import aniwatch_admin as admin
from . import scraper

log = logging.getLogger(__name__)

RESOLVE_PATH = '/v1/admin/media/resolve'
RESOLVE_TIMEOUT_S = 45.0

#: A playable URL is short-lived; say so in `direct_ready` instead of storing it
CACHE_SECONDS = 300.0

UNSUPPORTED_WARNING = 'host_not_supported'


def resolve(page_url: str, *, content_type: str | None = None) -> dict:
    """Dry-run the resolver for one page; writes nothing on the backend either."""
    url = str(page_url or '').strip()
    if not url:
        return {'ok': False, 'reason': 'page_url kosong', 'playable': False, 'warnings': []}
    body: dict = {'url': url}
    if content_type:
        body['content_type'] = content_type
    result = admin.request('POST', RESOLVE_PATH, json_body=body, timeout=RESOLVE_TIMEOUT_S)
    if not result['ok']:
        return {'ok': False, 'url': url, 'playable': False, 'warnings': [],
                'reason': result['reason'], 'configured': result.get('configured', True)}
    data = result['data']
    warnings = [str(w)[:160] for w in (data.get('warnings') or []) if str(w).strip()]
    return {'ok': True, 'url': url,
            'provider': data.get('provider'), 'playable': data.get('playable') is True,
            'mime': data.get('content_type') or data.get('mime'),
            'probe': data.get('probe') if isinstance(data.get('probe'), dict) else {},
            'warnings': warnings, 'data': data}


def pending_targets(*, context=None) -> list[dict]:
    """The `need_direct` handoffs addressed to the Resolver that nobody took yet.

    Read-only: `take()` belongs to a later hop, and dropping the envelope before
    the resolve succeeded would lose the only record of what still needs a URL.
    """
    from hermes_bridge import handoff

    found: list[dict] = []
    for key, env in handoff.pending(context=context).items():
        if not isinstance(env, dict) or env.get('to') != 'Resolver':
            continue
        if str(env.get('reason') or '') != 'need_direct':
            continue
        payload = env.get('payload') if isinstance(env.get('payload'), dict) else {}
        entry = dict(payload)
        entry['key'] = key
        entry['subject'] = env.get('subject')
        found.append(entry)
    return found


def refresh_due(limit: int = 20, *, context=None, now: float | None = None) -> dict:
    """Resolve the oldest `need_direct` pages; return what is ready and what is not.

    `direct_ready` is a *report* — `expires_at` is `now + CACHE_SECONDS` because
    the URL behind it is short-lived. Nothing is written to AniWatch's DB here.
    """
    at = time.time() if now is None else float(now)
    targets = pending_targets(context=context)[: max(1, int(limit))]
    if not targets:
        return {'ok': True, 'resolved': [], 'unresolved': {}, 'skipped': 0,
                'reason': 'tidak ada need_direct yang menunggu'}

    ready: list[dict] = []
    unresolved: dict[str, int] = {}
    failed: list[dict] = []
    for target in targets:
        url = str(target.get('page_url') or '')
        result = resolve(url, content_type=target.get('content_type') or None)
        if not result['ok']:
            failed.append({'target_id': target.get('target_id'), 'url': url,
                           'reason': result.get('reason')})
            continue
        if result['playable']:
            ready.append({
                'target_id': target.get('target_id'),
                'content_type': target.get('content_type'),
                'source_id': target.get('source_id'),
                'provider': result.get('provider'),
                'probe': result.get('probe') or {},
                'expires_at': at + CACHE_SECONDS,
            })
            continue
        if any(UNSUPPORTED_WARNING in warning for warning in result['warnings']):
            host = urlsplit(url).hostname or url
            unresolved[host] = unresolved.get(host, 0) + 1

    log.info('resolver refresh: %d siap, %d host tanpa adapter, %d gagal',
             len(ready), len(unresolved), len(failed))
    return {'ok': True, 'resolved': ready, 'unresolved': unresolved,
            'failed': failed, 'skipped': 0}


def health_report(*, refresh_limit: int = 3, context=None) -> dict:
    """One report for `/resolver`: dead/degraded sources, unsupported hosts, gave-up queue."""
    health = scraper.sources_health()
    queue = scraper.queue_summary()
    pending = pending_targets(context=context)
    refresh = (refresh_due(min(refresh_limit, len(pending)), context=context)
               if pending else {'resolved': [], 'unresolved': {}, 'failed': []})

    degraded = [row for row in health.get('sources') or []
                if str(row.get('status') or '') == 'degraded']
    return {
        'ok': bool(health.get('ok')) and bool(queue.get('ok')),
        'reason': health.get('reason') or queue.get('reason'),
        'dead': health.get('dead') or [],
        'degraded': degraded,
        'failed': health.get('failed') or [],
        'gave_up': queue.get('gave_up') or [],
        'unresolved': refresh['unresolved'],
        'resolved': refresh['resolved'],
        'waiting': len(pending),
    }
