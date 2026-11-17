"""kb.py - the Support knowledge base: SQLite FTS5 over the FAQ articles.

`kb_articles` is an FTS5 virtual table (DB-SCHEMA.md §9): one row per article,
searchable with `bm25`. `SQLiteKB.search()` returns the matches Support needs to
decide between answering and escalating, with the score the threshold
(`KB_MIN_SCORE`) is compared against.

Why `-rank` is the score: FTS5's `rank` is a *negative* bm25 value where -1 is
the best; negating it gives "bigger is better", which is what a threshold wants.
It is relative, not a probability (AGENTS.md §4.1): recalibrate once the KB has
real articles, never trust the 0.5 default in production.

An older database from W3 may still carry `kb_articles` as a normal table. We do
not drop anyone's rows: `_pick_table` copies them into `kb_articles_fts` and uses
that, so a dev DB keeps working without a migration script.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

#: The FAQ that ships with the repo; `SQLiteKB.seed()` reads it
FAQ_PATH = Path(__file__).parent / 'kb_faq.md'

#: AGENTS.md §4.1: relative bm25 score, not a probability
DEFAULT_MIN_SCORE = 0.5

#: Body column index in both the FTS5 table and `snippet()`
BODY_COLUMN = 2

_SLUG_STRIP = re.compile(r'[^a-z0-9]+')


def min_score() -> float:
    """`KB_MIN_SCORE`, default 0.5; a bad value falls back instead of crashing."""
    try:
        return float(os.environ.get('KB_MIN_SCORE') or DEFAULT_MIN_SCORE)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SCORE


def slug(title: str) -> str:
    """A stable id from a title: `Cara membatalkan langganan` -> `cara-membatalkan-langganan`."""
    return _SLUG_STRIP.sub('-', (title or '').strip().lower()).strip('-')[:80]


def parse_markdown(text: str) -> list[dict]:
    """Read the FAQ format: `## Title`, then `category:` / `tags:`, then the body."""
    articles: list[dict] = []
    title: str | None = None
    meta: dict[str, str] = {}
    body: list[str] = []

    def flush() -> None:
        if not title:
            return
        articles.append({
            'id': slug(title),
            'title': title,
            'body': ' '.join(' '.join(body).split()),
            'tags': meta.get('tags', ''),
            'category': meta.get('category', ''),
        })

    for line in text.splitlines():
        if line.startswith('## '):
            flush()
            title, meta, body = line[3:].strip(), {}, []
            continue
        if title is None:
            continue
        key, sep, value = line.partition(':')
        if sep and key.strip() in ('category', 'tags'):
            meta[key.strip()] = value.strip()
            continue
        if line.strip():
            body.append(line.strip())
    flush()
    return articles


def _fts_query(text: str) -> str:
    """Turn free text into an FTS5 query that cannot raise on punctuation.

    Every word is quoted, so `404`, `1080p`, `e-wallet` and `(` are all just
    words, and they are joined with **OR**: FTS5 treats space-separated terms as
    AND, so a ticket whose body has one word no article uses would match
    nothing at all. bm25 still ranks the article that covers more of the words
    first, which is what the threshold reads.

    An empty result means "nothing searchable".
    """
    words = [w for w in re.split(r'[^0-9A-Za-z_]+', text or '') if len(w) > 1]
    return ' OR '.join(f'"{w}"' for w in words[:12])


class SQLiteKB:
    """The FAQ, on SQLite FTS5."""

    def __init__(self, con: sqlite3.Connection | None = None) -> None:
        from . import store

        self._own = con is None
        self.con = con if con is not None else store.connect()
        self.table = self._pick_table()

    # -- schema -------------------------------------------------------------

    def _pick_table(self) -> str:
        """`kb_articles` when it is FTS5, else a side index built from it."""
        row = self.con.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('table') AND name = 'kb_articles'"
        ).fetchone()
        ddl = (row['sql'] if row and 'sql' in row.keys() else (row[0] if row else '')) or ''
        if 'fts5' in ddl.lower():
            return 'kb_articles'
        # A W3-era plain table: keep its rows, index them in a side FTS5 table
        self.con.execute(
            'CREATE VIRTUAL TABLE IF NOT EXISTS kb_articles_fts USING fts5('
            'id UNINDEXED, title, body, tags, category, updated_at UNINDEXED)'
        )
        self.con.commit()
        existing = self.con.execute('SELECT COUNT(*) FROM kb_articles_fts').fetchone()[0]
        if not existing:
            legacy = self._legacy_rows()
            for article in legacy:
                self._insert('kb_articles_fts', article, source='markdown')
            log.info('kb: mengindeks ulang %d artikel lama ke kb_articles_fts', len(legacy))
        return 'kb_articles_fts'

    def _legacy_rows(self) -> list[dict]:
        try:
            rows = self.con.execute('SELECT id, title, body, tags, category FROM kb_articles').fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]

    # -- writing ------------------------------------------------------------

    def _insert(self, table: str, article: dict, source: str) -> None:
        now = time.time()
        self.con.execute(
            f'INSERT INTO {table} (id, title, body, tags, category, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
            (article['id'], article['title'], article['body'], article.get('tags', ''),
             article.get('category', ''), now),
        )
        self.con.execute(
            'INSERT INTO kb_meta (id, source, url, created_at) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET source = excluded.source, url = excluded.url',
            (article['id'], source, article.get('url'), now),
        )

    def upsert(self, article: dict, source: str = 'manual') -> dict:
        """Add or replace one article (same id replaces; FTS5 has no UNIQUE)."""
        article = dict(article)
        article.setdefault('id', slug(article.get('title', '')))
        if not article.get('id') or not article.get('title') or not article.get('body'):
            raise ValueError('artikel butuh id/title/body')
        with self.con:
            self.con.execute(f'DELETE FROM {self.table} WHERE id = ?', (article['id'],))
            self._insert(self.table, article, source)
        return article

    def seed(self, path: Path | None = None) -> int:
        """Load the shipped FAQ when the table is empty; returns how many went in.

        Only when empty: a curated KB must never be overwritten by a deploy.
        """
        if self.stats()['articles']:
            return 0
        text = Path(path or FAQ_PATH).read_text(encoding='utf-8')
        articles = parse_markdown(text)
        for article in articles:
            self.upsert(article, source='markdown')
        log.info('kb: %d artikel FAQ dimuat', len(articles))
        return len(articles)

    # -- reading ------------------------------------------------------------

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """The best `top_k` articles for `query`, best first.

        Returns `[{id, title, category, score, snippet}]`; `score` is `-rank`
        (bigger is better) and is what `KB_MIN_SCORE` is compared against.
        """
        match = _fts_query(query)
        if not match:
            return []
        try:
            rows = self.con.execute(
                f'SELECT id, title, body, category, -rank AS score, '
                f'snippet({self.table}, {BODY_COLUMN}, \'…\', \'…\', \'…\', 20) AS snippet '
                f'FROM {self.table} WHERE {self.table} MATCH ? ORDER BY rank LIMIT ?',
                (match, int(top_k)),
            ).fetchall()
        except sqlite3.Error as err:
            # A query FTS5 refuses must read as "no answer", never as a crash in
            # the middle of a ticket
            log.warning('kb: pencarian %r gagal: %s', query[:60], err)
            return []
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        row = self.con.execute(f'SELECT COUNT(*) FROM {self.table}').fetchone()
        return {'articles': int(row[0]) if row else 0, 'table': self.table}

    def close(self) -> None:
        if self._own:
            self.con.close()


def default_kb() -> SQLiteKB:
    """The KB on the business DB, seeded with the shipped FAQ when empty."""
    kb = SQLiteKB()
    kb.seed()
    return kb
