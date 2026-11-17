"""config.py - where the pipeline keeps its files and which tools it uses.

No secrets here: API keys come from the environment (ENV-VARS.md). Every value
has a working default so one episode can run on a fresh machine.
"""

from __future__ import annotations

import os
from pathlib import Path


def media_root() -> Path:
    explicit = os.environ.get('HERMES_MEDIA_DIR')
    root = Path(explicit) if explicit else Path.home() / '.hermes-office' / 'media'
    for sub in ('incoming', 'encoded', 'subs', 'thumbnails', 'published'):
        (root / sub).mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def encoder() -> str:
    """`ffmpeg` (default) or `copy` for a dev box without ffmpeg."""
    value = (os.environ.get('HERMES_ENCODER') or 'ffmpeg').strip().lower()
    return value if value in ('ffmpeg', 'copy') else 'ffmpeg'


def translation_provider() -> str:
    return (os.environ.get('TRANSLATION_PROVIDER') or 'local').strip().lower()


def qa_threshold() -> float:
    try:
        return float(os.environ.get('TRANSLATION_QA_THRESHOLD') or 0.75)
    except ValueError:
        return 0.75


def glossary_path() -> Path:
    explicit = os.environ.get('HERMES_GLOSSARY')
    return Path(explicit) if explicit else Path.home() / '.hermes-office' / 'glossary' / 'id-en.json'


def cdn_base_url() -> str:
    return (os.environ.get('CDN_BASE_URL') or '').strip().rstrip('/')


def discord_webhook() -> str:
    return (os.environ.get('DISCORD_WEBHOOK_URL') or '').strip()


def telegram() -> tuple[str, str]:
    return (os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip(), (os.environ.get('TELEGRAM_CHANNEL_ID') or '').strip()


def analytics_feed() -> str:
    """AniWatch's export file: views, watch time and per-user history (W6)."""
    return (os.environ.get('ANALYTICS_FEED') or '').strip()


def recommendation_db() -> str:
    """AniWatch's own SQLite file; the batch writes to it when it is set."""
    return (os.environ.get('RECOMMENDATION_DB') or '').strip()


def seo_site_url() -> str:
    """Public origin for sitemap/meta links, when the site is not the CDN."""
    return (os.environ.get('SEO_SITE_URL') or '').strip().rstrip('/')


def security_event_feed() -> str:
    """Access-event JSONL for SecOps (W9); empty means the request rules cannot run."""
    return (os.environ.get('SECURITY_EVENT_FEED') or '').strip()


def aniwatch_api_url() -> str:
    """AniWatch's admin origin (W11); empty means the roles cannot report anything."""
    return (os.environ.get('ANIWATCH_API_URL') or '').strip().rstrip('/')


def aniwatch_admin_token() -> str:
    """Admin bearer token for the endpoints in W11-SCRAPER-RESOLVER.md §4.7."""
    return (os.environ.get('ANIWATCH_ADMIN_TOKEN') or '').strip()


def scraper_backfill_batch() -> int:
    """Items per hourly backfill (1-500); the ceiling keeps one hour from hammering a site."""
    try:
        value = int(os.environ.get('SCRAPER_BACKFILL_BATCH') or 50)
    except ValueError:
        return 50
    return min(500, max(1, value))
