"""aniwatch_admin.py - the one door to AniWatch's admin API (W11).

`hermes_agents/scraper.py` and `hermes_agents/resolver.py` are office roles: they
trigger, watch and report. The adapters, the DB, the allowlist and the probe live
in the Go backend, and the only way in from here is HTTP admin
(W11-SCRAPER-RESOLVER.md §2): `ANIWATCH_API_URL` + `ANIWATCH_ADMIN_TOKEN`.

Without either variable every call answers `{'ok': False, 'reason': ...}`, never
an empty list that reads as "all healthy" (§11: "Role kantor melapor 'sehat'
tanpa backend"). Nothing in this module prints, logs or returns the token.
"""

from __future__ import annotations

import logging

from . import config

log = logging.getLogger(__name__)

#: Short reads; a slow admin API must not hold a scheduler job open
DEFAULT_TIMEOUT_S = 30.0


def request(method: str, path: str, *, json_body: dict | None = None,
            params: dict | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """One admin call; always a dict, never an exception.

    Returns `{ok, status, data}` on success and `{ok: False, status, reason}` on
    failure. `configured: False` means this office was never pointed at a
    backend, which is a different answer from "the backend said no".
    """
    base = config.aniwatch_api_url()
    if not base:
        return {'ok': False, 'configured': False, 'status': None,
                'reason': 'ANIWATCH_API_URL belum diisi'}
    token = config.aniwatch_admin_token()
    if not token:
        return {'ok': False, 'configured': False, 'status': None,
                'reason': 'ANIWATCH_ADMIN_TOKEN belum diisi'}

    import httpx

    try:
        res = httpx.request(
            method.upper(), f'{base}{path}',
            json=json_body, params=params,
            headers={'Authorization': f'Bearer {token}'},
            timeout=timeout,
            follow_redirects=False,
        )
    except Exception as err:  # noqa: BLE001 - a dead backend is a report, not a crash
        log.warning('aniwatch admin %s %s gagal: %s', method, path, err)
        return {'ok': False, 'configured': True, 'status': None,
                'reason': f'AniWatch tidak bisa dihubungi: {err}'[:300]}

    if res.status_code >= 400:
        return {'ok': False, 'configured': True, 'status': res.status_code,
                'reason': f'AniWatch menjawab {res.status_code}: '
                          f'{(res.text or "").strip()[:200]}'}

    try:
        data = res.json()
    except ValueError:
        return {'ok': False, 'configured': True, 'status': res.status_code,
                'reason': 'balasan admin bukan JSON'}
    return {'ok': True, 'configured': True, 'status': res.status_code,
            'data': data if isinstance(data, dict) else {'items': data}}
