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
    check('w4: the scheduler registers the eight jobs that exist',
          ids == ['approval_sweep', 'db_backup', 'email_check', 'episode_embargo', 'handoff_check',
                  'ops_check', 'shared_context_cleanup', 'sla_check'], str(ids))
    check('w4: starting twice does not double the jobs', sched1 is sched2 and len(ids) == 8)
    check('w4: /health can list the running jobs',
          len(registered_jobs()) == 8 and len(pending_jobs()) == 3)
    check('w4: the three unbuilt jobs are named, not faked',
          len(PENDING_JOBS) == 3 and all(reason.strip() for reason in PENDING_JOBS.values()))
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
    check('w5: email_check and ops_check are registered, leaving three pending',
          'email_check' not in pending_ids and 'ops_check' not in pending_ids
          and len(pending_ids) == 3, str(pending_ids))

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
    check('w8: handoff_check is registered, leaving three pending jobs',
          'handoff_check' not in pending_ids and len(pending_ids) == 3, str(pending_ids))

    support.close()

    print()
    if FAILS:
        print(f'{len(FAILS)} check(s) failed: {", ".join(FAILS)}')
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
