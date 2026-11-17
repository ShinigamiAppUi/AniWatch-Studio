"""media.py - the deterministic file work the pipeline agents do.

Everything here is local and injectable: no network, no office. `encode()` uses
`ffmpeg` unless `HERMES_ENCODER=copy`, which exists for a dev box without
ffmpeg and records itself in the result (`mode: copy`) so an episode's row never
claims a transcode that did not happen.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

EPISODE_RE = re.compile(r'(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-s(?P<season>\d{2})e(?P<episode>\d{2,3})', re.IGNORECASE)
SRT_TIME = re.compile(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})')


class MediaError(RuntimeError):
    """A file is missing or unusable; the agent reports it, it does not guess."""


# ---------------------------------------------------------------------------
# Naming and metadata
# ---------------------------------------------------------------------------

def episode_id_from(path: Path) -> str:
    """`one-piece-s01e12.mp4` -> `one-piece-s01e12`; "" when the name has no SxxEyy."""
    m = EPISODE_RE.search(path.stem)
    return m.group(0).lower() if m else ''


def episode_number(path: Path) -> int:
    m = EPISODE_RE.search(path.stem)
    return int(m.group('episode')) if m else 0


def anime_slug(path: Path) -> str:
    m = EPISODE_RE.search(path.stem)
    return m.group('slug') if m else path.stem


def read_sidecar(path: Path) -> dict:
    """The `<episode>.json` next to the video, when the source shipped one."""
    sidecar = path.with_suffix('.json')
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def derive_metadata(path: Path) -> dict:
    """Sidecar fields when present, else what the filename itself says.

    Why no MAL/AniList call: those need a key, and a pipeline that fails without
    one cannot run on a fresh machine. The sidecar is the source of truth; the
    filename is the honest fallback (title from the slug, episode number).
    """
    sidecar = read_sidecar(path)
    slug = anime_slug(path)
    title = sidecar.get('title') or ' '.join(part.capitalize() for part in slug.split('-'))
    return {
        'title': str(title)[:200],
        'episode_number': int(sidecar.get('episode_number') or episode_number(path)),
        'synopsis': str(sidecar.get('synopsis') or '')[:2000],
        'genres': [str(g)[:40] for g in (sidecar.get('genres') or [])][:10],
        'rating': sidecar.get('rating'),
        'thumbnail': str(sidecar.get('thumbnail') or '')[:400],
        'metadata_source': 'sidecar' if sidecar else 'filename',
    }


# ---------------------------------------------------------------------------
# Encode + probe
# ---------------------------------------------------------------------------

def encode(src: Path, dest: Path) -> dict:
    """Encode `src` to 720p H.264 at `dest`, or copy it in dev mode."""
    if not src.exists() or src.stat().st_size == 0:
        raise MediaError(f'source tidak ada atau kosong: {src}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    mode = config.encoder()
    if mode == 'copy':
        shutil.copyfile(src, dest)
        return {'path': str(dest), 'mode': 'copy', 'bytes': dest.stat().st_size}
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise MediaError('ffmpeg tidak ada di PATH (set HERMES_ENCODER=copy untuk dev)')
    cmd = [
        ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(src),
        '-vf', 'scale=-2:720', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise MediaError(f'ffmpeg gagal ({proc.returncode}): {(proc.stderr or "").strip()[:300]}')
    return {'path': str(dest), 'mode': 'ffmpeg', 'bytes': dest.stat().st_size}


def probe_duration(path: Path) -> float | None:
    """Seconds, when ffprobe is available; None otherwise (never guessed)."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe or not path.exists():
        return None
    try:
        out = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        return float(json.loads(out.stdout or '{}').get('format', {}).get('duration') or 0) or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------

@dataclass
class Cue:
    start: str
    end: str
    text: str


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise MediaError(f'encoding subtitle tidak dikenali: {path}')


def parse_srt(text: str) -> list[Cue]:
    """Blocks separated by blank lines; a block without a timing line is skipped."""
    cues: list[Cue] = []
    for block in re.split(r'\r?\n\r?\n+', text.replace('\r\n', '\n')):
        lines = [ln for ln in block.split('\n') if ln.strip()]
        if not lines:
            continue
        i = 0
        if lines[0].strip().isdigit():
            i = 1
        if i >= len(lines) or not SRT_TIME.search(lines[i]):
            continue
        m = SRT_TIME.search(lines[i])
        assert m is not None
        cues.append(Cue(
            start=':'.join(m.groups()[:3]) + ',' + m.group(4),
            end=':'.join(m.groups()[4:7]) + ',' + m.group(8),
            text=' '.join(ln.strip() for ln in lines[i + 1:])[:500],
        ))
    return cues


