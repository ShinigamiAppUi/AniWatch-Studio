"""selfcheck.py - prove W3 works on a bare machine, no office and no network.

    python -m hermes_agents.selfcheck

Everything runs in a throwaway directory (`HERMES_MEDIA_DIR`, `HERMES_DB`,
`SHARED_DB`, `DLQ_DB`), so it never touches the real episode data. It is the
acceptance list from PLAN.md W3 in executable form: one episode to `live`, the
embargo queue publishing only what is still `scheduled`, DMCA's cancel keeping
an episode off, and the duplicate guard.

The entry points are checked first, before anything imports the bridge: `.env`
is read by `hermes_bridge/env.py` (called by the sidecar, the pipeline, this
check and the smoke run), and `hermes_bridge.bridge` must do no I/O until
`init()` (ENV-VARS.md §5).

The character side is not checked here: run `python -m hermes_agents.pipeline
--source ...` with the office up for that (`tests` of the office side live in
tests/*.ts).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from hermes_bridge.env import load_env

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    print(f'{"PASS" if condition else "FAIL"}  {name}{f" - {detail}" if detail and not condition else ""}')
    if not condition:
        FAILS.append(name)


def main() -> int:
    # Read `.env` first, then replace what this check needs: every path below
    # points at the throwaway directory, never at real episode data
    load_env()
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
        # No mail goes out of this check, ever: no host, and the outbox is in the
        # throwaway directory
        'SMTP_HOST': '',
        'SMTP_USER': '',
        'SMTP_PASSWORD': '',
        'SMTP_SECURITY': '',
        'SMTP_PORT': '',
        'SUPPORT_FROM': '',
        'HERMES_OUTBOX': str(tmp / 'outbox' / 'replies.jsonl'),
        # Growth (W6): no real post leaves this check either, and the two exports
        # start empty so the "no data yet" path is the one exercised first
        'DISCORD_WEBHOOK_URL': '',
        'TELEGRAM_BOT_TOKEN': '',
        'TELEGRAM_CHANNEL_ID': '',
        'TWITTER_BEARER_TOKEN': '',
        'ANALYTICS_FEED': '',
        'RECOMMENDATION_DB': '',
        'SEO_SITE_URL': '',
        'CDN_BASE_URL': '',
    })
    (tmp / 'glossary.json').write_text(
        '{"Selamat datang di episode baru":"Welcome to the new episode",'
        '"Petualangan dimulai sekarang":"The adventure begins now"}',
        encoding='utf-8',
    )

    # 0. Entry points: `.env` and a bridge that is inert at import ----------
    #    First, because "importing does no I/O" is only provable while
    #    `hermes_bridge.bridge` is not in sys.modules yet (`hermes_bridge.env`
    #    is a different module and imports nothing that talks to a server).
    token_file = tmp / 'token.txt'
    token_file.write_text('tok-from-file\n', encoding='utf-8')
    env_file = tmp / '.env'
    env_file.write_text(
        '# a comment\n'
        'export SELFCHECK_PLAIN=1\n'
        'SELFCHECK_QUOTED="dua kata # bukan komentar"\n'
        'SELFCHECK_DEFAULTED=${SELFCHECK_NOPE:-fallback}\n'
        'SELFCHECK_NESTED=${SELFCHECK_NOPE:-$SELFCHECK_HOME/child}\n'
        f'SELFCHECK_FROMFILE=$(cat "{token_file}")\n'
        'SELFCHECK_COMMENTED=plain # trailing note\n'
        'SELFCHECK_PRESET=from-file\n',
        encoding='utf-8',
    )
    os.environ['SELFCHECK_HOME'] = str(tmp / 'home')
    os.environ['SELFCHECK_PRESET'] = 'from-env'  # already set: the file must not win
    previous_env_file = os.environ.get('HERMES_ENV_FILE')
    os.environ['HERMES_ENV_FILE'] = str(env_file)

    from hermes_bridge.env import load_env as load_dotenv_file

    # 7 assignments in the file, one of them already set: 6 are applied
    check('env: loads the file, skipping the already-set key', load_dotenv_file() == 6)
    check('env: plain and export-prefixed values', os.environ.get('SELFCHECK_PLAIN') == '1')
    check('env: quotes keep a # in the value',
          os.environ.get('SELFCHECK_QUOTED') == 'dua kata # bukan komentar')
    check('env: ${VAR:-default} when the variable is unset',
          os.environ.get('SELFCHECK_DEFAULTED') == 'fallback')
    check('env: a nested default expands',
          os.environ.get('SELFCHECK_NESTED') == f'{tmp}/home/child')
    check('env: $(cat ...) reads the file', os.environ.get('SELFCHECK_FROMFILE') == 'tok-from-file')
    check('env: a trailing comment is dropped', os.environ.get('SELFCHECK_COMMENTED') == 'plain')
    check('env: the environment wins over the file', os.environ.get('SELFCHECK_PRESET') == 'from-env')
    check('env: a missing file is not an error', load_dotenv_file(tmp / 'nope.env') == 0)

    for key in ('SELFCHECK_PLAIN', 'SELFCHECK_QUOTED', 'SELFCHECK_DEFAULTED', 'SELFCHECK_NESTED',
                'SELFCHECK_FROMFILE', 'SELFCHECK_COMMENTED', 'SELFCHECK_PRESET', 'SELFCHECK_HOME'):
        os.environ.pop(key, None)
    if previous_env_file is None:
        os.environ.pop('HERMES_ENV_FILE', None)
    else:
        os.environ['HERMES_ENV_FILE'] = previous_env_file

    # A queue file of its own: the absence check must not be satisfied by
    # something an earlier step happened to write
    queue_file = tmp / 'bridge-dlq.db'
    os.environ['DLQ_DB'] = str(queue_file)
    import hermes_bridge.bridge as bridge

    check('bridge: importing opens no queue', not queue_file.exists())
    saved_urls = (os.environ.get('OFFICE_URL'), os.environ.get('SIDECAR_URL'))
    os.environ['OFFICE_URL'] = 'http://127.0.0.1:9999/'
    os.environ['SIDECAR_URL'] = 'http://127.0.0.1:9998/'
    check('bridge: OFFICE_URL is read on each call', bridge.OFFICE_URL == 'http://127.0.0.1:9999')
    check('bridge: SIDECAR_URL is read on each call', bridge.sidecar_url() == 'http://127.0.0.1:9998')
    for name, value in zip(('OFFICE_URL', 'SIDECAR_URL'), saved_urls):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    check('bridge: init() is idempotent', bridge.init() is bridge.init())
    check('bridge: init() opens the queue', queue_file.exists())
    check('bridge: pending_events() is 0 with no server', bridge.pending_events() == 0)

    from hermes_agents import config, media, pipeline, store
    from hermes_agents import episode_scheduler as sched

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
    check('w6: a live episode is announced with no channel configured, and says so',
          ep.get('notified') is True and ep.get('notified_channels') == []
          and 'DISCORD_WEBHOOK_URL kosong' in (ep.get('notified_skipped') or {}).get('discord', ''),
          f'{ep.get("notified_channels")} {ep.get("notified_skipped")}')

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

    # 6. W4: the two doors in, and the scheduler ----------------------------
    #    The routes are checked through fastapi.testclient without the app's
    #    lifespan, so no scheduler thread starts and the missing-secret guard
    #    (a startup check) does not fire here - it is checked directly below.
    from hermes_bridge.smoke import roles as known_roles
    from webhook_server import approval as approval_mod
    from webhook_server import jobs as w4jobs
    from webhook_server import payments, triggers

    os.environ['WEBHOOK_SECRET'] = 'selfcheck-secret'
    os.environ['MIDTRANS_SERVER_KEY'] = 'selfcheck-midtrans'

    check('w4: 13 trigger types, as API-REFERENCE.md lists them',
          len(triggers.SUPPORTED_TRIGGERS) == 13)
    business_roles = set(known_roles())
    mapped = {name: triggers.route_trigger(name) for name in triggers.SUPPORTED_TRIGGERS}
    check('w4: every trigger maps to a real business role, no Ops fallback',
          all(role in business_roles for role in mapped.values()), str(mapped))
    try:
        triggers.route_trigger('escalate')  # internal to W8, never over the webhook
        check('w4: an unmapped type is refused', False, 'no error')
    except triggers.UnknownTrigger:
        check('w4: an unmapped type is refused', True)

    triggers.require_secrets({'WEBHOOK_SECRET': 'a', 'MIDTRANS_SERVER_KEY': 'b'})
    try:
        triggers.require_secrets({})
        check('w4: a missing secret stops startup', False, 'no error')
    except triggers.MissingSecrets as err:
        check('w4: a missing secret stops startup',
              'WEBHOOK_SECRET' in str(err) and 'MIDTRANS_SERVER_KEY' in str(err))

    payload = {'order_id': 'o-1', 'status_code': '200', 'gross_amount': '149000.00',
               'transaction_status': 'settlement'}
    signature = payments.signature(payload, 'selfcheck-midtrans')
    check('w4: a correct Midtrans signature verifies', payments.verify(payload, signature))
    check('w4: a tampered signature is refused',
          not payments.verify(payload, signature[:-1] + ('0' if signature[-1] != '0' else '1')))
    check('w4: an empty body is a refusal, not a crash', payments.verify({}, 'x') is False)
    check('w4: notification status mapping',
          payments.status_of({'transaction_status': 'settlement'}) == 'processed'
          and payments.status_of({'transaction_status': 'chargeback'}) == 'chargeback'
          and payments.status_of({'transaction_status': 'aneh'}) == 'pending')

    from fastapi.testclient import TestClient
    from webhook_server.main import app

    client = TestClient(app)
    check('w4: /webhook refuses a wrong secret',
          client.post('/webhook', json={'type': 'support_ticket'},
                      headers={'X-Webhook-Secret': 'salah'}).status_code == 403)
    check('w4: /webhook refuses an unknown trigger',
          client.post('/webhook', json={'type': 'omong_kosong'},
                      headers={'X-Webhook-Secret': 'selfcheck-secret'}).status_code == 400)
    queued = client.post('/webhook', json={'type': 'support_ticket', 'data': {'id': 't-1'}},
                         headers={'X-Webhook-Secret': 'selfcheck-secret'})
    check('w4: /webhook queues a known trigger',
          queued.status_code == 200 and queued.json() == {'status': 'queued'})
    check('w4: /webhook/payment refuses a bad signature',
          client.post('/webhook/payment', json=payload,
                      headers={'X-Signature-Key': 'palsu'}).status_code == 403)
    first = client.post('/webhook/payment', json=payload, headers={'X-Signature-Key': signature})
    second = client.post('/webhook/payment', json=payload, headers={'X-Signature-Key': signature})
    con = store.connect()
    rows = con.execute("SELECT COUNT(*) FROM payment_events WHERE order_id = 'o-1'").fetchone()[0]
    con.close()
    check('w4: a notification sent twice is one row',
          first.status_code == 200 and second.status_code == 200 and rows == 1, f'{rows} row(s)')

    from webhook_server.scheduler import (PENDING_JOBS, pending_jobs, registered_jobs,
                                          shutdown_scheduler, start_scheduler)

    sched1 = start_scheduler()
    sched2 = start_scheduler()
    ids = sorted(job.id for job in sched1.get_jobs())
    check('w6: the scheduler registers all 11 jobs SCHEDULER.md lists',
          ids == ['approval_sweep', 'cache_warmer', 'db_backup', 'email_check', 'episode_embargo',
                  'handoff_check', 'ops_check', 'recommendation_batch', 'shared_context_cleanup',
                  'sla_check', 'weekly_report'], str(ids))
    check('w4: starting twice does not double the jobs', sched1 is sched2 and len(ids) == 11)
    check('w4: /health can list the running jobs',
          len(registered_jobs()) == 11 and pending_jobs() == [])
    check('w6: no job is parked in PENDING_JOBS now that the growth agents exist',
          PENDING_JOBS == {})
    shutdown_scheduler()
    check('w4: shutdown leaves no scheduler running', registered_jobs() == [])

    ctx = store.context()
    ctx.set('selfcheck:old', {'x': 1}, 'selfcheck')
    ctx.set('selfcheck:new', {'x': 2}, 'selfcheck')
    backdated = sqlite3.connect(os.environ['SHARED_DB'])
    backdated.execute("UPDATE context SET ts = ? WHERE key = 'selfcheck:old'", (time.time() - 25 * 3600,))
    backdated.commit()
    backdated.close()
    removed = w4jobs.cleanup_shared_context()
    check('w4: cleanup_shared_context drops the 25h row, keeps the new one',
          removed >= 1 and ctx.get('selfcheck:old') is None and ctx.get('selfcheck:new') is not None)

    approval_mod.store().set_decision('selfcheck-uncollected', 'Approve')
    check('w4: sweep_approvals drops a decision nobody collected',
          w4jobs.sweep_approvals(seconds=0) == 1,
          str(approval_mod.store().pending()))

    con = store.connect()
    sched.schedule_episode(con, episode_id='selfcheck-job-s01e01', anime_title='Job', episode_number=1,
                           encoded_path='/tmp/j.mp4', embargo_until=time.time() - 1)
    sched.schedule_episode(con, episode_id='selfcheck-job-cancel-s01e01', anime_title='Job',
                           episode_number=1, encoded_path='/tmp/k.mp4', embargo_until=time.time() - 1)
    sched.cancel_schedule(con, 'selfcheck-job-cancel-s01e01', 'selfcheck')
    con.close()
    went_live = [row['episode_id'] for row in w4jobs.run_episode_scheduler()]
    check('w4: the embargo job publishes the due episode only',
          'selfcheck-job-s01e01' in went_live and 'selfcheck-job-cancel-s01e01' not in went_live,
          str(went_live))

    written = w4jobs.backup_databases(dest=tmp / 'backups')
    check('w4: backup_databases writes the files that exist',
          bool(written) and all(path.exists() for path in written), str([p.name for p in written]))

    # 7. W5: Support (KB + SLA), UserReportAgent, and the triggers that call them --
    from hermes_agents import episode_scheduler as ep_sched
    from hermes_agents import kb as kb_mod
    from hermes_agents.support import SLA_OPTIONS, SupportAgent
    from hermes_agents.user_report import UserReportAgent

    support = SupportAgent()
    con = support.con()
    articles = kb_mod.parse_markdown(kb_mod.FAQ_PATH.read_text(encoding='utf-8'))
    seeded = support.kb().seed()
    check('w5: the shipped FAQ has at least 20 articles',
          len(articles) >= 20 and support.kb().stats()['articles'] == len(articles),
          f'{len(articles)} parsed, {support.kb().stats()["articles"]} indexed, seeded={seeded}')

    hit = support.search_kb('bagaimana cara membatalkan langganan')
    check('w5: the KB answers a real question above KB_MIN_SCORE',
          bool(hit) and hit[0]['id'] == 'cara-membatalkan-langganan'
          and hit[0]['score'] >= kb_mod.min_score(), str(hit[:1]))
    punct = support.search_kb('error 404 (video) tidak bisa diputar')
    check('w5: punctuation in a query does not break MATCH',
          bool(punct) and punct[0]['id'] == 'video-tidak-bisa-diputar-error-404', str(punct[:1]))
    check('w5: a question the KB cannot answer returns nothing', support.search_kb('zzz qqq wibble') == [])

    before = support.kb().stats()['articles']
    support.kb().upsert({'id': 'selfcheck-kb', 'title': 'Selfcheck', 'body': 'baris uji'})
    support.kb().upsert({'id': 'selfcheck-kb', 'title': 'Selfcheck', 'body': 'baris uji baru'})
    check('w5: upsert replaces an article instead of duplicating it',
          support.kb().stats()['articles'] == before + 1, str(support.kb().stats()))

    now = time.time()
    triaged = support.triage_ticket('Video error 404 tidak bisa diputar', 'sudah coba reload',
                                    user_id='u-1', channel='form', now=now)
    # "tidak bisa" is on the urgent list, "404" on the high one: urgent wins
    check('w5: triage writes a 1-hour SLA and a priority',
          triaged['sla_deadline'] == now + 3600 and triaged['priority'] == 'urgent'
          and triaged['status'] == 'open', str(triaged))

    from hermes_agents import mailer

    class _Mailbox:
        """A transport that keeps what it was asked to send, or refuses."""

        def __init__(self, error: str | None = None) -> None:
            self.sent: list = []
            self.error = error

        def __call__(self, message) -> None:
            if self.error:
                raise RuntimeError(self.error)
            self.sent.append(message)

    mailbox = _Mailbox()
    replied = support.handle_ticket({'subject': 'Cara membatalkan langganan',
                                     'body': 'saya mau berhenti perpanjangan',
                                     'user_id': 'u-2',
                                     'email': 'pelanggan@example.com'}, now=now, transport=mailbox)
    row = con.execute('SELECT status, kb_article_id FROM tickets WHERE id = ?', (replied['ticket'],)).fetchone()
    message = mailbox.sent[-1] if mailbox.sent else None
    check('w5: a KB hit really sends the reply and leaves the ticket pending',
          replied['action'] == 'replied' and row['status'] == 'pending'
          and row['kb_article_id'] == 'cara-membatalkan-langganan'
          and message is not None and message['To'] == 'pelanggan@example.com'
          and message['Auto-Submitted'] == 'auto-replied',
          f'{replied} {dict(row) if row else None}')
    check('w5: the outgoing mail carries the drafted reply, not a stub',
          message is not None and 'AniWatch' in message.get_content()
          and len(message.get_content()) > 80)
    stored = store.context().get(f'ticket:{replied["ticket"]}') or {}
    check('w5: the sent reply and its recipient are stored with the ticket',
          stored.get('sent_to') == 'pelanggan@example.com' and bool(stored.get('replied_at')),
          str(stored)[:120])

    failed = support.handle_ticket({'subject': 'Cara membatalkan langganan',
                                    'body': 'berhenti perpanjangan',
                                    'email': 'gagal@example.com'}, now=now,
                                   transport=_Mailbox('smtp down'))
    failed_row = con.execute('SELECT status FROM tickets WHERE id = ?', (failed['ticket'],)).fetchone()
    failed_ctx = store.context().get(f'ticket:{failed["ticket"]}') or {}
    check('w5: a failed send leaves the ticket OPEN and keeps the reason',
          failed['action'] == 'send_failed' and failed_row['status'] == 'open'
          and 'smtp down' in str(failed_ctx.get('send_error')),
          f'{failed} {failed_ctx.get("send_error")}')

    outbox = mailer.attempts(10)
    check('w5: every attempt is in the outbox, sent or failed',
          len(outbox) >= 2 and outbox[0]['sent'] is False and any(row['sent'] for row in outbox),
          str([(row['to'], row['sent']) for row in outbox[:3]]))
    check('w5: without SMTP_HOST the mailer says so instead of pretending',
          mailer.configured() is False
          and str(mailer.send('a@b.co', 'x', 'y')['error']).startswith('SMTP belum dikonfigurasi'))
    untouched = _Mailbox()
    check('w5: a recipient that is not an email is refused before connecting',
          mailer.send('bukan-email', 'x', 'y', transport=untouched)['sent'] is False
          and untouched.sent == [])

    missed = support.handle_ticket({'subject': 'zzz qqq wibble', 'user_id': 'u-3'}, now=now)
    esc = con.execute('SELECT status, assignee FROM tickets WHERE id = ?', (missed['ticket'],)).fetchone()
    check('w5: a KB miss escalates to the Orchestrator',
          missed['action'] == 'escalated' and esc['status'] == 'escalated'
          and esc['assignee'] == 'Orchestrator', str(dict(esc) if esc else None))

    closed = support.resolve(triaged['id'], 'selesai di selfcheck', now=now)
    check('w5: resolve stamps resolved_at',
          closed['status'] == 'resolved' and closed['resolved_at'] == now, str(closed))

    class _Card:
        """A stand-in for the office character: records the card, returns a choice."""

        def __init__(self, decision: str) -> None:
            self.id = 'selfcheck-card'
            self.decision = decision
            self.asks: list[tuple] = []
            self.updates: list[str] = []

        def update(self, status: str, tool: str | None = None) -> None:
            self.updates.append(status)

        def ask(self, message: str, options, timeout: float = 300.0) -> str:
            self.asks.append((message, tuple(options)))
            return self.decision

    def overdue(ticket_id: str) -> None:
        con.execute(
            'INSERT INTO tickets (id, user_id, subject, channel, priority, status, received_at, '
            'sla_deadline, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (ticket_id, 'u', 'tiket lewat SLA', 'email', 'normal', 'open', now - 7200, now - 3600, now - 7200),
        )
        con.commit()

    overdue('selfcheck-sla-a')
    overdue('selfcheck-sla-b')
    card = _Card('Extend SLA +30 menit')
    out = support.check_sla_breaches(char=card, now=now)
    check('w5: late tickets raise exactly ONE card, with the three options',
          len(card.asks) == 1 and card.asks[0][1] == SLA_OPTIONS and out['breaches'] == 2,
          f'{len(card.asks)} ask(s), {out}')
    deadline = con.execute("SELECT sla_deadline FROM tickets WHERE id = 'selfcheck-sla-a'").fetchone()[0]
    check('w5: Extend SLA pushes the deadline 30 minutes', deadline == now + 1800, str(deadline))

    overdue('selfcheck-sla-c')
    support.check_sla_breaches(char=_Card('Handle sekarang'), now=now)
    pri = con.execute("SELECT priority, assignee FROM tickets WHERE id = 'selfcheck-sla-c'").fetchone()
    check('w5: Handle sekarang marks the late ticket urgent for Support',
          pri['priority'] == 'urgent' and pri['assignee'] == 'Support', str(dict(pri)))

    overdue('selfcheck-sla-d')
    support.check_sla_breaches(char=_Card('Close as resolved'), now=now)
    done_row = con.execute("SELECT status, resolved_at FROM tickets WHERE id = 'selfcheck-sla-d'").fetchone()
    check('w5: Close as resolved stamps resolved_at',
          done_row['status'] == 'resolved' and done_row['resolved_at'] == now, str(dict(done_row)))

    overdue('selfcheck-sla-e')
    silent = support.check_sla_breaches(char=None, now=now)
    kept = con.execute("SELECT status, sla_deadline FROM tickets WHERE id = 'selfcheck-sla-e'").fetchone()
    check('w5: a timeout changes nothing (the next run bills the same ticket)',
          silent['decision'] == 'timeout' and kept['status'] == 'open'
          and kept['sla_deadline'] == now - 3600, f'{silent} {dict(kept)}')

    def report_status(report_id: str) -> str | None:
        row = con.execute('SELECT status FROM user_reports WHERE id = ?', (report_id,)).fetchone()
        return row['status'] if row else None

    reports = UserReportAgent(con=con)
    ep_sched.schedule_episode(con, episode_id='selfcheck-w5-live', anime_title='W5', episode_number=1,
                              encoded_path='/tmp/w5.mp4', embargo_until=now - 60)
    ep_sched.publish_due_episodes(con)
    live = con.execute("SELECT status FROM episode_schedule WHERE episode_id = 'selfcheck-w5-live'").fetchone()
    check('w5: the fixture episode is live (so its health check is honest)',
          bool(live) and live['status'] == 'live', str(dict(live) if live else None))

    broken = reports.handle_report({'description': 'video error 404 tidak bisa diputar',
                                    'episode_id': 'selfcheck-w5-missing', 'user_id': 'u-4'}, now=now)
    check('w5: a report about a broken episode asks for a QC re-check',
          broken['action'] == 'qc' and report_status(broken['report']) == 'investigating',
          str(broken))

    healthy = reports.handle_report({'description': 'video error 404 tidak bisa diputar',
                                     'episode_id': 'selfcheck-w5-live', 'user_id': 'u-5'}, now=now)
    check('w5: a report about a healthy episode gets the cache advice and closes',
          healthy['action'] == 'replied' and report_status(healthy['report']) == 'resolved', str(healthy))

    account = reports.handle_report({'description': 'akun saya tidak bisa login', 'user_id': 'u-6'}, now=now)
    form_tickets = con.execute("SELECT COUNT(*) FROM tickets WHERE channel = 'form'").fetchone()[0]
    check('w5: an account report becomes a real Support ticket',
          account['action'] == 'forwarded' and report_status(account['report']) == 'forwarded'
          and form_tickets >= 1, f'{account} form={form_tickets}')

    spam = reports.handle_report({'description': 'spam iklan judi', 'user_id': 'u-7'}, now=now)
    check('w5: a spam report is dismissed, not forwarded',
          spam['action'] == 'dismissed' and report_status(spam['report']) == 'dismissed', str(spam))

    rows_before = con.execute('SELECT COUNT(*) FROM user_reports').fetchone()[0]
    duplicate = reports.handle_report({'description': 'video error 404 lagi',
                                       'episode_id': 'selfcheck-w5-live', 'user_id': 'u-8'}, now=now)
    rows_after = con.execute('SELECT COUNT(*) FROM user_reports').fetchone()[0]
    check('w5: the same episode inside 24 hours writes no new row',
          duplicate['action'] == 'duplicate' and rows_after == rows_before,
          f'{rows_before} -> {rows_after}')

    from webhook_server import triggers as w4triggers

    result = w4triggers.run_trigger('support_ticket',
                                    {'subject': 'Cara membatalkan langganan',
                                     'email': 'lead@example.com'}, 'webhook')
    made = result.get('work') or {}
    made_rows = con.execute('SELECT COUNT(*) FROM tickets WHERE id = ?', (made.get('ticket'),)).fetchone()[0]
    check('w5: a support_ticket webhook records the ticket even when mail cannot go out',
          made.get('action') == 'send_failed' and made_rows == 1
          and 'SMTP' in str(made.get('error')), str(made))
    check('w5: the report trigger is wired to UserReportAgent and Support',
          w4triggers.AGENT_HANDLERS.get('user_report') is w4triggers._report_work
          and w4triggers.AGENT_HANDLERS.get('new_email') is w4triggers._support_work)
    check('w5: sla_check is registered now that Support exists',
          'sla_check' not in [job['id'] for job in pending_jobs()], str(pending_jobs()))

    # 8. W5 sisa: Moderator, OpsAgent, dan kotak masuk (email_check) -----------
    from hermes_agents import inbox as inbox_mod
    from hermes_agents.moderator import ModeratorAgent
    from hermes_agents.ops import OpsAgent, run_ops_check

    moderator = ModeratorAgent(con=con)
    check('w5: a clean comment is allowed',
          moderator.filter_comment('episodenya bagus banget')['action'] == 'allow')
    banned = moderator.handle_comment({'comment': 'dasar anjing', 'user_id': 'u-ban',
                                       'comment_id': 'c-1'}, now=now)
    check('w5: an abusive comment bans the account with its rule',
          banned['action'] == 'ban' and moderator.is_banned('u-ban'), str(banned))
    history = moderator.history('u-ban')
    check('w5: the ban row keeps rule, reason and actor (SECURITY.md §10)',
          len(history) == 1 and history[0]['rule'] == 'abuse' and bool(history[0]['reason'])
          and history[0]['actor'] == 'Moderator', str(history))
    spoiler = moderator.handle_comment({'comment': 'spoiler: mati di episode 3',
                                        'user_id': 'u-spoiler', 'comment_id': 'c-2'}, now=now)
    check('w5: a spoiler is flagged, not banned',
          spoiler['action'] == 'flag' and not moderator.is_banned('u-spoiler'), str(spoiler))
    anonymous = moderator.handle_comment({'comment': 'link torrent gratis',
                                          'comment_id': 'c-3'}, now=now)
    check('w5: without a user_id a bad comment is flagged instead of failing',
          anonymous['action'] == 'flag', str(anonymous))
    moderator.ban_account('u-ban', 'piracy', 'mengulang', now=now + 1)
    check('w5: moderation rows are append-only (a second ban is a second row)',
          len(moderator.history('u-ban')) == 2, str(len(moderator.history('u-ban'))))

    findings = OpsAgent(now=now).check_system()
    names = {f['check'] for f in findings}
    check('w5: Ops checks disk, database, dlq, context, scheduler and mail',
          names == {'disk', 'database', 'dlq', 'context', 'scheduler', 'mail'}, str(sorted(names)))
    check('w5: every finding has a level, and a bad one says what to do',
          all(f['level'] in ('ok', 'warn', 'critical')
              and (f['level'] == 'ok' or bool(f['action'])) for f in findings),
          str([(f['check'], f['level']) for f in findings]))

    class _FakeIMAP:
        """A mailbox that serves the raw messages it was given, by uid."""

        def __init__(self, raws: dict[str, bytes]) -> None:
            self.raws = raws
            self.logged_out = False

        def select(self, folder: str):
            return 'OK', [b'1']

        def uid(self, command: str, *args):
            if command == 'search':
                return 'OK', [' '.join(self.raws).encode()]
            if command == 'fetch':
                raw = self.raws.get(args[0])
                return ('OK', [(b'1 (BODY[])', raw)]) if raw else ('NO', [])
            return 'OK', []

        def logout(self) -> None:
            self.logged_out = True

    raw_mail = (b'From: Budi <Budi@Contoh.com>\r\n'
                b'Subject: =?UTF-8?B?Q2FyYSBtZW1iYXRhbGthbiBsYW5nZ2FuYW4=?=\r\n'
                b'Content-Type: text/plain; charset=utf-8\r\n\r\n'
                b'Halo, cara membatalkan langganan?\r\n> kutipan lama\r\n')
    raw_auto = (b'From: Bot <bot@aniwatch.example>\r\nSubject: Re: x\r\n'
                b'Auto-Submitted: auto-replied\r\n\r\nbalasan kita sendiri\r\n')
    os.environ.update({'IMAP_HOST': 'imap.example', 'IMAP_USER': 'support@example'})

    box = _FakeIMAP({'1': raw_mail, '2': raw_auto})
    messages = inbox_mod.fetch_new(factory=lambda cfg: box)
    check('w5: IMAP reading decodes the subject and trims the quoted history',
          len(messages) == 1 and messages[0]['subject'] == 'Cara membatalkan langganan'
          and 'kutipan' not in messages[0]['body'], str(messages))
    check('w5: our own auto-reply is skipped, and a seen uid is not fetched twice',
          inbox_mod.fetch_new(factory=lambda cfg: box) == [] and box.logged_out)

    mails = w4jobs.check_new_emails(fetch=lambda cfg: _FakeIMAP({'9': raw_mail}))
    made = (mails[0].get('work') or {}) if mails else {}
    email_tickets = con.execute("SELECT COUNT(*) FROM tickets WHERE channel = 'email'").fetchone()[0]
    check('w5: a new mail becomes a ticket through the same Orchestrator path',
          len(mails) == 1 and made.get('action') == 'send_failed' and email_tickets >= 1,
          f'{made} email_tickets={email_tickets}')

    os.environ['IMAP_HOST'] = ''
    check('w5: without IMAP settings the job returns nothing instead of raising',
          w4jobs.check_new_emails(fetch=lambda cfg: _FakeIMAP({'1': raw_mail})) == []
          and inbox_mod.configured() is False)
    os.environ['IMAP_HOST'] = 'imap.example'
    pending_ids = [job['id'] for job in pending_jobs()]
    check('w5: email_check and ops_check are registered',
          'email_check' not in pending_ids and 'ops_check' not in pending_ids, str(pending_ids))

    # 9. W8: protokol handoff + graph Orchestrator ----------------------------
    from hermes_agents import orchestrator as orch
    from hermes_bridge import handoff as ho
    from hermes_bridge import shared_context as sc

    ctx = sc.default()
    for stale_key in list(ho.pending(context=ctx)):
        ho.drop(stale_key, context=ctx)

    try:
        ho.hand_off('Sales', 'SecOps', 'random_reason', 'lead:1', {'x': 1}, context=ctx)
        refused_transition = False
    except ho.UnknownHandoff:
        refused_transition = True
    check('w8: a transition that is not a row in AGENT-HANDOFFS §3 is refused',
          refused_transition)

    try:
        ho.hand_off('Sales', 'Marketing', 'lead_converted', 'lead:1', {'name': 'Budi'}, context=ctx)
        refused_payload = False
    except ValueError:
        refused_payload = True
    check('w8: a payload missing what the table promises is refused', refused_payload)

    key = ho.hand_off('Sales', 'Marketing', 'lead_converted', 'lead:42',
                      {'name': 'Budi', 'email': 'budi@example.com', 'score': 0.87,
                       'plan': 'premium'}, now=now, context=ctx)
    wrong_owner = ho.take(key, 'Support', context=ctx)
    envelope = ho.take(key, 'Marketing', context=ctx) or {}
    check('w8: the envelope has the documented key and every field',
          key == 'handoff:sales:marketing:42'
          and set(envelope) == set(ho.ENVELOPE_FIELDS)
          and envelope.get('expects') == 'welcome_email_campaign', str(envelope))
    check('w8: only the addressed role can take a handoff, and only once',
          wrong_owner is None and ho.take(key, 'Marketing', context=ctx) is None,
          str(wrong_owner))

    seen: list[str] = []

    def _sales(data):
        seen.append('Sales')
        ho.hand_off('Sales', 'Marketing', 'lead_converted', 'lead:7',
                    {'name': 'Sari', 'email': 'sari@example.com', 'score': 0.9, 'plan': 'premium'},
                    now=now, context=ctx)
        return {'action': 'qualified'}

    def _marketing(data):
        seen.append(f'Marketing:{data.get("name")}')
        ho.hand_off('Marketing', 'Support', 'customer_onboarding', 'lead:7',
                    {'plan': data.get('plan'), 'channel': 'web'}, now=now, context=ctx)
        return {'action': 'welcome_sent'}

    def _support_chain(data):
        seen.append(f'Support:{data.get("reason")}')
        return {'action': 'onboarding_ticket'}

    graph = orch.build_orchestrator_graph(
        {'Sales': _sales, 'Marketing': _marketing, 'Support': _support_chain}, context=ctx)
    walked = graph.invoke('Sales', {})
    check('w8: Sales -> Marketing -> Support runs as one chain with the payload',
          walked['visited'] == ['Sales', 'Marketing', 'Support']
          and seen == ['Sales', 'Marketing:Sari', 'Support:customer_onboarding'], str(seen))
    check('w8: each handoff is consumed, so nothing is left behind',
          ho.pending(context=ctx) == {}, str(list(ho.pending(context=ctx))))

    ho.hand_off('UserReportAgent', 'QualityChecker', 'report_technical', 'report:rp-1',
                {'episode_id': 'e-1'}, now=now, context=ctx)
    stopped = orch.build_orchestrator_graph(context=ctx).follow_chain('UserReportAgent')
    check('w8: a handoff to an agent that does not exist stops with "skipped"',
          len(stopped) == 1 and 'skipped' in (stopped[0]['work'] or {})
          and ho.pending(context=ctx) == {}, str(stopped))

    escalated = w4triggers.run_trigger(
        'support_ticket', {'subject': 'xyzzy plugh', 'body': 'qwerty zxcv', 'user_id': 'u-esc'})
    hops = escalated.get('chain') or []
    records = ctx.find('escalation:')
    check('w8: a Support escalation is a handoff the Orchestrator picks up',
          (escalated.get('work') or {}).get('action') == 'escalated'
          and [(hop['from'], hop['to']) for hop in hops] == [('Support', 'Orchestrator')]
          and len(records) >= 1, str(hops))

    late = ho.hand_off('Scraper', 'Metadata', 'episode_fetched', 'episode:e-late',
                       {'episode_id': 'e-late'}, now=now - 7200, deadline=now - 3600, context=ctx)
    check('w8: a handoff past its deadline is the only one reported expired',
          late in ho.expired(now, context=ctx) and not ho.expired(now - 7200, context=ctx),
          str(list(ho.expired(now, context=ctx))))

    class _ChainChar:
        """The three-button card, answered without a browser."""

        def __init__(self, pick: str) -> None:
            self.pick = pick

        def update(self, *args, **kwargs) -> None:
            pass

        def ask(self, message: str, options: list[str], timeout: float = 300.0) -> str:
            return self.pick

    extended = w4jobs.check_handoffs(now=now, char=_ChainChar(w4jobs.HANDOFF_OPTIONS[1]))
    check('w8: "Perpanjang 1 jam" moves the deadline and keeps the handoff',
          extended['handled'] == 1 and late in ho.pending(context=ctx)
          and float(ho.get(late, context=ctx)['deadline']) > now, str(extended))

    ho.extend(late, -7200.0, now=now, context=ctx)
    to_human = w4jobs.check_handoffs(now=now, char=_ChainChar(w4jobs.HANDOFF_OPTIONS[0]))
    check('w8: "Eskalasi ke manusia" drops the handoff and records the decision',
          to_human['handled'] == 1 and late not in ho.pending(context=ctx)
          and len(ctx.find('escalation:')) > len(records), str(to_human))

    ignored = ho.hand_off('Scraper', 'Metadata', 'episode_fetched', 'episode:e-ignore',
                          {'episode_id': 'e-ignore'}, now=now - 7200, deadline=now - 3600, context=ctx)
    dropped = w4jobs.check_handoffs(now=now, char=_ChainChar(w4jobs.HANDOFF_OPTIONS[2]))
    check('w8: "Abaikan" throws the handoff away without escalating it',
          dropped['handled'] == 1 and ignored not in ho.pending(context=ctx), str(dropped))

    pending_ids = [job['id'] for job in pending_jobs()]
    check('w8: handoff_check is registered',
          'handoff_check' not in pending_ids, str(pending_ids))

    # 10. W6: growth — Analytics, SEO, SocialMedia, Recommendation, Retention,
    #     CacheWarmer and the three jobs that were waiting for them -------------
    from hermes_agents import analytics, cache_warmer, marketing, recommendation
    from hermes_agents import retention as retention_mod
    from hermes_agents import seo as seo_mod
    from hermes_agents import social as social_mod

    local_snap = analytics.AnalyticsAgent(con=con).generate_report(now=now)
    check('w6: analytics names its source and writes a snapshot file',
          local_snap['source'] == 'local' and local_snap['feed'] is None
          and Path(local_snap['path']).exists(), str(local_snap['source']))
    check('w6: without an export the missing watch data is named, not invented',
          local_snap['dropoffs'] == []
          and any('ANALYTICS_FEED' in line for line in local_snap['insufficient']))

    feed_file = tmp / 'analytics.json'
    feed_file.write_text(json.dumps({
        'generated_at': now,
        'episodes': [
            {'episode_id': 'feed-a', 'views': 100, 'completions': 90},
            {'episode_id': 'feed-b', 'views': 100, 'completions': 20},
            {'episode_id': 'feed-c', 'views': 5, 'completions': 0},
            {'episode_id': 'feed-d'},
        ],
        'history': [
            {'user_id': 'u-a', 'episode_id': 'feed-a'},
            {'user_id': 'u-a', 'episode_id': 'feed-b'},
            {'user_id': 'u-b', 'episode_id': 'feed-a'},
            {'user_id': 'u-b', 'episode_id': 'feed-c'},
            {'user_id': 'u-c', 'episode_id': 'feed-a'},
        ],
    }), encoding='utf-8')
    os.environ['ANALYTICS_FEED'] = str(feed_file)
    grown = analytics.AnalyticsAgent(con=con).generate_report(now=now)
    check('w6: with the export, only the real drop-off is flagged',
          [row['episode_id'] for row in grown['dropoffs']] == ['feed-b']
          and grown['source'] == 'feed+local', str(grown['dropoffs']))
    check('w6: a low view count is not a drop-off and a missing metric is not a zero',
          all(row['episode_id'] not in ('feed-c', 'feed-d') for row in grown['dropoffs']),
          str(grown['dropoffs']))

    site = seo_mod.SEOAgent(con=con).update_site(
        {'episode_id': 'feed-a', 'anime_title': 'Feed Show', 'episode_number': 1}, now=now)
    sitemap = Path(site['sitemap']).read_text(encoding='utf-8')
    structured = json.loads(Path(site['structured_data']).read_text(encoding='utf-8'))
    check('w6: the sitemap lists live episodes and never a cancelled one',
          'selfcheck-w5-live' in sitemap and 'selfcheck-cancel-s01e01' not in sitemap
          and 'selfcheck-job-cancel-s01e01' not in sitemap, site['sitemap'])
    check('w6: meta + structured data are written, with an honest base url',
          Path(site['meta']).exists() and len(structured) >= 2
          and site['base_url'] == 'relative', str(site['base_url']))

    social_agent = social_mod.SocialMediaAgent(context=ctx)
    quiet = social_agent.announce_episode(
        {'episode_id': 'feed-a', 'title': 'Feed Show', 'episode_number': 1})
    check('w6: with no webhook the post is skipped with its reason, never claimed',
          quiet['posted'] == [] and 'DISCORD_WEBHOOK_URL kosong' in quiet['skipped']['discord']
          and 'belum diimplementasikan' in quiet['skipped']['twitter'], str(quiet))
    ctx.set(social_mod.key('feed-a'), {'discord': True, 'at': now}, 'SocialMedia')
    again = social_agent.post_all('halo', episode_id='feed-a')
    check('w6: a channel that already has this episode is not posted twice',
          again['skipped']['discord'] == 'sudah diposting untuk episode ini', str(again))

    from hermes_agents.notifier import notify

    written = notify({'episode_id': 'feed-a', 'title': 'Feed Show', 'episode_number': 1,
                      'encoded_path': str(tmp / 'feed-a.mp4')})
    check('w6: Notifier writes the feed and leaves the platforms to SocialMedia',
          set(written) == {'feed', 'log', 'title'} and Path(written['feed']).exists(), str(written))

    recs = recommendation.RecommendationAgent(feed_path=feed_file).run_batch(now=now)
    rec_rows = [json.loads(line) for line in Path(recs['path']).read_text(encoding='utf-8').splitlines()]
    by_user = {row['user_id']: row['episode_id'] for row in rec_rows}
    check('w6: the batch recommends an unwatched episode and never one already watched',
          recs['target'] == 'file' and recs['users'] == 3 and by_user.get('u-a') == 'feed-c'
          and all(row['episode_id'] != 'feed-a' for row in rec_rows), str(recs))

    os.environ['RECOMMENDATION_DB'] = str(tmp / 'aniwatch.db')
    to_db = recommendation.RecommendationAgent(feed_path=feed_file).run_batch(now=now)
    ani = sqlite3.connect(str(tmp / 'aniwatch.db'))
    stored = ani.execute(
        "SELECT COUNT(*) FROM recommendations WHERE user_id = 'u-a' AND episode_id = 'feed-c'"
    ).fetchone()[0]
    ani.close()
    check("w6: with RECOMMENDATION_DB set the batch writes AniWatch's own table",
          to_db['target'] == 'db' and stored == 1, f'{to_db} stored={stored}')

    lapsed = ('lapsed@example.com', 'premium', now - 86400.0, 2, None)
    graced = ('grace@example.com', 'premium', now + 86400.0, 1, now + 2 * 86400.0)
    addressless = ('user-tanpa-email', 'premium', now - 86400.0, 2, None)
    for row in (lapsed, graced, addressless):
        con.execute(
            'INSERT OR REPLACE INTO subscription_status '
            '(user_id, plan, expires_at, retry_count, grace_until, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?)', (*row, now),
        )
    con.commit()
    letters = _Mailbox()
    retention = retention_mod.RetentionAgent(con=con, transport=letters)
    segment = retention.segment_users(now=now)
    check('w6: retention segments expired and in-grace subscribers',
          {row['user_id'] for row in segment} == {'lapsed@example.com', 'grace@example.com',
                                                  'user-tanpa-email'}, str(segment))
    campaign = retention.send_campaign(segment, now=now)
    check('w6: the campaign mails the address it has and skips an id that is not one',
          campaign['sent'] == 2 and 'user-tanpa-email' in campaign['skipped'], str(campaign))
    check('w6: the letter is a real re-engagement letter, not a stub',
          len(letters.sent) == 2 and 'AniWatch' in letters.sent[0].get_content())
    check('w6: a delivered campaign is not repeated inside the cooldown',
          [row['user_id'] for row in retention.segment_users(now=now)] == ['user-tanpa-email'],
          str(retention.segment_users(now=now)))
    check('w6: after the cooldown the same user is a candidate again',
          len(retention.segment_users(now=now + 8 * 86400)) == len(segment))

    warmer = cache_warmer.CacheWarmerAgent(con=con)
    cold = warmer.run(now=now)
    check('w6: without CDN_BASE_URL the warmer says there is nowhere to warm',
          cold['warmed'] == 0 and 'CDN_BASE_URL' in str(cold['reason']), str(cold))
    check('w6: trending is the live episodes this fork knows about',
          'selfcheck-w5-live' in [row['episode_id'] for row in warmer.get_trending()])
    warmer.close()

    weekly = marketing.MarketingAgent().weekly_report(now=now)
    text = Path(weekly['report']).read_text(encoding='utf-8')
    check('w6: the weekly report is a file naming its week and its data source',
          weekly['week'] == marketing.week_label(now) and 'feed+local' in text
          and '## Support' in text, weekly['report'])
    check('w6: the report summary is not posted to Discord when the webhook is empty',
          weekly['discord'] is False and 'DISCORD_WEBHOOK_URL' in str(weekly['discord_reason']),
          str(weekly['discord_reason']))

    reported = w4jobs.run_marketing_report(now=now)
    check('w6: weekly_report runs the weekly_analytics trigger through the Orchestrator',
          reported.get('role') == 'Marketing'
          and (reported.get('work') or {}).get('action') == 'reported', str(reported.get('role')))
    rec_job = w4jobs.run_recommendation_batch(now=now)
    check('w6: the recommendation_batch job writes where it says it does',
          rec_job['target'] == 'db' and rec_job['users'] == 3, str(rec_job))
    warm_job = w4jobs.run_cache_warmer(now=now)
    check('w6: the cache_warmer job reports its reason instead of a fake warm count',
          warm_job['warmed'] == 0 and bool(warm_job['reason']), str(warm_job))
    check('w6: the five growth triggers run agent work, not just characters',
          all(name in w4triggers.AGENT_HANDLERS for name in
              ('analytics_ready', 'weekly_analytics', 'content_schedule', 'announce_episode',
               'retention_check')), str(sorted(w4triggers.AGENT_HANDLERS)))

    # 11. W7: premium — design -> QA -> price -> preview -> approval -> live ----
    from hermes_agents import premium
    from webhook_server import commands as w7commands

    started = w7commands.handle_command('/design border neon', now=now)
    made_id = str(started.get('item') or '')
    made = premium.get_item(made_id) or {}
    check('w7: /design creates a priced, previewed item waiting for approval',
          started.get('ok') is True and made.get('status') == 'pending_approval'
          and bool(made.get('tier')) and int(made.get('price_idr') or 0) > 0
          and Path(str(made.get('design_path'))).exists()
          and Path(str(made.get('preview_light'))).exists()
          and Path(str(made.get('preview_dark'))).exists(), f'{started} {made.get("status")}')
    made_ctx = store.context().get(premium.item_key(made_id)) or {}
    check('w7: the design says it came from a template, not from an image model',
          made_ctx.get('design_source') == 'template', str(made_ctx.get('design_source')))
    check('w7: QA scored resolution, palette and transparency',
          made.get('qa_score') == 1.0, str(made.get('qa_score')))

    listing = w7commands.handle_command('/pending-items', now=now)
    check('w7: /pending-items names the item that waits',
          made_id in (listing.get('items') or []) and made_id in listing.get('reply', ''),
          str(listing)[:200])
    check('w7: a command it does not own is left to the chat',
          w7commands.handle_command('/status')['handled'] is False)
    bad = w7commands.handle_command('/design bingkai neon', now=now)
    check('w7: an unknown kind is refused, with the choices',
          bad.get('ok') is False and 'border' in bad.get('reply', ''), str(bad)[:160])

    approved = w7commands.handle_command(f'/approve {made_id}', now=now)
    live_row = premium.get_item(made_id) or {}
    made_ctx = store.context().get(premium.item_key(made_id)) or {}
    manifest_file = Path(str(made_ctx.get('manifest') or ''))
    manifest = (json.loads(manifest_file.read_text(encoding='utf-8'))
                if manifest_file.is_file() else {})
    check('w7: /approve publishes the item', approved.get('ok') is True and live_row.get('status') == 'live',
          f'{approved.get("reply")!r} {live_row.get("status")}')
    check('w7: publish writes a manifest that says the CDN upload did not happen',
          manifest.get('id') == made_id and manifest.get('cdn', {}).get('uploaded') is False
          and manifest.get('live_at') == now, str(manifest)[:160])
    check('w7: approving a live item again is a no-op, not a second publish',
          premium.publish(made_id, now=now).get('published') is False)

    card_item = premium.start('nameplate', 'sakura', now=now)
    carded = premium.request_approval(str(card_item['id']), char=_Card('Approve'), now=now)
    check('w7: the card door writes the same status as /approve',
          carded.get('status') == 'live'
          and (premium.get_item(str(card_item['id'])) or {}).get('status') == 'live',
          str(carded.get('status')))

    rejected_item = premium.start('profile_effect', 'ocean', now=now)
    rejected = premium.request_approval(str(rejected_item['id']), char=_Card('Reject'), now=now)
    check('w7: Reject stops the pipeline and the item stays rejected',
          rejected.get('status') == 'rejected', str(rejected.get('status')))

    class _Reviser:
        """Revisi on the first card, Approve on the second."""

        def __init__(self) -> None:
            self.id = 'selfcheck-reviser'
            self.calls = 0

        def update(self, *args, **kwargs) -> None:
            pass

        def ask(self, message: str, options, timeout: float = 300.0) -> str:
            self.calls += 1
            return 'Revisi' if self.calls == 1 else 'Approve'

    revise_item = premium.start('border', 'ocean', now=now)
    reviser = _Reviser()
    revised = premium.request_approval(str(revise_item['id']), char=reviser, now=now)
    revise_ctx = store.context().get(premium.item_key(str(revise_item['id']))) or {}
    check('w7: Revisi runs DesignAgent again, and the second card can publish it',
          reviser.calls == 2 and revised.get('status') == 'live'
          and int(revise_ctx.get('attempt') or 0) >= 2,
          f'{reviser.calls} kartu, {revised.get("status")}, attempt={revise_ctx.get("attempt")}')

    timeout_item = premium.start('border', 'neon', now=now)
    timed = premium.request_approval(str(timeout_item['id']), char=_Card('timeout'), now=now)
    check('w7: a timeout leaves the item pending, so /approve can still take it',
          timed.get('status') == 'pending_approval'
          and (premium.get_item(str(timeout_item['id'])) or {}).get('status') == 'pending_approval',
          str(timed.get('status')))

    route = client.post('/command', json={'text': '/pending-items'}).json()
    check('w7: the sidecar route answers a chat command with one reply',
          route.get('handled') is True and route.get('ok') is True and 'pm-' in route.get('reply', ''),
          str(route)[:160])
    other = client.post('/command', json={'text': '/status'}).json()
    check('w7: the route leaves a base command alone', other.get('handled') is False, str(other))

    # 12. W9: Finance, Legal, Security ---------------------------------------
    from hermes_agents import dmca as dmca_mod
    from hermes_agents import finance
    from hermes_agents import sec_ops

    def payment_row(order: str, user: str, amount: int, status: str, when: float) -> None:
        """One recorded notification, the shape `payments.record()` writes."""
        con.execute(
            'INSERT OR REPLACE INTO payment_events '
            '(id, order_id, user_id, event_type, amount_idr, payment_method, status, processed_at, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (f'{order}:200:settlement', order, user, 'settlement', amount, 'qris', status, when, when),
        )
        con.commit()

    # PaymentAgent: renewal failed -> grace 3 hari -> downgrade
    payment_row('sc-renew', 'renew@example.com', 149000, 'processed', now - 86400)
    letters = _Mailbox()
    graced_payment = finance.handle_failure(
        {'order_id': 'sc-renew', 'customer_id': 'renew@example.com',
         'transaction_status': 'deny'}, now=now, con=con, transport=letters)
    sub = con.execute("SELECT * FROM subscription_status WHERE user_id = 'renew@example.com'").fetchone()
    check('w9: a failed renewal sets a 3-day grace and mails the subscriber',
          graced_payment['action'] == 'grace' and sub['grace_until'] == now + finance.GRACE_S
          and sub['retry_count'] == 1 and len(letters.sent) == 1,
          f'{graced_payment} {dict(sub) if sub else None} mail={len(letters.sent)}')
    downgraded = finance.handle_failure(
        {'order_id': 'sc-renew', 'customer_id': 'renew@example.com',
         'transaction_status': 'expire'}, now=now, con=con)
    sub = con.execute("SELECT * FROM subscription_status WHERE user_id = 'renew@example.com'").fetchone()
    check('w9: the second failed renewal downgrades to free and counts subscriptions_lost',
          downgraded['action'] == 'downgrade' and sub['plan'] == 'free'
          and downgraded['metric'] == {'subscriptions_lost': 1} and sub['grace_until'] is None,
          f'{downgraded} {dict(sub)}')

    # refund: window, card, approve / reject / timeout
    payment_row('sc-refund', 'buyer@example.com', 35000, 'processed', now - 2 * 86400)
    queued_refund = finance.refund_request(
        {'order_id': 'sc-refund', 'customer_id': 'buyer@example.com'}, now=now, con=con)
    check('w9: a refund inside the 7-day window is queued as pending, never paid',
          queued_refund['action'] == 'refund_requested'
          and (finance.refund_row(con, 'sc-refund') or {}).get('status') == 'pending',
          str(queued_refund))
    refund_carded = finance.request_refund_approval('sc-refund', char=_Card('Approve'), now=now, con=con)
    check('w9: Approve on the refund card is the only way to refunded',
          refund_carded['action'] == 'refunded'
          and finance.refund_row(con, 'sc-refund')['status'] == 'refunded'
          and refund_carded['metric'] == {'refunds_processed': 1}, str(refund_carded))

    payment_row('sc-refund2', 'buyer2@example.com', 35000, 'processed', now - 86400)
    finance.refund_request({'order_id': 'sc-refund2'}, now=now, con=con)
    refund_refused = finance.request_refund_approval('sc-refund2', char=_Card('Tolak'), now=now, con=con)
    check('w9: Tolak leaves the money where it was and records the refusal',
          refund_refused['action'] == 'rejected'
          and finance.refund_row(con, 'sc-refund2')['status'] == 'failed', str(refund_refused))

    payment_row('sc-refund3', 'buyer3@example.com', 35000, 'processed', now - 86400)
    finance.refund_request({'order_id': 'sc-refund3'}, now=now, con=con)
    finance.request_refund_approval('sc-refund3', char=_Card('timeout'), now=now, con=con)
    check('w9: a timeout on the refund card keeps the request in the queue',
          finance.refund_row(con, 'sc-refund3')['status'] == 'pending'
          and 'sc-refund3' in [row['order_id'] for row in finance.refund_queue(con)])

    payment_row('sc-old', 'late@example.com', 35000, 'processed', now - 30 * 86400)
    too_late = finance.refund_request({'order_id': 'sc-old'}, now=now, con=con)
    check('w9: a refund after the 7-day window is refused with the age named',
          too_late['action'] == 'refused' and '7 hari' in too_late['reason'], str(too_late))

    # chargeback: revoke the named item, then reach SecOps through the trigger
    revocable = premium.start('border', 'neon', now=now)
    premium.decide(str(revocable['id']), 'Approve', now=now)
    chargeback = w4triggers.run_trigger(
        'chargeback_received',
        {'order_id': 'sc-cb', 'customer_id': 'fraud@example.com', 'gross_amount': '75000',
         'item_id': str(revocable['id'])}, 'midtrans')
    chargeback_work = chargeback.get('work') or {}
    chargeback_hops = [(hop['from'], hop['to']) for hop in (chargeback.get('chain') or [])]
    flagged = con.execute(
        "SELECT action, rule FROM security_incidents WHERE target = 'fraud@example.com' "
        'ORDER BY created_at DESC LIMIT 1').fetchone()
    check('w9: a chargeback revokes the named item and reaches SecOps as one hop',
          chargeback_work.get('action') == 'chargeback'
          and bool((chargeback_work.get('revoked') or {}).get('revoked'))
          and (premium.get_item(str(revocable['id'])) or {}).get('status') == 'revoked'
          and chargeback_hops == [('PaymentAgent', 'SecOps')]
          and flagged is not None and flagged['action'] == 'flag_account',
          f'{chargeback_work} hops={chargeback_hops} flagged={dict(flagged) if flagged else None}')

    # SecOps: no feed -> says so; with the feed -> the rule really fires
    os.environ['SECURITY_EVENT_FEED'] = ''
    quiet_round = sec_ops.monitor(now=now, con=con)
    check('w9: without the access feed SecOps names what it cannot count',
          any('SECURITY_EVENT_FEED' in line for line in quiet_round['insufficient'])
          and quiet_round['violations'] == [], str(quiet_round))

    security_feed = tmp / 'security-events.jsonl'
    security_feed.write_text('\n'.join(
        json.dumps({'at': now - 10, 'type': 'login_failed', 'ip': '10.0.0.9'}) for _ in range(5)
    ) + '\n', encoding='utf-8')
    os.environ['SECURITY_EVENT_FEED'] = str(security_feed)
    armed = sec_ops.monitor(now=now, con=con)
    check('w9: five failed logins in 60 s ban the IP',
          any(row['rule'] == 'login_attempts' for row in armed['violations'])
          and sec_ops.is_banned('10.0.0.9', con=con), str(armed))
    check('w9: the same breach inside the cooldown writes no second incident',
          sec_ops.monitor(now=now, con=con)['blocked'] == 0)
    unbanned = sec_ops.unban('10.0.0.9', now=now + 1, con=con)
    check('w9: unban is a new row, and it lifts the block',
          unbanned['ok'] is True and not sec_ops.is_banned('10.0.0.9', con=con), str(unbanned))
    os.environ['SECURITY_EVENT_FEED'] = ''

    # DMCA: a takedown before the embargo, after it, twice, and refused
    sched.schedule_episode(con, episode_id='sc-dmca-scheduled', anime_title='Legal',
                           episode_number=1, encoded_path='/tmp/d1.mp4', embargo_until=now + 3600)
    takedown = dmca_mod.handle_takedown(
        {'episode_id': 'sc-dmca-scheduled', 'requester': 'Studio X', 'reason': 'hak cipta'},
        now=now, con=con)
    takedown_row = sched.get_schedule(con, 'sc-dmca-scheduled')
    takedown_audit = con.execute('SELECT status FROM dmca_requests WHERE id = ?', (takedown['id'],)).fetchone()
    check('w9: a DMCA takedown cancels a scheduled episode through EpisodeScheduler',
          takedown['action'] == 'cancelled' and takedown_row['status'] == 'cancelled'
          and [(hop['from'], hop['to']) for hop in (takedown.get('chain') or [])]
          == [('DMCA', 'EpisodeScheduler')]
          and takedown_audit is not None and takedown_audit['status'] == 'cancelled',
          f'{takedown.get("action")} {dict(takedown_row)} {dict(takedown_audit) if takedown_audit else None}')
    check('w9: a cancelled episode never publishes',
          'sc-dmca-scheduled' not in [row['episode_id']
                                       for row in sched.publish_due_episodes(con, now + 7200)])

    sched.schedule_episode(con, episode_id='sc-dmca-live', anime_title='Legal',
                           episode_number=2, encoded_path='/tmp/d2.mp4', embargo_until=now - 60)
    sched.publish_due_episodes(con, now)
    live_takedown = dmca_mod.handle_takedown(
        {'episode_id': 'sc-dmca-live', 'requester': 'Studio Y', 'reason': 'lisensi'},
        now=now, con=con)
    check('w9: a takedown on a live episode unpublishes it and says the CDN was not purged',
          live_takedown['action'] == 'unpublished'
          and sched.get_schedule(con, 'sc-dmca-live')['status'] == 'cancelled'
          and live_takedown['cdn_purged'] is False and bool(live_takedown['cdn_reason']),
          str(live_takedown)[:200])
    check('w9: the same takedown twice is a duplicate, not a second cancel',
          dmca_mod.handle_takedown(
              {'episode_id': 'sc-dmca-scheduled', 'requester': 'Studio X', 'reason': 'ulang'},
              now=now, con=con)['action'] == 'duplicate')
    refused = dmca_mod.handle_takedown({'anime_id': 'a-1', 'reason': 'semua episode'}, now=now, con=con)
    check('w9: a request without episode_id/requester is refused, and still recorded',
          refused['action'] == 'refused' and bool(refused['id'])
          and 'episode_id' in refused['missing']
          and con.execute('SELECT COUNT(*) FROM dmca_requests WHERE id = ?',
                          (refused['id'],)).fetchone()[0] == 1, str(refused))

    # The payment door, end to end: signature -> row -> PaymentAgent -> handoff
    settled_payload = {'order_id': 'sc-e2e', 'status_code': '200', 'gross_amount': '99000.00',
                       'transaction_status': 'settlement', 'customer_id': 'e2e@example.com',
                       'payment_type': 'qris'}
    settled_answer = client.post('/webhook/payment', json=settled_payload,
                                 headers={'X-Signature-Key': payments.signature(
                                     settled_payload, 'selfcheck-midtrans')})
    e2e_sub = con.execute(
        "SELECT plan FROM subscription_status WHERE user_id = 'e2e@example.com'").fetchone()
    e2e_rows = con.execute("SELECT COUNT(*) FROM payment_events WHERE order_id = 'sc-e2e'").fetchone()[0]
    check('w9: POST /webhook/payment runs PaymentAgent end to end',
          settled_answer.status_code == 200 and settled_answer.json().get('action') == 'settled'
          and e2e_sub is not None and e2e_sub['plan'] == 'premium' and e2e_rows == 1,
          f'{settled_answer.json()} {dict(e2e_sub) if e2e_sub else None} rows={e2e_rows}')
    check('w9: the settled payment reached RevenueTracker and left a snapshot',
          not [key for key in ho.pending() if 'revenuetracker' in key]
          and Path(finance.snapshot_path(time.time())).exists(), str(list(ho.pending())))

    revenue_reply = w7commands.handle_command('/revenue', now=now)
    security_reply = w7commands.handle_command('/security', now=now)
    subs_reply = w7commands.handle_command('/subscriptions', now=now)
    check('w9: /revenue, /security and /subscriptions answer from real rows',
          revenue_reply.get('ok') is True and 'file:' in revenue_reply.get('reply', '')
          and Path(str(revenue_reply.get('path'))).exists()
          and security_reply.get('ok') is True and 'insiden' in security_reply.get('reply', '')
          and subs_reply.get('ok') is True and 'subscription' in subs_reply.get('reply', ''),
          str(revenue_reply)[:160])
    check('w9: the chargeback trigger is wired to PaymentAgent',
          w4triggers.AGENT_HANDLERS.get('chargeback_received') is w4triggers._payment_work)
    nodes = set(orch.build_orchestrator_graph().node_names)
    check('w9: PaymentAgent, RevenueTracker, SecOps and EpisodeScheduler are graph nodes',
          {'PaymentAgent', 'RevenueTracker', 'SecOps', 'EpisodeScheduler'} <= nodes,
          str(sorted(nodes)))

    # 13. W10: the dashboard's numbers, and the rest of the chat ---------------
    #     The panel itself is React (tests/biz-metrics-ui.test.ts); what is
    #     checked here is the data it reads and the commands that answer from
    #     the same rows.
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from hermes_bridge import db as bdb
    from hermes_agents import store as bstore

    # SLA: a reply that left is the first response; a failed send is not
    early = support.triage_ticket('sc-w10-sla', 'pertanyaan biasa', user_id='sla@example.com',
                                  now=now - 1800)
    support.send_reply(early['id'], 'halo', to='sla@example.com', now=now - 1200,
                       transport=_Mailbox())
    support.resolve(early['id'], now=now - 600)
    con.execute(
        'INSERT INTO tickets (id, user_id, subject, status, received_at, sla_deadline, '
        'resolved_at, first_response_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        ('sc-w10-late', 'late@example.com', 'telat', 'resolved', now - 7200, now - 3600,
         now - 3000, now - 7000, now - 3000),
    )
    con.commit()
    stats = support.sla_stats(now=now)
    # The W5 tickets in this same DB are resolved too, so the count is a floor;
    # the exact average comes from the two replies this section planted.
    check('w10: sla_stats measures first response, not resolution time',
          stats['samples'] == 2 and stats['resolved'] >= 2 and stats['on_time'] >= 1
          and stats['avg_response_min'] == 7
          and (stats['compliance'] is None or 0.0 <= stats['compliance'] <= 1.0), str(stats))
    first_response = con.execute('SELECT first_response_at FROM tickets WHERE id = ?',
                                 (early['id'],)).fetchone()[0]
    check('w10: send_reply records the first reply that actually left',
          first_response == now - 1200, str(first_response))

    # An older DB gets the new column without a destructive migration
    legacy = tmp / 'legacy.db'
    legacy_con = sqlite3.connect(str(legacy))
    legacy_con.execute('CREATE TABLE tickets (id TEXT PRIMARY KEY)')
    legacy_con.commit()
    legacy_con.close()
    bdb.migrate(legacy)
    legacy_cols = {row[1] for row in sqlite3.connect(str(legacy)).execute(
        'PRAGMA table_info(tickets)')}
    check('w10: migrate() adds first_response_at to an older tickets table',
          'first_response_at' in legacy_cols, str(sorted(legacy_cols)))

    sla_reply = w7commands.handle_command('/sla', now=now)
    tickets_reply = w7commands.handle_command('/tickets', now=now)
    check('w10: /sla and /tickets answer from the ticket rows',
          sla_reply.get('ok') is True and sla_reply['sla']['samples'] == 2
          and 'Rata-rata respons pertama' in sla_reply.get('reply', '')
          and tickets_reply.get('ok') is True
          and tickets_reply['tickets'].get('resolved', 0) >= 2, str(sla_reply)[:160])

    # /biz reads the office's door over HTTP - never the office DB directly
    class _MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's name
            body = json.dumps({
                'today': {'leads_qualified': 4, 'emails_sent': 9, 'tickets_resolved': 2,
                          'tickets_pending': 1, 'crm_updates': 3, 'refunds_processed': 1,
                          'chargebacks': 0},
                'sla': {'avg_response_min': 7, 'breach_count': 1},
                'agents_active': ['Support'],
                'last_updated': '2026-11-17T07:03:00.000Z',
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: D102 - keep the selfcheck output clean
            return

    metrics_server = ThreadingHTTPServer(('127.0.0.1', 0), _MetricsHandler)
    threading.Thread(target=metrics_server.serve_forever, daemon=True).start()
    saved_office_url = os.environ.get('OFFICE_URL')
    os.environ['OFFICE_URL'] = f'http://127.0.0.1:{metrics_server.server_address[1]}'
    biz_reply = w7commands.handle_command('/biz', now=now)
    check('w10: /biz reads GET /biz-metrics from a running office',
          biz_reply.get('ok') is True and biz_reply['today']['leads_qualified'] == 4
          and 'Hari ini' in biz_reply.get('reply', ''), str(biz_reply)[:200])
    metrics_server.shutdown()
    metrics_server.server_close()
    os.environ['OFFICE_URL'] = 'http://127.0.0.1:9'
    offline = w7commands.handle_command('/biz', now=now)
    check('w10: a closed office is reported, not invented',
          offline.get('ok') is False and 'tidak menjawab' in offline.get('reply', ''),
          str(offline)[:160])
    if saved_office_url is None:
        os.environ.pop('OFFICE_URL', None)
    else:
        os.environ['OFFICE_URL'] = saved_office_url

    # /leads: the keys only exist if a Sales agent wrote them
    empty_leads = w7commands.handle_command('/leads', now=now)
    check('w10: /leads reports an empty day without inventing a lead',
          empty_leads.get('ok') is True and 'tidak ada key lead:*' in empty_leads.get('insufficient', '')
          and 'Belum ada lead' in empty_leads.get('reply', ''), str(empty_leads)[:160])
    bstore.context().set('lead:sc-1', {'name': 'Budi', 'stage': 'qualified'}, 'selfcheck')
    one_lead = w7commands.handle_command('/leads', now=now)
    check('w10: /leads lists what SharedContext really holds',
          one_lead.get('ok') is True and one_lead['leads'] == ['lead:sc-1']
          and 'Budi' in one_lead.get('reply', ''), str(one_lead)[:160])

    # /topselling: no per-item sales source, and the command says so
    selling = w7commands.handle_command('/topselling', now=now)
    check('w10: /topselling states the missing sales source instead of ranking by price',
          selling.get('ok') is True and 'item_id' in selling.get('insufficient', '')
          and 'Ranking terlaris belum ada' in selling.get('reply', ''), str(selling)[:160])

    # /incidents and /unban: the audit log, append-only
    sec_ops.apply_rule('login_attempts', '10.9.9.9', 'ban_ip', 'selfcheck w10', now=now,
                       actor='SecOps')
    incident_reply = w7commands.handle_command('/incidents', now=now)
    banned_rows = con.execute('SELECT COUNT(*) FROM security_incidents WHERE target = ?',
                              ('10.9.9.9',)).fetchone()[0]
    unban_reply = w7commands.handle_command('/unban 10.9.9.9', now=now)
    unban_rows = con.execute('SELECT COUNT(*) FROM security_incidents WHERE target = ?',
                             ('10.9.9.9',)).fetchone()[0]
    check('w10: /incidents lists the rows /security summarises',
          incident_reply.get('ok') is True and incident_reply['incidents'],
          str(incident_reply)[:160])
    check('w10: /unban adds a row, never deletes one',
          unban_reply.get('ok') is True and unban_reply['was_banned'] is True
          and not sec_ops.is_banned('10.9.9.9') and unban_rows == banned_rows + 1,
          f'{unban_reply} rows {banned_rows}->{unban_rows}')
    check('w10: /unban without a target asks for one',
          w7commands.handle_command('/unban', now=now).get('ok') is False)

    # /schedule and /embargo read the embargo queue
    sched.schedule_episode(con, episode_id='sc-w10-embargo', anime_title='W10', episode_number=1,
                           encoded_path='/tmp/w10.mp4', embargo_until=now + 3600)
    schedule_reply = w7commands.handle_command('/schedule', now=now)
    embargo_reply = w7commands.handle_command('/embargo sc-w10-embargo', now=now)
    check('w10: /schedule and /embargo answer from episode_schedule',
          schedule_reply.get('ok') is True and 'sc-w10-embargo' in schedule_reply.get('upcoming', [])
          and embargo_reply.get('ok') is True
          and embargo_reply['episode']['status'] == 'scheduled'
          and 'scheduled' in embargo_reply.get('reply', ''), str(embargo_reply)[:160])

    # /translations and /approve-sub: needs_review -> approved
    bstore.upsert_track(con, 'sc-w10-subs', 'id', '/tmp/w10.id.srt', source='local',
                        status='needs_review', qa_score=0.8, updated_at=now)
    translations_reply = w7commands.handle_command('/translations', now=now)
    handled_sub = w7commands.handle_command('/approve-sub sc-w10-subs', now=now)
    sub_status = con.execute("SELECT status FROM subtitle_tracks WHERE episode_id = 'sc-w10-subs' "
                             "AND lang = 'id'").fetchone()[0]
    check('w10: /translations and /approve-sub move a real subtitle track',
          translations_reply.get('ok') is True
          and translations_reply['translations'].get('needs_review', 0) >= 1
          and handled_sub.get('approved') == 1 and sub_status == 'approved',
          f'{handled_sub} {sub_status}')
    check('w10: /approve-sub without an id lists what needs review',
          w7commands.handle_command('/approve-sub', now=now).get('ok') is True and sub_status == 'approved')

    # /reports and /report-stats: today and the seven-day trend
    con.execute(
        'INSERT OR REPLACE INTO user_reports (id, user_id, episode_id, category, description, '
        'status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        ('rp-w10-1', 'u-w10', 'ep-w10', 'technical', 'video buffering terus', 'pending', now),
    )
    con.commit()
    reports_reply = w7commands.handle_command('/reports', now=now)
    stats_reply = w7commands.handle_command('/report-stats', now=now)
    check('w10: /reports and /report-stats answer from user_reports',
          reports_reply.get('ok') is True and reports_reply['reports'].get('pending', 0) >= 1
          and stats_reply.get('ok') is True and sum(stats_reply['days'].values()) >= 1,
          f'{reports_reply} {stats_reply}'[:200])

    check('w10: every command in API-REFERENCE §6 is registered, and none answers nothing',
          len(w7commands.COMMANDS) == 23
          and {'/biz', '/leads', '/tickets', '/sla', '/topselling', '/incidents', '/unban',
               '/schedule', '/embargo', '/translations', '/approve-sub', '/reports',
               '/report-stats'} <= set(w7commands.COMMANDS)
          and all(w7commands.handle_command(name, now=now).get('handled') is True
                  for name in w7commands.COMMANDS))

    # 14. W8 sisa: agent Sales + Marketing — lead, form, dan tahap deal --------
    from hermes_agents import sales as sales_mod

    sales_mailbox = _Mailbox()
    lead_payload = {
        'lead_id': 'sc-lead-1', 'name': 'Rina', 'email': 'rina@studio.co.id',
        'plan': 'premium_plus', 'budget_idr': 200000, 'company': 'Studio Rina',
        'company_size': 14, 'source': 'referral',
    }
    qualified = sales_mod.handle_trigger('new_lead', lead_payload, now=now,
                                         transport=sales_mailbox)
    lead_record = ctx.get('lead:sc-lead-1') or {}
    check('w8: new_lead scores a lead from stated rules and stores it in lead:*',
          qualified['action'] == 'qualified'
          and qualified['score'] >= sales_mod.QUALIFY_MIN_SCORE
          and len(qualified['reasons']) >= 3
          and lead_record.get('stage') == 'qualified'
          and lead_record.get('email') == 'rina@studio.co.id', str(qualified)[:200])
    check('w8: a qualified lead gets one acknowledgement mail and one handoff to Marketing',
          qualified['mail']['sent'] is True and len(sales_mailbox.sent) == 1
          and qualified['handoff'] == 'handoff:sales:marketing:sc-lead-1'
          and ho.get(qualified['handoff'], context=ctx) is not None,
          f'{qualified.get("mail")} {qualified.get("handoff")}')
    repeat_form = sales_mod.handle_trigger('form_submit', lead_payload, now=now,
                                           transport=sales_mailbox)
    check('w8: the same form twice does not mail, count, or hand off twice',
          repeat_form['action'] == 'duplicate' and len(sales_mailbox.sent) == 1
          and len(ho.pending_from('Sales', context=ctx)) == 1, str(repeat_form)[:160])

    weak = sales_mod.handle_trigger('form_submit',
                                    {'name': 'Budi', 'email': 'budi@gmail.com',
                                     'source': 'web'}, now=now, transport=sales_mailbox)
    check('w8: a form with weak signal is nurtured, not handed to Marketing',
          weak['action'] == 'nurture' and weak['score'] < sales_mod.QUALIFY_MIN_SCORE
          and weak.get('handoff') is None and weak.get('mail') is None
          and len(sales_mailbox.sent) == 1, str(weak)[:160])

    chain = orch.follow_handoffs('Sales')
    campaign = ctx.get('campaign:sc-lead-1') or {}
    onboarding = con.execute(
        "SELECT id, user_id, status FROM tickets WHERE subject LIKE 'Onboarding%' "
        'ORDER BY received_at DESC LIMIT 1').fetchone()
    check('w8: Sales -> Marketing -> Support runs on the real agents',
          [(hop['from'], hop['to']) for hop in chain]
          == [('Sales', 'Marketing'), ('Marketing', 'Support')]
          and campaign.get('lead') == 'sc-lead-1' and onboarding is not None
          and onboarding['user_id'] == 'rina@studio.co.id', f'{chain} {campaign} {onboarding}')
    check('w8: Marketing reports the missing SMTP instead of claiming a welcome letter',
          campaign.get('sent') is False and 'SMTP' in str(campaign.get('reason')),
          str(campaign)[:160])
    check('w8: the chain consumed both handoffs',
          ho.pending(context=ctx) == {}, str(list(ho.pending(context=ctx))))

    meeting = sales_mod.handle_trigger(
        'deal_stage_change',
        {'lead_id': 'sc-lead-1', 'stage': 'meeting', 'when': '2026-11-18T10:00:00+07:00',
         'timezone': 'Asia/Jakarta', 'needs': 'demo paket premium_plus'}, now=now)
    brief_chain = orch.follow_handoffs('Sales')
    brief = ctx.get('brief:sc-lead-1') or {}
    check('w8: a meeting writes the Sales -> Support handoff Support briefs',
          meeting['action'] == 'stage_changed' and meeting['stage'] == 'meeting'
          and [(hop['from'], hop['to']) for hop in brief_chain] == [('Sales', 'Support')]
          and brief.get('timezone') == 'Asia/Jakarta'
          and brief.get('needs') == 'demo paket premium_plus', f'{meeting} {brief_chain} {brief}')
    no_slot = sales_mod.handle_trigger('deal_stage_change',
                                       {'lead_id': 'sc-lead-1', 'stage': 'meeting'}, now=now)
    check('w8: a meeting without when/timezone is refused, not half-written',
          no_slot['action'] == 'refused' and 'when' in no_slot.get('reason', '')
          and (ctx.get('lead:sc-lead-1') or {}).get('stage') == 'meeting', str(no_slot))

    won = sales_mod.handle_trigger('deal_stage_change',
                                   {'lead_id': 'sc-lead-1', 'stage': 'closed_won'}, now=now)
    check('w8: closed_won is an alias for won, and hands the lead to Marketing',
          won['action'] == 'stage_changed' and won['stage'] == 'won'
          and won['handoff'] == 'handoff:sales:marketing:sc-lead-1'
          and (ctx.get('lead:sc-lead-1') or {}).get('status') == 'converted', str(won)[:200])
    repeat_chain = orch.follow_handoffs('Sales')
    check('w8: a second conversion does not send a second welcome letter',
          len(repeat_chain) == 1 and repeat_chain[0]['work'].get('duplicate') is True
          and ho.pending(context=ctx) == {}, str(repeat_chain)[:200])

    unknown_stage = sales_mod.handle_trigger('deal_stage_change',
                                             {'lead_id': 'sc-lead-1', 'stage': 'teleported'}, now=now)
    unknown_lead = sales_mod.handle_trigger('deal_stage_change',
                                            {'lead_id': 'sc-tidak-ada', 'stage': 'contacted'}, now=now)
    check('w8: an unknown stage or an unknown lead is refused with the reason',
          unknown_stage['action'] == 'refused' and 'won' in unknown_stage.get('allowed', [])
          and unknown_lead['action'] == 'refused'
          and 'tidak ada di SharedContext' in unknown_lead.get('reason', ''),
          f'{unknown_stage} {unknown_lead}'[:200])

    leads_reply = w7commands.handle_command('/leads', now=now)
    check('w8: /leads lists what the Sales agent wrote, with stage and score',
          leads_reply.get('ok') is True and 'lead:sc-lead-1' in leads_reply.get('leads', [])
          and 'won' in leads_reply.get('reply', '')
          and 'skor' in leads_reply.get('reply', ''), str(leads_reply)[:200])
    stuck = ho.hand_off('Sales', 'Marketing', 'lead_converted', 'lead:sc-stuck',
                        {'name': 'Nadia', 'email': 'nadia@toko.id', 'score': 0.8,
                         'plan': 'premium'}, now=now, context=ctx)
    pipeline_reply = w7commands.handle_command('/leads', now=now)
    check('w8: /leads counts the pipeline per stage and shows the stuck handoff',
          pipeline_reply['pipeline'].get('won') == 1
          and pipeline_reply['pipeline'].get('qualified', 0) >= 1
          and pipeline_reply['pipeline'].get('new', 0) >= 1
          and pipeline_reply['handoffs'].get('Sales→Marketing') == 1
          and stuck in pipeline_reply['waiting']
          and 'Handoff lead tertunda' in pipeline_reply.get('reply', ''),
          str(pipeline_reply)[:240])
    ho.drop(stuck, context=ctx)
    cleared = w7commands.handle_command('/leads', now=now)
    check('w8: a taken or dropped handoff leaves the pipeline view',
          cleared['handoffs'] == {} and cleared['waiting'] == [], str(cleared)[:200])

    via_webhook = w4triggers.run_trigger(
        'new_lead', {'name': 'Tono', 'email': 'tono@kedai.id', 'plan': 'premium',
                     'budget_idr': 75000}, source='selfcheck')
    check('w8: the new_lead trigger path runs Sales and follows its chain headless',
          (via_webhook.get('work') or {}).get('action') == 'qualified'
          and [(hop['from'], hop['to']) for hop in via_webhook.get('chain') or []]
          == [('Sales', 'Marketing'), ('Marketing', 'Support')]
          and via_webhook.get('office') is False, str(via_webhook)[:240])
    check('w8: the three Sales triggers run the agent, and Sales/Marketing are graph nodes',
          all(w4triggers.AGENT_HANDLERS.get(name) is w4triggers._sales_work
              for name in ('new_lead', 'form_submit', 'deal_stage_change'))
          and {'Sales', 'Marketing'} <= set(orch.build_orchestrator_graph().node_names),
          str(sorted(orch.build_orchestrator_graph().node_names)))

    support.close()

    print()
    if FAILS:
        print(f'{len(FAILS)} check(s) failed: {", ".join(FAILS)}')
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
