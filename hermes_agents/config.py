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
