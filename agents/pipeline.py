"""pipeline.py - one episode, eight characters, from source file to `live`.

    python -m agents.pipeline --source ~/media/incoming/one-piece-s01e12.mp4

Order (AGENTS.md §4.2): Scraper → Metadata → Encoder → Subtitle →
TranslationAgent → QualityChecker → EpisodeScheduler → (Notifier once live).

The office is a view, never a dependency (ADR-3): without `OFFICE_TOKEN` the run
is headless and still does all the work. Each agent's state goes to
`context["episode:<id>"]`, so a later step (or a person) can see where it stopped.

Encoder: `HERMES_ENCODER=ffmpeg` (default) needs ffmpeg; `copy` is the dev
fallback and records `encode_mode: copy` in the episode, never pretending it
transcoded anything.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import config, media, store
from .base import Agent
from .episode_scheduler import publish_due_episodes, schedule_episode
from .notifier import notify

log = logging.getLogger('agents.pipeline')


class PipelineError(RuntimeError):
    """A step refused to continue; the episode keeps its last good state."""


def _episode_id(source: Path, override: str | None) -> str:
    return (override or media.episode_id_from(source) or source.stem).strip().lower()


# ---------------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------------

def scraper(source: Path, episode_id: str) -> dict:
    with Agent('Scraper', f'Ambil episode {episode_id}') as a:
        a.update('check_duplicate', tool='check_duplicate')
        existing = store.get_episode(episode_id)
        if existing and existing.get('status') in ('scheduled', 'live'):
            raise PipelineError(f'{episode_id} sudah {existing["status"]}: duplikat ditolak')
        if not source.exists():
            raise PipelineError(f'source tidak ada: {source}')
        a.update('save_episode', tool='save_episode')
        return store.save_episode(episode_id, {
            'episode_id': episode_id,
            'source_path': str(source),
            'anime_slug': media.anime_slug(source),
            'status': 'fetched',
            'fetched_at': time.time(),
        }, 'Scraper')


def metadata(episode_id: str, source: Path) -> dict:
    with Agent('Metadata', f'Metadata {episode_id}') as a:
        a.update('fetch metadata', tool='update_db')
        meta = media.derive_metadata(source)
        a.update(f'{meta["title"]} ep {meta["episode_number"]} ({meta["metadata_source"]})')
        return store.update_episode(episode_id, {**meta, 'status': 'metadata'}, 'Metadata')


def encoder(episode_id: str, source: Path) -> dict:
    with Agent('Encoder', f'Encode {episode_id}') as a:
        a.update('encode_video', tool='encode_video')
        dest = config.media_root() / 'encoded' / f'{episode_id}.mp4'
        result = media.encode(source, dest)
        a.update(f'encoded ({result["mode"]}, {result["bytes"]} bytes)', tool='upload_cdn')
        return store.update_episode(episode_id, {
            'encoded_path': result['path'],
            'encode_mode': result['mode'],
            'encoded_bytes': result['bytes'],
            'duration_s': media.probe_duration(dest),
            'status': 'encoded',
        }, 'Encoder')


def subtitle(episode_id: str, source: Path) -> dict:
    with Agent('Subtitle', f'Subtitle {episode_id}') as a:
        a.update('fetch_subtitle', tool='fetch_subtitle')
        src = media.find_subtitle(source, 'id')
        cues = media.parse_subtitle(src)
        if not cues:
            raise PipelineError(f'tidak ada cue yang terbaca di {src.name}')
        a.update(f'{len(cues)} cue, sync + encoding', tool='sync_timing')
        out = media.write_srt(cues, config.media_root() / 'subs' / f'{episode_id}.id.srt')
        con = store.connect()
        store.upsert_track(con, episode_id, 'id', str(out), source='source', status='ready', updated_at=time.time())
        return store.update_episode(episode_id, {
            'subtitle_id_path': str(out), 'subtitle_cues': len(cues), 'status': 'subtitled',
        }, 'Subtitle')


def translation(episode_id: str, *, approve_sub: bool = False) -> dict:
    with Agent('TranslationAgent', f'Terjemahkan {episode_id}') as a:
        a.update('fetch_raw_subtitle', tool='fetch_raw_subtitle')
        ep = store.get_episode(episode_id) or {}
        raw = Path(ep.get('subtitle_id_path') or '')
        if not raw.exists():
            raise PipelineError('subtitle Indonesia belum ada: jalankan Subtitle dulu')
        cues = media.parse_srt(media.read_text(raw))
        a.update(f'translate_text ({len(cues)} cue)', tool='translate_text')
        translated, score = media.translate_lines(cues)
        a.update(f'qa_translation skor {score}', tool='qa_translation')

        approved = True
        if score < config.qa_threshold() and not approve_sub:
            decision = a.ask(
                f'QA terjemahan {score} di bawah {config.qa_threshold()}. Lanjutkan?',
                ['Approve & Lanjutkan', 'Reject & Translate Ulang'],
                timeout=3600,
            )
            approved = decision.startswith('Approve')
            if not approved:
                con = store.connect()
                store.set_track_status(con, episode_id, 'en', 'rejected', time.time())
                store.update_episode(episode_id, {'status': 'translation_rejected', 'qa_score': score}, 'TranslationAgent')
                raise PipelineError(f'terjemahan ditolak ({decision})')

        out = media.write_srt(translated, config.media_root() / 'subs' / f'{episode_id}.en.srt')
        con = store.connect()
        store.upsert_track(con, episode_id, 'en', str(out), source='local', status='approved' if approved else 'ready',
                           qa_score=score, updated_at=time.time())
        a.update(f'save_translated_sub ({score})', tool='save_translated_sub')
        return store.update_episode(episode_id, {
            'subtitle_en_path': str(out), 'qa_score': score,
            'status': 'translated',
        }, 'TranslationAgent')


def quality(episode_id: str) -> dict:
    with Agent('QualityChecker', f'QC {episode_id}') as a:
        a.update('check_stream', tool='check_stream')
        ep = store.get_episode(episode_id) or {}
        problems: list[str] = []
        encoded = Path(ep.get('encoded_path') or '')
        if not encoded.exists() or encoded.stat().st_size == 0:
            problems.append('encoded file hilang/0 byte')
        con = store.connect()
        tracks = store.tracks(con, episode_id)
        if not tracks:
            problems.append('tidak ada subtitle track')
        for track in tracks:
            if track['status'] not in ('ready', 'approved'):
                problems.append(f'subtitle {track["lang"]} berstatus {track["status"]}')
            if not Path(track['path']).exists():
                problems.append(f'subtitle {track["lang"]} hilang di disk')
        if problems:
            attempts = int(ep.get('qc_attempts') or 0) + 1
            patch = {'qc_attempts': attempts, 'qc_problems': problems}
            if attempts >= 2:
                patch['status'] = 'failed'
                store.context().set(f'handoff:QualityChecker:Orchestrator:{episode_id}', {
                    'episode_id': episode_id, 'problems': problems, 'attempt': attempts,
                }, 'QualityChecker')
            store.update_episode(episode_id, patch, 'QualityChecker')
            raise PipelineError('QC gagal: ' + '; '.join(problems))
        a.update('check_subtitle_sync ok', tool='check_subtitle_sync')
        return store.update_episode(episode_id, {'status': 'qc_passed', 'qc_problems': []}, 'QualityChecker')


def schedule(episode_id: str, embargo_seconds: float) -> dict:
    with Agent('EpisodeScheduler', f'Jadwalkan {episode_id}') as a:
        ep = store.get_episode(episode_id) or {}
        con = store.connect()
        embargo_until = time.time() + max(0.0, float(embargo_seconds))
        a.update(f'queue_episode (embargo {int(embargo_seconds)}s)', tool='queue_episode')
        schedule_episode(
            con,
            episode_id=episode_id,
            anime_title=str(ep.get('title') or episode_id),
            episode_number=int(ep.get('episode_number') or 0),
            encoded_path=str(ep.get('encoded_path') or ''),
            embargo_until=embargo_until,
        )
        a.update('check_embargo', tool='check_embargo')
        published = publish_due_episodes(con) if embargo_seconds <= 0 else []
        went_live = any(row['episode_id'] == episode_id for row in published)
        a.update('live' if went_live else 'scheduled', tool='trigger_publish')
        return store.update_episode(episode_id, {
            'status': 'live' if went_live else 'scheduled',
            'embargo_until': embargo_until,
        }, 'EpisodeScheduler')


def announce(episode_id: str) -> dict:
    with Agent('Notifier', f'Umumkan {episode_id}') as a:
        ep = store.get_episode(episode_id) or {}
        a.update('push_notif', tool='push_notif')
        result = notify({**ep, 'episode_id': episode_id})
        a.update('update_rss' if result['feed'] else 'rss gagal', tool='update_rss')
        channels = [name for name in ('discord', 'telegram') if result[name]]
        return store.update_episode(episode_id, {
            'status': 'live', 'notified': True, 'notified_channels': channels,
        }, 'Notifier')


# ---------------------------------------------------------------------------
# Whole run
# ---------------------------------------------------------------------------

def run_episode(source: Path, *, episode_id: str | None = None, embargo_seconds: float = 0,
                approve_sub: bool = False) -> dict:
    """Run the eight steps in order and return what the episode ended as."""
    eid = _episode_id(source, episode_id)
    log.info('episode %s dari %s', eid, source)
    scraper(source, eid)
    metadata(eid, source)
    encoder(eid, source)
    subtitle(eid, source)
    translation(eid, approve_sub=approve_sub)
    quality(eid)
    ep = schedule(eid, embargo_seconds)
    if ep['status'] == 'live':
        announce(eid)
    return store.get_episode(eid) or ep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Jalankan pipeline satu episode (W3)')
    parser.add_argument('--source', required=True, help='file video episode (SxxEyy di nama)')
    parser.add_argument('--episode', help='override episode id')
    parser.add_argument('--embargo', type=float, default=0, help='detik embargo sebelum live')
    parser.add_argument('--approve-sub', action='store_true', help='lewati kartu approval terjemahan')
    parser.add_argument('--json', action='store_true', help='cetak episode sebagai JSON')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    try:
        ep = run_episode(Path(args.source).expanduser(), episode_id=args.episode,
                         embargo_seconds=args.embargo, approve_sub=args.approve_sub)
    except PipelineError as err:
        print(f'pipeline berhenti: {err}', file=sys.stderr)
        return 1
    print(json.dumps(ep, ensure_ascii=False, indent=2, default=str) if args.json
          else f'{ep["episode_id"]}: {ep["status"]} ({ep.get("encoded_path")})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