def parse_ass(text: str) -> list[Cue]:
    """`Dialogue:` lines of an .ass file, in the shape the rest of the pipeline reads."""
    cues: list[Cue] = []
    for line in text.replace('\r\n', '\n').split('\n'):
        if not line.lower().startswith('dialogue:'):
            continue
        parts = line.split(',', 9)
        if len(parts) < 10:
            continue
        start, end, body = parts[1].strip(), parts[2].strip(), parts[9]
        body = re.sub(r'\{[^}]*\}', '', body).strip()  # drop {\pos(...)} style overrides
        if not body:
            continue
        cues.append(Cue(_ass_time(start), _ass_time(end), body[:500]))
    return cues


def _ass_time(value: str) -> str:
    """`0:00:01.00` -> `00:00:01,000` (SRT's shape)."""
    m = re.match(r'(\d+):(\d{2}):(\d{2})[.:](\d{1,2})', value.strip())
    if not m:
        return '00:00:00,000'
    h, mi, se, cs = m.groups()
    return f'{int(h):02d}:{mi}:{se},{int(cs.ljust(2, "0")) * 10:03d}'


def parse_subtitle(path: Path) -> list[Cue]:
    """SRT or ASS, by extension; one entry point for the Subtitle agent."""
    text = read_text(path)
    return parse_ass(text) if path.suffix.lower() == '.ass' else parse_srt(text)


def write_srt(cues: list[Cue], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = '\n\n'.join(f'{i + 1}\n{c.start} --> {c.end}\n{c.text}' for i, c in enumerate(cues))
    path.write_text(body + '\n', encoding='utf-8')
    return path


def find_subtitle(video: Path, lang: str = 'id') -> Path:
    """`<stem>.<lang>.srt`, `<stem>.srt`, or `<stem>.<lang>.ass` next to the video."""
    for name in (f'{video.stem}.{lang}.srt', f'{video.stem}.srt', f'{video.stem}.{lang}.ass', f'{video.stem}.ass'):
        candidate = video.with_name(name)
        if candidate.exists():
            return candidate
    raise MediaError(f'subtitle {lang} tidak ditemukan di sebelah {video.name}')


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

class MissingCredentials(MediaError):
    """The chosen provider needs a key that is not set (never silently swapped)."""


def _glossary() -> dict[str, str]:
    path = config.glossary_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return {str(k).casefold(): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def translate_lines(cues: list[Cue], provider: str | None = None) -> tuple[list[Cue], float]:
    """Translate the cues and score how much actually changed.

    `local` uses the glossary only (`HERMES_GLOSSARY`, default
    ~/.hermes-office/glossary/id-en.json) and leaves a line untouched when the
    glossary has no entry — it is a glossary, not a translator, and the score
    says so. `deepl` / `openai` need their API key and call that service.
    """
    provider = (provider or config.translation_provider()).lower()
    if provider in ('deepl', 'openai'):
        return _translate_remote(cues, provider)

    glossary = _glossary()
    out: list[Cue] = []
    changed = 0
    for cue in cues:
        key = cue.text.strip().casefold()
        translated = glossary.get(key)
        if translated is None:
            out.append(cue)
            continue
        changed += 1
        out.append(Cue(cue.start, cue.end, translated))
    score = (changed / len(cues)) if cues else 0.0
    return out, round(score, 3)


def _translate_remote(cues: list[Cue], provider: str) -> tuple[list[Cue], float]:
    import os

    key = (os.environ.get('DEEPL_API_KEY') if provider == 'deepl' else os.environ.get('OPENAI_API_KEY')) or ''
    if not key.strip():
        raise MissingCredentials(f'{provider} butuh API key; kosong (atau pakai TRANSLATION_PROVIDER=local)')
    import httpx

    out: list[Cue] = []
    changed = 0
    for cue in cues:
        try:
            if provider == 'deepl':
                res = httpx.post(
                    'https://api-free.deepl.com/v2/translate',
                    data={'text': cue.text, 'source_lang': 'ID', 'target_lang': 'EN-US'},
                    headers={'Authorization': f'DeepL-Auth-Key {key}'},
                    timeout=30,
                )
                res.raise_for_status()
                text = res.json()['translations'][0]['text']
            else:
                res = httpx.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={'Authorization': f'Bearer {key}'},
                    json={
                        'model': os.environ.get('TRANSLATION_MODEL') or 'gpt-4o-mini',
                        'messages': [
                            {'role': 'system', 'content': 'Translate Indonesian subtitles to English. Reply with the translation only.'},
                            {'role': 'user', 'content': cue.text},
                        ],
                    },
                    timeout=60,
                )
                res.raise_for_status()
                text = res.json()['choices'][0]['message']['content'].strip()
        except Exception as err:  # noqa: BLE001 - one bad line must not lose the episode
            raise MediaError(f'{provider} gagal pada satu baris: {err}') from err
        if text and text != cue.text:
            changed += 1
        out.append(Cue(cue.start, cue.end, str(text or cue.text)[:500]))
    score = (changed / len(cues)) if cues else 0.0
    return out, round(score, 3)
