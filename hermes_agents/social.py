"""social.py - SocialMediaAgent: one post per channel when an episode is out.

Tools from AGENTS.md §4.4: `post_discord`, `post_telegram`, `post_twitter`,
plus `announce_episode` for the end of the pipeline and `post_content` for
`content_schedule`.

Why the channel post lives here and not in `notifier.py`: Notifier's job is the
feed and the subscriber log (`notifications.jsonl`, `feed.xml`), SocialMedia's
job is the platforms. Splitting them keeps one message per platform per episode
instead of two accounts posting the same link.

One episode, one post per channel: what already went out is recorded in
SharedContext (`social:<episode_id>`), so an `announce_episode` webhook that
arrives after the pipeline published does not repeat the post. A failed send is
not recorded, so the next attempt is allowed to try again.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import channels, config, store

log = logging.getLogger(__name__)

MAX_TEXT = 1800


def announcement(episode: dict) -> str:
    """The line that goes out. Built once, so every platform says the same thing."""
    title = (episode.get('title') or episode.get('anime_title')
             or episode.get('episode_id') or 'Episode baru')
    number = episode.get('episode_number')
    heading = f'🎬 {title} Episode {number}' if number not in (None, '') else f'🎬 {title}'
    base = config.cdn_base_url()
    encoded = str(episode.get('encoded_path') or '')
    link = f'{base}/{encoded.rsplit("/", 1)[-1]}' if (base and encoded) else ''
    lines = [heading, 'Sudah tayang di AniWatch — sub Indo.']
    if link:
        lines.append(link)
    return '\n'.join(lines)[:MAX_TEXT]


class SocialMediaAgent:
    """Posts one announcement to every platform, remembering what already went."""

    def __init__(self, context=None) -> None:
        self._context = context

    def context(self):
        return self._context if self._context is not None else store.context()

    def _posted_before(self, episode_id: str) -> dict:
        value = self.context().get(key(episode_id))
        return value if isinstance(value, dict) else {}

    def post_all(self, text: str, episode_id: str | None = None) -> dict:
        """Post `text` everywhere it has not gone yet; returns posted/skipped.

        `skip` maps platform -> reason, and an already-posted platform is skipped
        with `sudah diposting` rather than sent a second time (AGENT-HANDOFFS §5.1
        in spirit: one post, one recipient).
        """
        already = self._posted_before(episode_id) if episode_id else {}
        posted: list[str] = []
        skipped: dict[str, str] = {}
        for name, outcome in channels.post_all(text).items():
            if already.get(name):
                skipped[name] = 'sudah diposting untuk episode ini'
                continue
            if outcome['posted']:
                posted.append(name)
            else:
                skipped[name] = str(outcome.get('reason') or 'gagal')
        if episode_id and posted:
            merged = {**already, **{name: True for name in posted}, 'at': time.time()}
            try:
                self.context().set(key(episode_id), merged, 'SocialMedia')
            except Exception as err:  # noqa: BLE001 - a post that went out is already out
                log.warning('social: %s terkirim tapi tidak tercatat: %s', episode_id, err)
        return {'posted': posted, 'skipped': skipped}

    def announce_episode(self, episode: dict, char: Any = None) -> dict:
        """`announce_episode` on one live episode."""
        episode_id = str(episode.get('episode_id') or '').strip()
        if not episode_id:
            return {'action': 'skipped', 'posted': [], 'skipped': {'episode': 'episode_id kosong'}}
        text = announcement(episode)
        if char:
            char.update(f'post_discord + post_telegram: {episode_id}'[:190], tool='post_discord')
        result = self.post_all(text, episode_id=episode_id)
        log.info('social: %s -> %s (dilewati: %s)', episode_id,
                 result['posted'] or 'tidak ada channel', result['skipped'])
        return {'action': 'announced' if result['posted'] else 'not_sent',
                'episode_id': episode_id, **result}

    def post_content(self, payload: object, char: Any = None) -> dict:
        """`content_schedule`: a post someone wrote, with no episode behind it."""
        data = payload if isinstance(payload, dict) else {}
        text = str(data.get('text') or data.get('content') or data.get('message') or '').strip()
        if not text:
            return {'action': 'skipped', 'posted': [], 'skipped': {'text': 'isi post kosong'}}
        if char:
            char.update('post konten terjadwal', tool='post_telegram')
        result = self.post_all(text[:MAX_TEXT])
        return {'action': 'posted' if result['posted'] else 'not_sent', **result}


def key(episode_id: str) -> str:
    """SharedContext key: what already went out for this episode."""
    return f'social:{episode_id}'


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point for `announce_episode` and `content_schedule`."""
    data = payload if isinstance(payload, dict) else {}
    agent = SocialMediaAgent()
    if data.get('episode_id') or data.get('title'):
        # An episode announcement: the payload is the episode (or names one we
        # already know), which is what the pipeline hands over as well
        episode = dict(data)
        if not episode.get('title') and episode.get('episode_id'):
            known = store.get_episode(str(episode['episode_id'])) or {}
            episode = {**known, **episode}
        return agent.announce_episode(episode, char=char)
    return agent.post_content(data, char=char)
