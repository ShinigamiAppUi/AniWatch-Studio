"""cache_warmer.py - CacheWarmerAgent: the CDN is warm before prime time (17.00).

Tools from AGENTS.md §4.2: `get_trending`, `warm_cdn_cache`.

"Trending" here is what this fork can actually know: live episodes, newest
first (`episode_schedule`). There is no view-count API to rank by, and inventing
one would mean warming the wrong files.

Warming is a real HTTP GET per file against `CDN_BASE_URL`. Without that
variable there is nowhere to warm, so the run reports `warmed: 0` and the reason
instead of pretending the cache is hot (ENV-VARS.md §3: the CDN is optional).
Nothing is published here: this agent only touches the cache.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)

#: Prime time is 19.00-22.00 WIB; this many episodes is plenty to pre-fetch
TRENDING_LIMIT = 10

WARM_TIMEOUT_S = 20


class CacheWarmerAgent:
    """Warm the files of the newest live episodes."""

    def __init__(self, con: sqlite3.Connection | None = None) -> None:
        self._con = con
        self._own = con is None

    def con(self) -> sqlite3.Connection:
        if self._con is None:
            from . import store

            self._con = store.connect()
        return self._con

    def close(self) -> None:
        if self._own and self._con is not None:
            self._con.close()
            self._con = None

    def get_trending(self, limit: int = TRENDING_LIMIT) -> list[dict]:
        """Newest live episodes, with the encoded file each one serves."""
        rows = self.con().execute(
            "SELECT episode_id, encoded_path, published_at FROM episode_schedule "
            "WHERE status='live' ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def warm_cdn_cache(self, episodes: list[dict]) -> dict:
        """One GET per file; a missing CDN or file is reported, never counted."""
        base = config.cdn_base_url()
        if not base:
            return {'warmed': 0, 'failed': [], 'reason': 'CDN_BASE_URL kosong - tidak ada yang bisa dihangatkan'}
        if not episodes:
            return {'warmed': 0, 'failed': [], 'reason': 'belum ada episode live'}

        import httpx

        warmed: list[str] = []
        failed: list[dict] = []
        for episode in episodes:
            name = Path(str(episode.get('encoded_path') or '')).name
            if not name:
                failed.append({'episode_id': episode.get('episode_id'), 'error': 'encoded_path kosong'})
                continue
            url = f'{base}/{name}'
            try:
                res = httpx.get(url, timeout=WARM_TIMEOUT_S, follow_redirects=True)
                res.raise_for_status()
                warmed.append(episode['episode_id'])
            except Exception as err:  # noqa: BLE001 - one cold file must not stop the rest
                failed.append({'episode_id': episode.get('episode_id'), 'error': str(err)[:160]})
        log.info('cache_warmer: %d hangat, %d gagal', len(warmed), len(failed))
        return {'warmed': len(warmed), 'warmed_ids': warmed, 'failed': failed,
                'reason': None if warmed else 'semua permintaan gagal'}

    def run(self, now: float | None = None) -> dict:
        """`run_cache_warmer`: trending -> warm, returns what happened."""
        at = time.time() if now is None else float(now)
        trending = self.get_trending()
        result = self.warm_cdn_cache(trending)
        return {'at': at, 'trending': len(trending), **result}


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Not wired to a webhook trigger; callable for a manual warm-up."""
    agent = CacheWarmerAgent()
    try:
        if char:
            char.update('get_trending', tool='get_trending')
        return agent.run()
    finally:
        agent.close()
