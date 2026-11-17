"""recommendation.py - RecommendationAgent: the Sunday batch, written where it lands.

Tools from AGENTS.md §4.4: `fetch_history`, `run_model`, `save_recs`.

The model is deliberately small and explainable: users who watched the same
episode are a co-view pair, an episode's score for a user is how many of that
user's co-viewers watched it, and an episode the user already watched is never
recommended. No LLM, so the same export always produces the same rows - which is
what makes `/recap`-style questions answerable.

Where the rows go is named in the result: AniWatch's own SQLite file
(`RECOMMENDATION_DB`, table `recommendations`, created if missing) or, when that
file is not configured, `media/published/recommendations.jsonl`. The fork cannot
write into the live site by itself, so it never claims it did.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config, growth_data

log = logging.getLogger(__name__)

#: A user gets at most this many rows per batch
MAX_RECS_PER_USER = 10

#: How many co-viewers must agree before an episode is recommended at all
MIN_SCORE = 1

RECOMMENDATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS recommendations (
    user_id    TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    score      REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, episode_id)
)
"""


class RecommendationAgent:
    """Co-view recommendations from the export, written to the site or a file."""

    def __init__(self, feed_path: Path | None = None, now: float | None = None) -> None:
        self._feed_path = feed_path
        self._now = now

    def fetch_history(self) -> dict[str, list[str]]:
        """`{user_id: [episode_id, ...]}`; empty when the export is not there."""
        feed = growth_data.read_feed(self._feed_path)
        if feed is None:
            log.warning('recommendation: ANALYTICS_FEED belum ada - tidak ada history untuk diproses')
            return {}
        return growth_data.feed_history(feed)

    def run_model(self, history: dict[str, list[str]]) -> list[dict]:
        """One row per (user, unwatched episode), highest score first."""
        # episode -> the set of users who watched it
        viewers: dict[str, set[str]] = {}
        for user, episodes in history.items():
            for episode in episodes:
                viewers.setdefault(episode, set()).add(user)

        rows: list[dict] = []
        for user, watched in history.items():
            seen = set(watched)
            scores: dict[str, int] = {}
            for episode in watched:
                for other in viewers.get(episode, ()):
                    if other == user:
                        continue
                    for candidate in history.get(other, ()):
                        if candidate not in seen:
                            scores[candidate] = scores.get(candidate, 0) + 1
            ranked = sorted(
                ((episode, score) for episode, score in scores.items() if score >= MIN_SCORE),
                key=lambda item: (-item[1], item[0]),
            )[:MAX_RECS_PER_USER]
            rows.extend({'user_id': user, 'episode_id': episode, 'score': float(score)}
                        for episode, score in ranked)
        return rows

    def save_recs(self, recs: list[dict], now: float | None = None) -> dict:
        """Write the batch; the result says target, count and where."""
        at = time.time() if now is None else float(now)
        target = config.recommendation_db()
        if target:
            path = Path(target).expanduser()
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            con = sqlite3.connect(str(path))
            try:
                con.execute(RECOMMENDATIONS_TABLE)
                con.executemany(
                    'INSERT OR REPLACE INTO recommendations (user_id, episode_id, score, created_at) '
                    'VALUES (?, ?, ?, ?)',
                    [(row['user_id'], row['episode_id'], row['score'], at) for row in recs],
                )
                con.commit()
            finally:
                con.close()
            log.info('recommendation: %d baris ke %s (tabel recommendations)', len(recs), path)
            return {'target': 'db', 'written': len(recs), 'path': str(path)}

        out = config.media_root() / 'published' / 'recommendations.jsonl'
        out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The file is rewritten whole: it is this batch's answer, and appending
        # would leave yesterday's scores next to today's with no way to tell them
        out.write_text(
            ''.join(json.dumps({'user_id': row['user_id'], 'episode_id': row['episode_id'],
                                'score': row['score'], 'created_at': at}, ensure_ascii=False) + '\n'
                    for row in recs),
            encoding='utf-8',
        )
        log.info('recommendation: %d baris ke %s', len(recs), out)
        return {'target': 'file', 'written': len(recs), 'path': str(out)}

    def run_batch(self, now: float | None = None) -> dict:
        """`run_recommendation_batch`: history -> model -> save, never raising."""
        at = time.time() if now is None else float(now)
        history = self.fetch_history()
        recs = self.run_model(history) if history else []
        saved = self.save_recs(recs, now=at)
        return {
            'users': len(history),
            'recommendations': len(recs),
            'target': saved['target'],
            'path': saved['path'],
            'reason': None if history else 'ANALYTICS_FEED kosong atau tanpa history',
            'at': at,
        }
