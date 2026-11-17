"""seo.py - SEOAgent: the crawlable files for what actually went live.

Tools from AGENTS.md §4.4: `update_meta`, `update_sitemap`,
`add_structured_data`. All three read `episode_schedule` (real rows, status
`live`) and write files under `media/published/`:

    meta/<episode_id>.json     <title>/og values for one episode
    sitemap.xml                every live episode, newest lastmod first
    structured-data.json       JSON-LD TVEpisode list for the same episodes

Why files and not an API call: the AniWatch site is outside this fork and has no
meta endpoint documented anywhere. The files are a contract the site reads from
the same folder as `feed.xml`; uploading them is the site's job, and the result
records `base_url: relative` when `SEO_SITE_URL`/`CDN_BASE_URL` is empty so no
one believes absolute URLs were published.
"""

from __future__ import annotations

import html
import json
import logging
import sqlite3
import time
import xml.sax.saxutils as saxutils
from pathlib import Path
from typing import Any

from . import config, growth_data

log = logging.getLogger(__name__)

META_DIR = 'meta'


class SEOAgent:
    """Writes meta, sitemap and structured data for live episodes."""

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

    # -- helpers ------------------------------------------------------------

    def _base_url(self) -> str:
        """`SEO_SITE_URL`, then `CDN_BASE_URL`, then empty (= relative links)."""
        return config.seo_site_url() or config.cdn_base_url()

    def _live_episodes(self) -> list[dict]:
        rows = self.con().execute(
            "SELECT episode_id, anime_title, episode_number, encoded_path, published_at "
            "FROM episode_schedule WHERE status='live' "
            'ORDER BY COALESCE(published_at, created_at) DESC'
        ).fetchall()
        return [dict(row) for row in rows]

    def _url(self, episode_id: str) -> str:
        base = self._base_url()
        return f'{base}/watch/{episode_id}' if base else f'/watch/{episode_id}'

    # -- the tools ----------------------------------------------------------

    def update_meta(self, episode: dict, now: float | None = None) -> Path:
        """One `<title>`/og record per episode, derived from its schedule row."""
        at = time.time() if now is None else float(now)
        episode_id = str(episode['episode_id'])
        title = f'{episode.get("anime_title") or episode_id} Episode {episode.get("episode_number", "?")}'
        record = {
            'episode_id': episode_id,
            'title': title,
            'description': f'Nonton {title} sub Indo di AniWatch.',
            'url': self._url(episode_id),
            'image': (f'{config.cdn_base_url()}/{Path(episode.get("encoded_path") or "").stem}.jpg'
                      if config.cdn_base_url() else None),
            'updated_at': at,
        }
        path = growth_data.write_json(f'{META_DIR}/{episode_id}.json', record)
        log.info('seo: meta %s', path)
        return path

    def update_sitemap(self, now: float | None = None) -> tuple[Path, int]:
        """A sitemap of live episodes only; `cancelled` ones must not be listed."""
        at = time.time() if now is None else float(now)
        episodes = self._live_episodes()
        base = self._base_url() or ''
        entries = [f'<url><loc>{saxutils.escape(base + "/")}</loc></url>']
        for episode in episodes:
            lastmod = episode.get('published_at') or at
            entries.append(
                f'<url><loc>{saxutils.escape(self._url(episode["episode_id"]))}</loc>'
                f'<lastmod>{time.strftime("%Y-%m-%d", time.localtime(float(lastmod)))}</lastmod></url>'
            )
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + ''.join(entries) + '</urlset>\n')
        path = config.media_root() / 'published' / 'sitemap.xml'
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        log.info('seo: sitemap %d url (base=%r)', len(entries), base or 'relative')
        return path, len(entries)

    def add_structured_data(self, now: float | None = None) -> Path:
        """JSON-LD `TVEpisode` records, one per live episode, for the site to embed."""
        at = time.time() if now is None else float(now)
        episodes = self._live_episodes()
        records = [{
            '@context': 'https://schema.org',
            '@type': 'TVEpisode',
            'name': html.escape(
                f'{episode.get("anime_title") or episode["episode_id"]} '
                f'Episode {episode.get("episode_number", "?")}'),
            'url': self._url(episode['episode_id']),
            'episodeNumber': episode.get('episode_number'),
            'datePublished': time.strftime(
                '%Y-%m-%dT%H:%M:%SZ',
                time.gmtime(float(episode.get('published_at') or at)),
            ),
        } for episode in episodes]
        path = growth_data.write_json('structured-data.json', records)
        log.info('seo: structured data %d episode', len(records))
        return path

    def update_site(self, episode: dict | None = None, char: Any = None,
                    now: float | None = None) -> dict:
        """The whole pass, used at the end of the episode pipeline.

        `episode` is written first: its meta record exists even when the sitemap
        pass that follows fails, so no live episode is missing its title.
        """
        meta = None
        if episode and episode.get('episode_id'):
            if char:
                char.update(f'update_meta {episode["episode_id"]}', tool='update_meta')
            meta = self.update_meta(episode, now=now)
        if char:
            char.update('update_sitemap + add_structured_data', tool='update_sitemap')
        sitemap, urls = self.update_sitemap(now=now)
        structured = self.add_structured_data(now=now)
        return {
            'meta': str(meta) if meta else None,
            'sitemap': str(sitemap),
            'sitemap_urls': urls,
            'structured_data': str(structured),
            'base_url': self._base_url() or 'relative',
        }
