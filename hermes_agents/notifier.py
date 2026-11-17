"""notifier.py - tell subscribers an episode is live.

Always: one line in `media/published/notifications.jsonl` and a rebuilt
`media/published/feed.xml` (RSS 2.0, the same file the site's feed can point
at). Discord and Telegram are posted only when their env vars are set
(ENV-VARS.md §3): a missing webhook is skipped with a note, never faked.
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


def _post_discord(text: str) -> bool:
    url = config.discord_webhook()
    if not url:
        return False
    import httpx
    try:
        res = httpx.post(url, json={'content': text[:1900]}, timeout=15)
        res.raise_for_status()
        return True
    except Exception as err:  # noqa: BLE001 - one channel down is not an episode failure
        log.warning('notifier: Discord gagal: %s', err)
        return False


def _post_telegram(text: str) -> bool:
    token, chat = config.telegram()
    if not (token and chat):
        return False
    import httpx
    try:
        res = httpx.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat, 'text': text[:4000]},
            timeout=15,
        )
        res.raise_for_status()
        return True
    except Exception as err:  # noqa: BLE001
        log.warning('notifier: Telegram gagal: %s', err)
        return False


def notify(episode: dict) -> dict:
    """Announce one live episode. Returns what actually went out."""
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
    text = f'🎬 {item["title"]} sudah tayang: {_public_url(item["encoded_path"])}'
    return {
        'feed': str(_feed_path()),
        'log': str(_log_path()),
        'discord': _post_discord(text),
        'telegram': _post_telegram(text),
    }
