"""selfcheck.py - prove W3 works on a bare machine, no office and no network.

    python -m agents.selfcheck

Everything runs in a throwaway directory (`HERMES_MEDIA_DIR`, `HERMES_DB`,
`SHARED_DB`, `DLQ_DB`), so it never touches the real episode data. It is the
acceptance list from PLAN.md W3 in executable form: one episode to `live`, the
embargo queue publishing only what is still `scheduled`, DMCA's cancel keeping
an episode off, and the duplicate guard.

The character side is not checked here: run `python -m agents.pipeline
--source ...` with the office up for that (`tests` of the office side live in
tests/*.ts).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    print(f'{"PASS" if condition else "FAIL"}  {name}{f" - {detail}" if detail and not condition else ""}')
    if not condition:
        FAILS.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='hermes-selfcheck-'))
    os.environ.update({
        'HERMES_MEDIA_DIR': str(tmp / 'media'),
        'HERMES_DB': str(tmp / 'hermes.db'),
        'SHARED_DB': str(tmp / 'shared.db'),
        'DLQ_DB': str(tmp / 'dlq.db'),
        'HERMES_GLOSSARY': str(tmp / 'glossary.json'),
        'HERMES_ENCODER': 'copy',
        'TRANSLATION_PROVIDER': 'local',
        'TRANSLATION_QA_THRESHOLD': '0.75',
        'OFFICE_TOKEN': '',
    })
    (tmp / 'glossary.json').write_text(
        '{"Selamat datang di episode baru":"Welcome to the new episode",'
        '"Petualangan dimulai sekarang":"The adventure begins now"}',
        encoding='utf-8',
    )

    from agents import config, media, pipeline, store
    from agents import episode_scheduler as sched

    # 1. File parsing -------------------------------------------------------
    check('episode id from filename', media.episode_id_from(Path('one-piece-s01e12.mp4')) == 'one-piece-s01e12')
    check('srt timing parsed', media.parse_srt('1\n00:00:01,000 --> 00:00:03,000\nhalo\n')[0].text == 'halo')
    ass = 'Dialogue: 0,0:00:04.50,0:00:06.00,Default,,0,0,0,,{\\pos(1,2)}hai\n'
    check('ass dialogue parsed', media.parse_ass(ass)[0].start == '00:00:04,500')

    # 2. One episode, all the way to live ----------------------------------
    incoming = config.media_root() / 'incoming'
    video = incoming / 'selfcheck-show-s01e01.mp4'
    video.write_bytes(b'\x00' * 2048)
    video.with_suffix('.id.srt').write_text(
        '1\n00:00:01,000 --> 00:00:03,000\nSelamat datang di episode baru\n\n'
        '2\n00:00:04,000 --> 00:00:06,000\nPetualangan dimulai sekarang\n',
        encoding='utf-8',
    )
    video.with_suffix('.json').write_text('{"title":"Selfcheck Show","episode_number":1}', encoding='utf-8')

    ep = pipeline.run_episode(video)
    check('episode live after the run', ep['status'] == 'live', str(ep.get('status')))
    check('encoded file written', Path(ep['encoded_path']).exists())
    check('encode mode is recorded', ep['encode_mode'] == 'copy')
    tracks = {t['lang']: t for t in store.tracks(store.connect(), ep['episode_id'])}
    check('indonesian track ready', tracks.get('id', {}).get('status') == 'ready')
    check('english track approved', tracks.get('en', {}).get('status') == 'approved')
    check('translation scored 1.0', tracks.get('en', {}).get('qa_score') == 1.0)
    check('feed written', (config.media_root() / 'published' / 'feed.xml').exists())
    check('notification logged', (config.media_root() / 'published' / 'notifications.jsonl').exists())

    # 3. Duplicate guard ---------------------------------------------------
    try:
        pipeline.scraper(video, ep['episode_id'])
        check('duplicate refused', False, 'no error')
    except pipeline.PipelineError:
        check('duplicate refused', True)

    # 4. Embargo: publish only what is still scheduled ---------------------
    con = store.connect()
    cancelled = 'selfcheck-cancel-s01e01'
    sched.schedule_episode(con, episode_id=cancelled, anime_title='Cancel',
                           episode_number=1, encoded_path='/tmp/x.mp4',
                           embargo_until=time.time() + 3600)
    check('schedule lands as scheduled', sched.get_schedule(con, cancelled)['status'] == 'scheduled')
    check('DMCA cancel returns True', sched.cancel_schedule(con, cancelled, 'DMCA palsu'))
    published = [r['episode_id'] for r in sched.publish_due_episodes(con, time.time() + 7200)]
    check('cancelled episode never publishes', cancelled not in published)
    check('cancelled stays cancelled', sched.get_schedule(con, cancelled)['status'] == 'cancelled')

    due = 'selfcheck-due-s01e01'
    sched.schedule_episode(con, episode_id=due, anime_title='Due', episode_number=1,
                           encoded_path='/tmp/y.mp4', embargo_until=time.time() - 1)
    check('due episode publishes', any(r['episode_id'] == due for r in sched.publish_due_episodes(con)))
    check('publish is not repeated', sched.publish_due_episodes(con) == [])

    # 5. QC failure is recorded, and twice means failed --------------------
    quality = 'selfcheck-qc-s01e01'
    store.save_episode(quality, {'episode_id': quality, 'encoded_path': '/nonexistent.mp4'}, 'selfcheck')
    for attempt in (1, 2):
        try:
            pipeline.quality(quality)
        except pipeline.PipelineError:
            pass
        status = (store.get_episode(quality) or {}).get('status')
        expected = 'failed' if attempt == 2 else None
        check(f'qc attempt {attempt} recorded', (status == expected) if expected else bool(store.get_episode(quality)))
    check('qc twice marks failed', (store.get_episode(quality) or {}).get('status') == 'failed')
    check('handoff written on failure',
          store.context().get(f'handoff:QualityChecker:Orchestrator:{quality}') is not None)

    print()
    if FAILS:
        print(f'{len(FAILS)} check(s) failed: {", ".join(FAILS)}')
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
