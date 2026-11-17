"""channels.py - one function per outbound platform, and an honest skip.

Every function returns `{posted: bool, reason: str | None}`: a missing webhook or
token is a skip with the variable named, never a silent success. That shape is
what `social.py` records per episode and what the log line shows, so "why did
this episode not reach Telegram" has one answer in one place.

Twitter/X has no posting function on purpose: `TWITTER_BEARER_TOKEN` can only
read, and posting needs an OAuth 2.0 user context this fork does not have
(ENV-VARS.md §3). It is reported as `belum diimplementasikan`, not faked.
"""

from __future__ import annotations

import logging

from . import config

log = logging.getLogger(__name__)

POST_TIMEOUT_S = 15
DISCORD_MAX = 1900
TELEGRAM_MAX = 4000


def discord(text: str) -> dict:
    """Post one message to `DISCORD_WEBHOOK_URL`."""
    url = config.discord_webhook()
    if not url:
        return {'posted': False, 'reason': 'DISCORD_WEBHOOK_URL kosong'}
    import httpx

    try:
        res = httpx.post(url, json={'content': text[:DISCORD_MAX]}, timeout=POST_TIMEOUT_S)
        res.raise_for_status()
        return {'posted': True, 'reason': None}
    except Exception as err:  # noqa: BLE001 - one channel down is not a failed episode
        log.warning('channels: Discord gagal: %s', err)
        return {'posted': False, 'reason': str(err)[:160]}


def telegram(text: str) -> dict:
    """Post one message to the configured Telegram channel."""
    token, chat = config.telegram()
    if not (token and chat):
        missing = 'TELEGRAM_BOT_TOKEN' if not token else 'TELEGRAM_CHANNEL_ID'
        return {'posted': False, 'reason': f'{missing} kosong'}
    import httpx

    try:
        res = httpx.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat, 'text': text[:TELEGRAM_MAX]},
            timeout=POST_TIMEOUT_S,
        )
        res.raise_for_status()
        return {'posted': True, 'reason': None}
    except Exception as err:  # noqa: BLE001
        log.warning('channels: Telegram gagal: %s', err)
        return {'posted': False, 'reason': str(err)[:160]}


def twitter(_text: str) -> dict:
    """X/Twitter posting is not implemented; say so instead of dropping the post."""
    return {'posted': False, 'reason': 'posting X belum diimplementasikan (bearer token hanya bisa baca)'}


#: The platforms a post goes to, in the order results are reported
PLATFORMS = ('discord', 'telegram', 'twitter')


def post_all(text: str) -> dict[str, dict]:
    """Post `text` to every platform; the result maps platform -> outcome."""
    senders = {'discord': discord, 'telegram': telegram, 'twitter': twitter}
    return {name: senders[name](text) for name in PLATFORMS}
