"""notifier.py - tell subscribers an episode is live: the feed and the log.

Always: one line in `media/published/notifications.jsonl` and a rebuilt
`media/published/feed.xml` (RSS 2.0, the same file the site's feed can point
at).

The platform posts are SocialMedia's job (`social.py`, W6): one message per
channel per episode belongs to the agent whose desk is marked 📱, and keeping it
out of here is what stops the same link being posted twice. This module still
reports what it wrote, so a run says `feed`/`log` and nothing it did not do.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from xml.sax.saxutils import escape

from . import config

log = logging.getLogger(__name__)


def _feed_path() -> Path:
    return config.media_root() / 'published' / 'feed.xml'


def _log_path() -> Path:
    return config.media_root() / 'published' / 'notifications.jsonl'


def _public_url(encoded_path: str) -> str:
    base = config.cdn_base_url()
    if base:
        return f'{base}/{Path(encoded_path).name}'
    return encoded_path


def _rebuild_feed(item: dict) -> None:
    path = _feed_path()
    entries = []
    if path.exists():
        # Keep the previous items: the feed is the history, not just this episode
        entries = [ln for ln in path.read_text(encoding='utf-8').split('<item>')[1:] if '</item>' in ln]
    entry = (
        '<item>'
        f'<title>{escape(str(item.get("title") or item["episode_id"]))}</title>'
        f'<guid isPermaLink="false">{escape(item["episode_id"])}</guid>'
        f'<link>{escape(_public_url(item.get("encoded_path", "")))}</link>'
        f'<pubDate>{time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())}</pubDate>'
        f'<description>{escape(str(item.get("synopsis") or "")[:500])}</description>'
        '</item>'
    )
    items = ''.join('<item>' + e for e in entries[:49]) + entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        '<title>AniWatch</title><link>https://aniwatch.example</link>'
        f'<description>Episode terbaru</description>{items}</channel></rss>\n',
        encoding='utf-8',
    )


def notify(episode: dict) -> dict:
    """Write the feed entry and the subscriber log for one live episode.

    Returns `{feed, log, title}`: the two files that were written, and the line
    SocialMedia turns into the channel post (`social.announcement` rebuilds it
    from the episode, so the two never disagree about the link).
    """
    item = {
        'episode_id': episode['episode_id'],
        'title': f'{episode.get("title") or episode.get("anime_title") or episode["episode_id"]} '
                 f'Episode {episode.get("episode_number", "?")}',
        'encoded_path': episode.get('encoded_path', ''),
        'synopsis': episode.get('synopsis', ''),
        'at': time.time(),
    }
    _log_path().parent.mkdir(parents=True, exist_ok=True)
    with _log_path().open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + '\n')
    _rebuild_feed(item)
    return {
        'feed': str(_feed_path()),
        'log': str(_log_path()),
        'title': item['title'],
    }
