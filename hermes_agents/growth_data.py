"""growth_data.py - the numbers the growth agents read, from sources this fork has.

Two sources, and every result names the one it used:

- the AniWatch export at `ANALYTICS_FEED` - one JSON file the site writes:
  views / watch time per episode, and per-user history. Optional, because this
  fork cannot call the site (ENV-VARS.md §3d).
- this fork's own DB (`hermes.db`): published episodes, tickets, user reports.
  Always there, always labelled `local`.

Nothing here invents a number to fill a diagram: a metric the feed does not
carry is absent, `dropoffs` is empty with `insufficient` naming the reason, and a
weak completion rate only becomes a drop-off once enough people watched.

This is a data module, not an agent: `analytics.py` and `marketing.py` both read
it, and neither imports the other (AGENT-HANDOFFS.md §5.3).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)

#: Fewer viewers than this and a completion rate is noise, not a drop-off
MIN_VIEWS = 20

#: Below this share of finishes, an episode is losing people
DROPOFF_RATE = 0.5

#: How far back "recent" reaches in `local_facts`
RECENT_DAYS = 7


def feed_path() -> Path | None:
    """`ANALYTICS_FEED` as a path, or None when the site has not exported yet."""
    raw = (config.analytics_feed() or '').strip()
    return Path(raw).expanduser() if raw else None


def read_feed(path: Path | None = None) -> dict | None:
    """The AniWatch export, or None when there is none readable.

    A malformed export is a logged `None`, not an exception: the batch jobs that
    call this must keep running on the local fallback, and a site that exports a
    broken file should not stop the office.
    """
    target = path if path is not None else feed_path()
    if target is None:
        return None
    try:
        data = json.loads(Path(target).read_text(encoding='utf-8'))
    except FileNotFoundError:
        log.warning('growth: ANALYTICS_FEED %s belum ada - memakai data lokal', target)
        return None
    except (OSError, ValueError) as err:
        log.warning('growth: ANALYTICS_FEED %s tidak terbaca (%s) - memakai data lokal', target, err)
        return None
    if not isinstance(data, dict):
        log.warning('growth: ANALYTICS_FEED bukan object JSON - memakai data lokal')
        return None
    return data


def feed_episodes(feed: dict | None) -> list[dict]:
    """Per-episode rows of the export, keeping only rows that name an episode."""
    rows = (feed or {}).get('episodes') or []
    return [row for row in rows if isinstance(row, dict) and row.get('episode_id')]


def feed_history(feed: dict | None) -> dict[str, list[str]]:
    """`{user_id: [episode_id, ...]}` from the export's `history` rows."""
    history: dict[str, list[str]] = {}
    for row in (feed or {}).get('history') or []:
        if not isinstance(row, dict):
            continue
        user, episode = row.get('user_id'), row.get('episode_id')
        if not (user and episode):
            continue
        seen = history.setdefault(str(user), [])
        if episode not in seen:
            seen.append(str(episode))
    return history


def local_facts(con: sqlite3.Connection, now: float | None = None) -> dict[str, Any]:
    """What this fork itself knows: episodes out, tickets, reports."""
    at = time.time() if now is None else float(now)
    since = at - RECENT_DAYS * 86400
    live = con.execute("SELECT COUNT(*) FROM episode_schedule WHERE status='live'").fetchone()[0]
    released = con.execute(
        "SELECT COUNT(*) FROM episode_schedule WHERE published_at IS NOT NULL AND published_at >= ?",
        (since,),
    ).fetchone()[0]
    open_tickets = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'pending', 'escalated')"
    ).fetchone()[0]
    resolved = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status='resolved' AND resolved_at >= ?", (since,)
    ).fetchone()[0]
    reports = con.execute(
        'SELECT COUNT(*) FROM user_reports WHERE created_at >= ?', (since,)
    ).fetchone()[0]
    recent = [
        row['episode_id']
        for row in con.execute(
            "SELECT episode_id FROM episode_schedule WHERE status='live' "
            'ORDER BY COALESCE(published_at, created_at) DESC LIMIT 10'
        )
    ]
    return {
        'episodes_live': live,
        'episodes_released_7d': released,
        'tickets_open': open_tickets,
        'tickets_resolved_7d': resolved,
        'user_reports_7d': reports,
        'recent_episodes': recent,
    }


def dropoffs(episodes: list[dict], min_views: int = MIN_VIEWS,
             rate: float = DROPOFF_RATE) -> list[dict]:
    """Episodes where too few viewers reached the end, computed from the feed.

    A row without `views`/`completions` is skipped - an absent metric is not a
    zero, and calling it one would flag every episode the export does not cover.
    """
    found: list[dict] = []
    for row in episodes:
        views, completions = row.get('views'), row.get('completions')
        if not isinstance(views, (int, float)) or not isinstance(completions, (int, float)):
            continue
        if views < min_views:
            continue
        completion = float(completions) / float(views) if views else 0.0
        if completion < rate:
            found.append({
                'episode_id': row['episode_id'],
                'views': int(views),
                'completion_rate': round(completion, 3),
                'dropped': int(views - completions),
            })
    return sorted(found, key=lambda item: item['completion_rate'])


def snapshot(con: sqlite3.Connection, now: float | None = None,
             feed: dict | None = None) -> dict[str, Any]:
    """One growth snapshot: the feed when there is one, local facts always."""
    at = time.time() if now is None else float(now)
    data = read_feed() if feed is None else feed
    episodes = feed_episodes(data)
    return {
        'generated_at': at,
        'source': 'feed+local' if data is not None else 'local',
        'feed': {
            'generated_at': (data or {}).get('generated_at'),
            'episodes': len(episodes),
            'users_with_history': len(feed_history(data)),
        } if data is not None else None,
        'local': local_facts(con, at),
        'dropoffs': dropoffs(episodes),
        'insufficient': [] if data is not None else [
            'ANALYTICS_FEED kosong: angka tontonan, watch time dan drop-off belum bisa dihitung',
        ],
    }


def write_json(relative: str, data: object) -> Path:
    """Write a JSON file under `media/published/` (the folder the site reads)."""
    path = config.media_root() / 'published' / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    return path
