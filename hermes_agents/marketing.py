"""marketing.py - MarketingAgent: the Monday report and the welcome campaign.

Two jobs, both from AGENTS.md §4.1:

- `weekly_report()` — the Monday 09.00 report, fired by the `weekly_report` job
  through the `weekly_analytics` trigger. A markdown file under
  `media/published/reports/`, written every week whether or not anyone reads it,
  plus a one-line summary to Discord when `DISCORD_WEBHOOK_URL` is set. Every
  section states where its numbers came from (`growth_data.py` labels the
  source): a week with no AniWatch export says so in the report instead of
  showing a watch-time chart nobody measured.
- `onboard_lead()` — the `lead_converted` handoff Sales leaves after a lead is
  qualified: one welcome letter through `mailer` (the same SMTP channel Support
  uses), one campaign record in `campaign:<lead>`, then a handoff to Support for
  the follow-up. A second conversion for the same lead does not send a second
  letter; the record says what happened the first time.
- `retry_welcome()` — the other half of that promise. A letter whose first
  attempt did not leave (no `SMTP_HOST`, a dead relay) is retried on a widening
  backoff by the `campaign_retry` job. The retry re-reads the campaign record and
  sends only the letter: it never writes a handoff, so Support never gets a
  second onboarding ticket for the same customer. After
  `MAX_WELCOME_ATTEMPTS` the record stays `sent: False` with its last error, which
  is a person's problem instead of an infinite loop.

Neither job invents numbers or sends. Without `SMTP_HOST` the welcome letter is
`sent: False` with the reason in the campaign record, and the lead stays
qualified - the missing mail is visible, not hidden.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from hermes_bridge import handoff

from . import channels, config, growth_data, store

log = logging.getLogger(__name__)

REPORT_DIR = 'reports'

#: Where one onboarding campaign per lead is recorded
CAMPAIGN_PREFIX = 'campaign:'

WELCOME_SUBJECT = 'Selamat datang di AniWatch'

#: First try included: one letter, then three retries before a person looks
MAX_WELCOME_ATTEMPTS = 4

#: Wait after the first attempt, doubled per attempt (15m, 30m, 60m). A dead
#: relay is not fixed in seconds, and a retry storm is how domains get blocked.
WELCOME_RETRY_S = 900.0


def _retry_delay(attempts: int) -> float:
    """How long after attempt `attempts` the next one is allowed."""
    return WELCOME_RETRY_S * (2 ** max(0, int(attempts) - 1))


def _next_try(record: dict) -> float | None:
    """When this letter may be tried again; None when it is done being tried."""
    if record.get('sent') or int(record.get('attempts') or 0) >= MAX_WELCOME_ATTEMPTS:
        return None
    return float(record.get('last_at') or record.get('at') or 0) + _retry_delay(int(record.get('attempts') or 0))


def week_label(now: float) -> str:
    """`2026-W47`, the ISO week the report covers."""
    return time.strftime('%G-W%V', time.localtime(now))


def _render(data: dict, at: float) -> str:
    local = data['local']
    lines = [
        f'# Laporan mingguan — {week_label(at)}',
        '',
        f'Dibuat {time.strftime("%d %b %Y %H:%M", time.localtime(at))} · '
        f'sumber angka: `{data["source"]}`',
        '',
        '## Pipeline',
        '',
        f'- Episode live: **{local["episodes_live"]}**',
        f'- Rilis 7 hari terakhir: **{local["episodes_released_7d"]}**',
        '',
        '## Support',
        '',
        f'- Tiket terbuka/pending/eskalasi: **{local["tickets_open"]}**',
        f'- Tiket selesai 7 hari: **{local["tickets_resolved_7d"]}**',
        f'- Laporan user 7 hari: **{local["user_reports_7d"]}**',
        '',
        '## Tontonan',
        '',
    ]
    if data['feed'] is None:
        lines.append('Belum ada export AniWatch (`ANALYTICS_FEED`), jadi angka tontonan, watch time '
                     'dan drop-off minggu ini belum bisa dilaporkan.')
    else:
        lines.append(f'- Episode di export: **{data["feed"]["episodes"]}**')
        lines.append(f'- User dengan histori: **{data["feed"]["users_with_history"]}**')
        lines.append('')
        if data['dropoffs']:
            lines.append('### Drop-off (viewer tidak selesai > 50%)')
            lines.append('')
            for row in data['dropoffs'][:10]:
                lines.append(f'- `{row["episode_id"]}`: {row["completion_rate"] * 100:.0f}% selesai '
                             f'dari {row["views"]} viewer')
        else:
            lines.append('Tidak ada episode yang kehilangan lebih dari separuh viewernya.')
    lines.append('')
    return '\n'.join(lines)


class MarketingAgent:
    """One weekly report: numbers, a file, and a summary where people look."""

    def weekly_report(self, now: float | None = None) -> dict:
        from . import store

        at = time.time() if now is None else float(now)
        con = store.connect()
        try:
            data = growth_data.snapshot(con, at)
        finally:
            con.close()
        text = _render(data, at)
        relative = f'{REPORT_DIR}/weekly-{week_label(at)}.md'
        out = config.media_root() / 'published' / relative
        out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        out.write_text(text, encoding='utf-8')

        summary = (f'📊 Laporan mingguan {week_label(at)}: '
                   f'{data["local"]["episodes_live"]} episode live, '
                   f'{data["local"]["tickets_open"]} tiket terbuka, '
                   f'{len(data["dropoffs"])} drop-off.')
        posted = channels.discord(summary)
        log.info('marketing: laporan %s (discord=%s)', out, posted['posted'])
        return {
            'report': str(out),
            'week': week_label(at),
            'source': data['source'],
            'episodes_live': data['local']['episodes_live'],
            'dropoffs': len(data['dropoffs']),
            'discord': posted['posted'],
            'discord_reason': posted['reason'],
        }


def _metric(delta: dict) -> None:
    """One counter; a metrics failure must not undo a sent letter."""
    from hermes_bridge import bridge

    try:
        bridge.update_biz_metrics(delta)
    except Exception as err:  # noqa: BLE001 - the campaign record is the source, not the panel
        log.warning('marketing: metric %s tidak terkirim: %s', delta, err)


def welcome_body(lead: dict) -> str:
    """The letter a converted lead gets: what they chose, and what happens next."""
    name = ' '.join(str(lead.get('name') or '').split())[:80] or 'Halo'
    plan = str(lead.get('plan') or 'free')
    channel = str(lead.get('channel') or lead.get('source') or 'web')
    return (
        f'Halo {name},\n\n'
        'Selamat datang di AniWatch. Akun Anda sudah kami siapkan'
        + (f' pada paket {plan}' if plan != 'free' else '')
        + f', dan kami mencatat Anda datang lewat {channel}.\n\n'
        'Beberapa hal yang bisa langsung Anda pakai:\n'
        '- Katalog episode terbaru dengan subtitle Indonesia\n'
        '- Riwayat tontonan dan rekomendasi personal\n'
        '- Pengaturan langganan dan pembayaran di halaman akun\n\n'
        'Kalau ada pertanyaan, balas email ini - tim support kami yang menjawab, '
        'bukan robot.\n\nSalam,\nTim AniWatch'
    )


def onboard_lead(payload: object, *, now: float | None = None, transport=None) -> dict:
    """The `lead_converted` handoff: welcome, record the campaign, brief Support.

    One letter per lead, ever: the campaign record is checked before sending, so
    a second conversion (a deal that closes after the form already qualified it)
    reports `duplicate` instead of mailing the customer again.
    """
    from . import mailer

    at = time.time() if now is None else float(now)
    data = payload if isinstance(payload, dict) else {}
    lead_id = str(data.get('lead_id') or data.get('subject') or '').split(':')[-1]
    email = ' '.join(str(data.get('email') or '').split())[:200]
    if not email:
        return {'action': 'skipped', 'reason': 'payload tanpa email', 'lead': lead_id or None}
    if not lead_id:
        lead_id = email.lower()

    key = f'{CAMPAIGN_PREFIX}{lead_id}'
    existing = store.context().get(key)
    # Any earlier attempt counts: a deal that closes after the form already
    # qualified the lead must not mail the customer twice or open a second
    # onboarding ticket. The record still says whether that attempt left.
    if isinstance(existing, dict) and int(existing.get('attempts') or 0) >= 1:
        log.info('marketing: kampanye %s sudah dicoba - tidak diulang', lead_id)
        # An unsent letter is not re-mailed here: the `campaign_retry` job owns
        # the backoff, so a burst of conversions cannot become a burst of mail.
        return {'action': 'campaign_sent' if existing.get('sent') else 'welcome_skipped',
                'lead': lead_id, 'duplicate': True, 'sent': bool(existing.get('sent')),
                'sent_at': existing.get('sent_at') or existing.get('at'),
                'retry_at': _next_try(existing), 'handoff': None,
                'reason': 'surat selamat datang untuk lead ini sudah dicoba sebelumnya'}

    plan = str(data.get('plan') or 'free')
    channel = str(data.get('channel') or data.get('source') or 'web')
    result = mailer.send(email, WELCOME_SUBJECT, welcome_body({**data, 'plan': plan,
                                                              'channel': channel}),
                         transport=transport, now=at)
    sent = bool(result.get('sent'))
    if sent:
        _metric({'emails_sent': 1})

    handoff_key = None
    handoff_reason = None
    try:
        handoff_key = handoff.hand_off(
            'Marketing', 'Support', 'customer_onboarding', f'lead:{lead_id}',
            {'plan': plan, 'channel': channel, 'email': email},
            now=at,
        )
    except (ValueError, handoff.UnknownHandoff) as err:
        handoff_reason = f'handoff tidak ditulis: {err}'
        log.warning('marketing: %s', handoff_reason)

    record = {
        'lead': lead_id, 'name': str(data.get('name') or '')[:80], 'email': email,
        'plan': plan, 'channel': channel, 'sent': sent, 'reason': result.get('error'),
        'at': at, 'last_at': at, 'outbox': result.get('outbox'), 'attempts': 1,
        'sent_at': at if sent else None, 'handoff': handoff_key,
    }
    record['next_try_at'] = _next_try(record)
    store.context().set(key, record, 'Marketing')
    log.info('marketing: kampanye %s (terkirim=%s) -> Support', lead_id, sent)
    return {'action': 'welcome_sent' if sent else 'welcome_skipped', 'lead': lead_id,
            'sent': sent, 'reason': result.get('error'), 'plan': plan, 'channel': channel,
            'handoff': handoff_key, 'handoff_reason': handoff_reason,
            'metric': {'emails_sent': 1} if sent else None}


def retry_welcome(*, now: float | None = None, transport=None) -> dict:
    """Resend welcome letters whose earlier attempt did not leave.

    The campaign record is the source of truth and the only thing written back:
    no handoff, no ticket, no second campaign. A record that already went out or
    used up `MAX_WELCOME_ATTEMPTS` is left alone, and the result says which
    records are still waiting, so a quiet run is distinguishable from a broken
    one.
    """
    from . import mailer

    at = time.time() if now is None else float(now)
    records = store.context().find(CAMPAIGN_PREFIX)
    sent: list[dict] = []
    failed: list[dict] = []
    waiting = 0
    gave_up: list[str] = []

    for key, value in sorted(records.items()):
        record = value if isinstance(value, dict) else {}
        if record.get('sent'):
            continue
        tries = int(record.get('attempts') or 0)
        if tries >= MAX_WELCOME_ATTEMPTS:
            gave_up.append(key)
            continue
        due = float(record.get('last_at') or record.get('at') or 0) + _retry_delay(tries)
        if at < due:
            waiting += 1
            continue

        lead_id = str(record.get('lead') or key.split(':', 1)[-1])
        result = mailer.send(record.get('email') or '', WELCOME_SUBJECT,
                             welcome_body(record), transport=transport, now=at)
        left = bool(result.get('sent'))
        updated = {
            **record, 'sent': left, 'reason': result.get('error'),
            'last_error': result.get('error') or record.get('last_error'),
            'last_at': at, 'attempts': tries + 1,
            'outbox': result.get('outbox') or record.get('outbox'),
            'sent_at': at if left else None,
        }
        updated['next_try_at'] = _next_try(updated)
        store.context().set(key, updated, 'Marketing')
        if left:
            _metric({'emails_sent': 1})
            sent.append({'lead': lead_id, 'email': record.get('email'),
                         'attempts': tries + 1})
            log.info('marketing: surat selamat datang %s terkirim pada percobaan %d',
                     lead_id, tries + 1)
        else:
            failed.append({'lead': lead_id, 'error': result.get('error'),
                           'attempts': tries + 1})

    return {'checked': len(records), 'sent': sent, 'failed': failed,
            'waiting': waiting, 'gave_up': gave_up}


def gave_up_campaigns() -> list[dict]:
    """Welcome letters that used up every attempt and are now a person's problem.

    The `campaign_retry` job stops at `MAX_WELCOME_ATTEMPTS` and leaves the record
    `sent: False`; without a reader those failures only exist for whoever opens
    SharedContext. `/biz` and `/leads` call this so a broken relay is visible in
    the chat, next to the pipeline it affects.
    """
    records = store.context().find(CAMPAIGN_PREFIX)
    out: list[dict] = []
    for key, value in sorted(records.items()):
        record = value if isinstance(value, dict) else {}
        tries = int(record.get('attempts') or 0)
        if record.get('sent') or tries < MAX_WELCOME_ATTEMPTS:
            continue
        out.append({
            'lead': str(record.get('lead') or key.split(':', 1)[-1]),
            'email': record.get('email'),
            'attempts': tries,
            'last_error': record.get('last_error') or record.get('reason'),
            'last_at': record.get('last_at') or record.get('at'),
        })
    return out


def handle_trigger(payload: object, char: Any = None) -> dict:
    """Entry point for `weekly_analytics` (fired by the `weekly_report` job)."""
    data = payload if isinstance(payload, dict) else {}
    now = data.get('now')
    agent = MarketingAgent()
    if char:
        char.update('fetch_analytics + generate_report', tool='fetch_analytics')
    report = agent.weekly_report(now=now if isinstance(now, (int, float)) else None)
    if char:
        char.update(f'laporan {report["week"]} ({report["source"]})', tool='generate_report')
    return {'action': 'reported', **report}
