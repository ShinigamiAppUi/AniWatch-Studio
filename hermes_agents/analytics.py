"""analytics.py - AnalyticsAgent: what the numbers are doing this week.

Tools from AGENTS.md §4.4: `fetch_watch_data`, `detect_dropoff`,
`generate_report`. The numbers come from `growth_data.py`, which names its
source in the result: the AniWatch export (`ANALYTICS_FEED`) when the site wrote
one, otherwise this fork's own DB.

Saying "the tontonan data is not there yet" is the point. The old plan line was
"Analytics fetches watch data"; there is no watch-data API in this fork, so the
agent reports the local facts it really has and lists what the export must carry
before drop-off can be computed - it never fills the gap with a plausible number.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from . import growth_data

log = logging.getLogger(__name__)

#: Where the snapshot lands, under `media/published/`
SNAPSHOT_DIR = 'analytics'


class AnalyticsAgent:
    """Reads the two sources, computes drop-off, writes one snapshot."""

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

    # -- the tools ----------------------------------------------------------

    def fetch_watch_data(self) -> dict[str, Any]:
        """The export's episode rows, with the reason when it is missing."""
        feed = growth_data.read_feed()
        rows = growth_data.feed_episodes(feed)
        return {
            'source': 'feed' if feed is not None else 'none',
            'episodes': rows,
            'reason': None if feed is not None else 'ANALYTICS_FEED belum ada',
        }

    def detect_dropoff(self) -> list[dict]:
        """Episodes losing more than half their viewers, from the export only."""
        return growth_data.dropoffs(growth_data.feed_episodes(growth_data.read_feed()))

    def generate_report(self, now: float | None = None) -> dict[str, Any]:
        """One snapshot: local facts, feed facts when available, drop-offs."""
        at = time.time() if now is None else float(now)
        data = growth_data.snapshot(self.con(), at)
        path = growth_data.write_json(
            f'{SNAPSHOT_DIR}/{time.strftime("%Y-%m-%d", time.localtime(at))}.json', data,
        )
        log.info('analytics: snapshot %s (source=%s, dropoff=%d)', path, data['source'],
                 len(data['dropoffs']))
        return {**data, 'path': str(path)}


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point `webhook_server/triggers.py` calls for `analytics_ready`."""
    data = payload if isinstance(payload, dict) else {}
    now = data.get('now')
    agent = AnalyticsAgent()
    try:
        if char:
            char.update('fetch_watch_data + detect_dropoff', tool='fetch_watch_data')
        report = agent.generate_report(now=now if isinstance(now, (int, float)) else None)
        if char:
            char.update(f'snapshot {report["source"]}: {len(report["dropoffs"])} drop-off',
                        tool='generate_report')
        return {'action': 'reported', 'source': report['source'],
                'dropoffs': len(report['dropoffs']), 'path': report['path']}
    finally:
        agent.close()
