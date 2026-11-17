"""commands.py - the business slash commands the chat panel sends (W7).

The chat panel is the office's own surface (`POST /chat` -> `server/biz-events.js`),
and the work lives in Python, so a business command is relayed here and answered
with one short chat line (API-REFERENCE.md §6: one message, at most six lines).

The commands W7 and W9 introduce:

    /design [kind] [tema]   create the item, design/QA/price/preview it
    /pending-items          what is waiting for approval
    /approve [id]           the same decision the card's Approve button makes
    /revenue                today + 7 days, from payment_events, and the snapshot file
    /payments               today's notifications by status
    /subscriptions          plans, grace and expired rows
    /refunds                refunds waiting for a person
    /chargeback             the latest chargebacks
    /security               SecOps incidents in the last 24 hours
    /takedown [id] [alasan] DMCA: cancel a schedule, or unpublish a live episode

W10 adds the rest of API-REFERENCE.md §6, split by where the answer comes from:

    /biz                    the office's own counters (GET /biz-metrics)
    /leads                  the `lead:*` pipeline per stage, today's leads, waiting handoffs
    /tickets                tickets by status, with the newest open ones
    /sla                    compliance + the tickets past their deadline
    /topselling             what a sale per item would need; no ranking is invented
    /incidents              the latest rows of `security_incidents`
    /unban <ip|user>        a person lifts a block (a new row, never a delete)
    /schedule               the embargo queue and what publishes next
    /embargo [id]           one schedule's detail, or the next few
    /translations           subtitle tracks by status
    /approve-sub [id]       needs_review -> approved, for one episode
    /reports                today's user reports
    /report-stats           the last 7 days, per day and per category

One of those is deliberately an answer about missing data, not a fake number:
`/topselling` says `payment_events` has no `item_id`, so there is no per-item
ranking to print. A chat line that claimed otherwise would be the only part of
the office not checked against the DB.

`/leads` reports two different windows in one message and labels them: stage
counts over every `lead:*` record (a deal won last week is still won), and the
leads that came in today. Pending handoffs whose subject is a `lead:` are shown
next to them, because "qualified but nobody picked it up" is the failure a
pipeline view exists to catch.

`/approve` calls `premium.decide`, which is the only writer out of
`pending_approval`; the card's answer goes through the same function from
`premium.request_approval`. That is what makes both doors end in the same status
(PLAN.md W7), and it is checked in `hermes_agents.selfcheck`.

`/takedown` is the door a takedown has in this fork: there is no webhook type for
it (the 13 in API-REFERENCE.md §4 stay as they are), so a notice that arrives by
email becomes this command, and `dmca.handle_takedown` writes the audit row.

The design card is not raised here on purpose: a card blocks until someone
presses it, and this module is called from a request. The route queues
`premium.request_approval` in a worker thread instead (`webhook_server/main.py`).
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

#: What the chat accepts, in the order API-REFERENCE.md §6 lists them
COMMANDS = ('/design', '/pending-items', '/approve', '/revenue', '/payments',
            '/subscriptions', '/refunds', '/chargeback', '/security', '/takedown',
            '/biz', '/leads', '/tickets', '/sla', '/topselling', '/incidents',
            '/unban', '/schedule', '/embargo', '/translations', '/approve-sub',
            '/reports', '/report-stats')

#: Chat panel, not a dashboard: the office's own rule for business replies
MAX_LINES = 6
MAX_LINE = 220

_HELP = {
    '/design': 'tulis /design <border|nameplate|profile_effect> <tema>',
    '/approve': 'tulis /approve <id>',
    '/takedown': 'tulis /takedown <episode_id> [alasan]',
    '/unban': 'tulis /unban <ip|user_id>',
    '/embargo': 'tulis /embargo [episode_id]',
    '/approve-sub': 'tulis /approve-sub <episode_id>',
}


def _line(text: object) -> str:
    return ' '.join(str(text or '').split())[:MAX_LINE]


def _reply(*lines: str) -> str:
    kept = [line for line in lines if line][:MAX_LINES]
    return '\n'.join(kept)


def _at(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    """Read-only query on the business DB; the connection is closed here.

    Commands answer from the same rows the agents write, so a chat line can be
    checked against `hermes.db` without trusting a cached number.
    """
    from hermes_agents import store

    con = store.connect()
    try:
        return [dict(row) for row in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def _when(ts: object) -> str:
    """`2026-11-17 14:03` in local time, or `-` when there is no timestamp."""
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return '-'


def _left(ts: object, at: float) -> str:
    """How far an embargo still is: `2.4 jam lagi` / `sudah lewat`."""
    try:
        seconds = float(ts) - at
    except (TypeError, ValueError):
        return '-'
    if seconds <= 0:
        return 'sudah lewat'
    if seconds < 3600:
        return f'{int(seconds // 60)} menit lagi'
    return f'{seconds / 3600:.1f} jam lagi'


def _day_start(at: float) -> float:
    """Local midnight before `at`, for commands that say "hari ini"."""
    t = time.localtime(at)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _design(args: list[str], now: float | None) -> dict:
    from hermes_agents import premium

    kind = (args[0] if args else 'border').lower()
    theme = (args[1] if len(args) > 1 else premium.DEFAULT_THEME).lower()
    if kind not in premium.KINDS:
        return {'handled': True, 'ok': False,
                'reply': f'🎨 kind {kind!r} tidak dikenal. Pilihan: ' + ', '.join(premium.KINDS)}
    if theme not in premium.THEMES:
        return {'handled': True, 'ok': False,
                'reply': f'🎨 tema {theme!r} tidak dikenal. Pilihan: ' + ', '.join(premium.THEMES)}

    item = premium.start(kind, theme, now=now)
    if item.get('error'):
        return {'handled': True, 'ok': False, 'reply': f'🎨 gagal: {item["error"]}'}
    if item.get('status') == 'rejected':
        return {'handled': True, 'ok': False, 'item': item['id'],
                'reply': _reply(f'🎨 {item["id"]} ditolak QA: ' + '; '.join(item.get('problems') or []),
                                '/design lagi untuk mencoba variasi baru')}
    return {
        'handled': True, 'ok': True, 'item': item['id'],
        'approval': item['id'],
        'reply': _reply(
            f'🎨 {item["id"]} {kind}/{theme} siap: {item.get("tier")} '
            f'Rp{item.get("price_idr"):,}'.replace(',', '.'),
            f'👁 preview: {item.get("preview_light")}',
            f'Kartu approval menyusul. /approve {item["id"]} juga bisa.',
        ),
    }


def _pending(now: float | None) -> dict:
    from hermes_agents import premium

    rows = premium.list_items('pending_approval')
    if not rows:
        return {'handled': True, 'ok': True, 'reply': '📭 Tidak ada item premium menunggu approval.'}
    lines = [f'🗂 {len(rows)} item menunggu approval:']
    for row in rows[: MAX_LINES - 2]:
        price = f'Rp{int(row.get("price_idr") or 0):,}'.replace(',', '.')
        lines.append(f'- {row["id"]} {row["kind"]}/{row["theme"]} {row.get("tier")} {price}')
    if len(rows) > MAX_LINES - 2:
        lines.append(f'…dan {len(rows) - (MAX_LINES - 2)} lainnya')
    lines.append('Setujui dengan /approve <id> atau tombol di kartu.')
    return {'handled': True, 'ok': True, 'items': [row['id'] for row in rows],
            'reply': _reply(*lines)}


def _approve(args: list[str], now: float | None) -> dict:
    from hermes_agents import premium

    item_id = (args[0] if args else '').strip()
    if not item_id:
        return {'handled': True, 'ok': False, 'reply': _HELP['/approve']}
    item = premium.get_item(item_id)
    if item is None:
        return {'handled': True, 'ok': False, 'reply': f'❓ Item {item_id} tidak ada.'}
    if item['status'] != 'pending_approval':
        return {'handled': True, 'ok': False, 'item': item_id,
                'reply': f'ℹ️ {item_id} berstatus {item["status"]}, bukan pending_approval.'}

    result = premium.decide(item_id, 'Approve', now=now)
    if result.get('error'):
        return {'handled': True, 'ok': False, 'reply': f'❌ {item_id}: {result["error"]}'}
    if not result.get('published'):
        return {'handled': True, 'ok': False, 'item': item_id,
                'reply': f'⚠️ {item_id} disetujui tapi belum live: {result.get("reason")}'}
    return {'handled': True, 'ok': True, 'item': item_id, 'status': result.get('status'),
            'reply': _reply(f'🚀 {item_id} live di toko ({result.get("tier")} '
                            f'Rp{int(result.get("price_idr") or 0):,})'.replace(',', '.'),
                            f'manifest: {result.get("manifest")}')}


def _revenue(now: float | None) -> dict:
    from hermes_agents import finance

    snap = finance.revenue_summary(now=now)
    lines = [
        f'💵 24 jam: {finance.rupiah(snap["today"]["idr"])} dari {snap["today"]["orders"]} order',
        f'📅 7 hari: {finance.rupiah(snap["week"]["idr"])} dari {snap["week"]["orders"]} order',
    ]
    if snap.get('refund_queue'):
        lines.append(f'⏳ {snap["refund_queue"]} refund menunggu approval (/refunds)')
    found = snap.get('anomalies') or []
    lines.append('🔎 anomali: ' + '; '.join(str(row.get('detail')) for row in found)
                 if found else '🔎 anomali: tidak ada')
    lines.append(f'file: {snap["path"]}')
    return {'handled': True, 'ok': True, 'revenue': snap['today'],
            'path': snap['path'], 'reply': _reply(*lines)}


def _payments(now: float | None) -> dict:
    from hermes_agents import finance

    summary = finance.payment_summary(now=now)
    if not summary['total']:
        return {'handled': True, 'ok': True, 'reply': '💳 Belum ada notifikasi payment dalam 24 jam.'}
    counts = ', '.join(f'{name} {count}' for name, count in sorted(summary['by_status'].items()))
    return {'handled': True, 'ok': True, 'payments': summary['by_status'],
            'reply': _reply(f'💳 {summary["total"]} notifikasi dalam 24 jam: {counts}',
                            'Detail per order ada di /revenue.')}


def _subscriptions(now: float | None) -> dict:
    from hermes_agents import finance

    summary = finance.subscription_summary(now=now)
    if not summary['total']:
        return {'handled': True, 'ok': True,
                'reply': '📭 Belum ada subscription_status: PaymentAgent belum menerima notifikasi.'}
    plans = ', '.join(f'{name} {count}' for name, count in sorted(summary['plans'].items()))
    return {'handled': True, 'ok': True, 'subscriptions': summary,
            'reply': _reply(f'👥 {summary["total"]} baris subscription: {plans}',
                            f'⏳ grace: {summary["in_grace"]}, kedaluwarsa: {summary["expired"]}')}


def _refunds(now: float | None) -> dict:
    from hermes_agents import finance

    rows = finance.refund_queue()
    if not rows:
        return {'handled': True, 'ok': True, 'reply': '📭 Tidak ada refund menunggu approval.'}
    lines = [f'💸 {len(rows)} refund menunggu approval:']
    for row in rows[: MAX_LINES - 2]:
        lines.append(f'- {row["order_id"]} {finance.rupiah(row.get("amount_idr"))} '
                     f'({row.get("user_id")})')
    lines.append('Keputusan lewat kartu di kantor; timeout tidak mengubah status.')
    return {'handled': True, 'ok': True, 'refunds': [row['order_id'] for row in rows],
            'reply': _reply(*lines)}


def _chargeback(now: float | None) -> dict:
    from hermes_agents import finance

    rows = finance.recent_chargebacks()
    if not rows:
        return {'handled': True, 'ok': True, 'reply': '✅ Tidak ada chargeback tercatat.'}
    lines = [f'⚠️ {len(rows)} chargeback terakhir:']
    for row in rows[: MAX_LINES - 1]:
        lines.append(f'- {row["order_id"]} {finance.rupiah(row.get("amount_idr"))} '
                     f'({row.get("user_id")})')
    return {'handled': True, 'ok': True, 'chargebacks': [row['order_id'] for row in rows],
            'reply': _reply(*lines)}


def _security(now: float | None) -> dict:
    from hermes_agents import sec_ops

    summary = sec_ops.summary(hours=24.0, now=now)
    actions = ', '.join(f'{name} {count}' for name, count in sorted(summary['by_action'].items()))
    lines = [f'🔐 {summary["incidents"]} insiden 24 jam' + (f': {actions}' if actions else '')]
    if summary.get('feed_missing'):
        lines.append('ℹ️ ' + summary['feed_missing'])
    chargebacks = summary.get('chargebacks') or {}
    if chargebacks:
        lines.append('💳 chargeback per akun: ' + ', '.join(
            f'{user} {count}' for user, count in sorted(chargebacks.items()))[:MAX_LINE])
    return {'handled': True, 'ok': True, 'security': summary, 'reply': _reply(*lines)}


def _takedown(args: list[str], now: float | None) -> dict:
    from hermes_agents import dmca

    episode_id = (args[0] if args else '').strip()
    if not episode_id:
        return {'handled': True, 'ok': False, 'reply': _HELP['/takedown']}
    reason = ' '.join(args[1:]).strip() or 'takedown via chat'
    result = dmca.handle_takedown({'episode_id': episode_id, 'requester': 'CEO (chat)',
                                   'reason': reason}, now=now)
    if result.get('action') == 'refused':
        return {'handled': True, 'ok': False, 'takedown': result.get('id'),
                'reply': _reply(f'⚖️ ditolak: {result.get("reason")}',
                                'Sertakan episode_id, peminta, dan alasan.')}
    if result.get('action') == 'unknown_episode':
        return {'handled': True, 'ok': False, 'takedown': result.get('id'),
                'reply': f'⚖️ {episode_id} tidak ada di episode_schedule; permintaan dicatat.'}
    if result.get('action') == 'duplicate':
        return {'handled': True, 'ok': True, 'takedown': result.get('id'),
                'reply': f'ℹ️ {episode_id} sudah cancelled: {result.get("cancel_reason") or "-"}'}
    cdn = ('CDN tidak di-purge (belum diimplementasikan)' if not result.get('cdn_purged')
           else 'CDN di-purge')
    return {'handled': True, 'ok': True, 'takedown': result.get('id'),
            'action': result.get('action'),
            'reply': _reply(f'⚖️ {episode_id}: {result.get("action")} ({reason})',
                            f'audit: {result.get("id")}, {cdn}')}


def _biz(now: float | None) -> dict:
    """The office's own counters, read from `GET /biz-metrics`.

    The counters live in `chat.db` and are written by `server/biz-events.js`;
    the sidecar asks the office instead of opening a database that is not its
    own. A closed office is reported as a closed office.
    """
    from hermes_bridge import bridge

    try:
        data = bridge.get_biz_metrics()
    except Exception as err:  # noqa: BLE001 - the chat gets the reason, not a 500
        return {'handled': True, 'ok': False, 'reply': _reply(
            '📊 /biz membaca GET /biz-metrics di kantor, dan kantor tidak menjawab.',
            f'alasan: {str(err)[:160]}',
            'Jalankan kantornya (npm start), lalu coba lagi.')}

    today = data.get('today') if isinstance(data.get('today'), dict) else {}
    sla = data.get('sla') if isinstance(data.get('sla'), dict) else {}

    def n(source: dict, key: str) -> int:
        try:
            return int(source.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    agents = [str(name) for name in (data.get('agents_active') or []) if str(name).strip()]
    return {
        'handled': True, 'ok': True, 'metrics': data, 'today': today, 'sla': sla,
        'reply': _reply(
            f'📊 Hari ini: {n(today, "leads_qualified")} lead, {n(today, "emails_sent")} email, '
            f'{n(today, "tickets_resolved")} tiket selesai, {n(today, "tickets_pending")} terbuka',
            f'🛠 CRM {n(today, "crm_updates")} · refund {n(today, "refunds_processed")} · '
            f'chargeback {n(today, "chargebacks")}',
            f'⏱ SLA: rata-rata {n(sla, "avg_response_min")} mnt, '
            f'{n(sla, "breach_count")} lewat deadline',
            '🧑‍💻 bekerja: ' + (', '.join(agents[:6]) if agents else '-'),
            f'🕒 update: {data.get("last_updated") or "-"}',
        ),
    }


#: Pipeline stages in the order `/leads` reports them (AGENTS.md §4.1)
LEAD_STAGES = ('new', 'contacted', 'qualified', 'meeting', 'won', 'lost')


def _leads(now: float | None) -> dict:
    """`/leads`: pipeline per stage, today's leads, and lead handoffs still waiting.

    Two windows on purpose. The stage counts cover every `lead:*` record, because
    a deal won last week is still won today; the list is only today's leads. A
    single "won 1" under the word "hari ini" would be a misreading the office
    cannot afford, so the reply labels each line.

    Handoffs are filtered to subjects starting `lead:` - the ones the Sales
    pipeline left behind. A pending `Marketing -> Support` handoff for a lead
    means the customer's follow-up is stuck, which is exactly what a pipeline
    view is for.
    """
    from hermes_bridge import handoff
    from hermes_agents import store

    at = _at(now)
    ctx = store.context()
    everything = ctx.find('lead:')
    rows = ctx.recent('lead:', since=_day_start(at))

    pipeline: dict[str, int] = {stage: 0 for stage in LEAD_STAGES}
    for value in everything.values():
        record = value if isinstance(value, dict) else {}
        stage = str(record.get('stage') or record.get('status') or 'new')
        stage = stage if stage in pipeline else 'new'
        pipeline[stage] += 1

    waiting = {key: env for key, env in handoff.pending().items()
               if isinstance(env, dict) and str(env.get('subject') or '').startswith('lead:')}
    routes: dict[str, int] = {}
    for env in waiting.values():
        route = f'{env.get("from")}→{env.get("to")}'
        routes[route] = routes.get(route, 0) + 1

    handoff_line = ''
    if waiting:
        parts = ', '.join(f'{route} {n}' for route, n in sorted(routes.items()))
        handoff_line = f'🔗 Handoff lead tertunda: {len(waiting)} ({parts})'

    if not everything:
        return {'handled': True, 'ok': True, 'leads': [], 'pipeline': pipeline,
                'handoffs': routes, 'waiting': sorted(waiting), 'insufficient':
                'tidak ada key lead:*; agent Sales menulisnya lewat trigger '
                'new_lead/form_submit/deal_stage_change',
                'reply': _reply('📭 Belum ada lead.',
                                'Key lead:* ditulis agent Sales dari trigger new_lead, '
                                'form_submit, dan deal_stage_change.',
                                'Kantor tidak mengarang lead untuk mengisi panel.',
                                handoff_line)}

    filled = ', '.join(f'{stage} {n}' for stage, n in pipeline.items() if n)
    lines = [
        f'🧲 Pipeline: {sum(pipeline.values())} lead — {filled or "-"}',
        f'📅 Hari ini: {len(rows)} lead masuk' if rows else '📅 Hari ini: belum ada lead masuk',
    ]
    for row in rows[:2]:
        value = row.get('value') if isinstance(row.get('value'), dict) else {}
        label = value.get('name') or value.get('email') or row['key'].split(':', 1)[-1]
        stage = value.get('stage') or value.get('status') or '-'
        score = value.get('score')
        grades = f', skor {float(score):.2f}' if isinstance(score, (int, float)) else ''
        lines.append(f'- {str(label)[:60]} ({stage}{grades}) oleh {row.get("owner") or "-"}')
    lines.append(handoff_line)
    if len(rows) > 2:
        lines.append(f'…dan {len(rows) - 2} lead lain hari ini')
    return {'handled': True, 'ok': True, 'leads': [row['key'] for row in rows],
            'pipeline': pipeline, 'handoffs': routes, 'waiting': sorted(waiting),
            'reply': _reply(*lines)}


def _tickets(now: float | None) -> dict:
    """Tickets by status, plus the newest ones still waiting."""
    from hermes_bridge.db import init_db

    init_db()
    counts = {row['status']: int(row['n']) for row in _rows(
        'SELECT status, COUNT(*) AS n FROM tickets GROUP BY status')}
    total = sum(counts.values())
    if not total:
        return {'handled': True, 'ok': True, 'reply': '📭 Belum ada tiket di tickets.'}
    waiting = _rows("SELECT id, subject, priority, sla_deadline FROM tickets "
                    "WHERE status IN ('open', 'pending') ORDER BY received_at DESC LIMIT 3")
    lines = [f'🎫 {total} tiket: ' + ', '.join(f'{name} {n}' for name, n in sorted(counts.items()))]
    for row in waiting:
        lines.append(f'- {row["id"]} [{row["priority"]}] {str(row["subject"])[:60]} '
                     f'(SLA {_when(row["sla_deadline"])})')
    if not waiting:
        lines.append('Tidak ada tiket yang masih terbuka.')
    return {'handled': True, 'ok': True, 'tickets': counts,
            'open': [row['id'] for row in waiting], 'reply': _reply(*lines)}


def _sla(now: float | None) -> dict:
    """Compliance over closed tickets, and the ones past their deadline now."""
    from hermes_agents.support import SupportAgent

    at = _at(now)
    agent = SupportAgent()
    try:
        stats = agent.sla_stats(now=at)
    finally:
        agent.close()
    late = _rows("SELECT id, subject, sla_deadline FROM tickets "
                 "WHERE status IN ('open', 'pending') AND sla_deadline < ? "
                 'ORDER BY sla_deadline LIMIT 3', (at,))
    compliance = stats['compliance']
    lines = [
        '🎯 SLA 7 hari: ' + (f'{compliance * 100:.0f}% dari {stats["resolved"]} tiket selesai'
                             if compliance is not None else 'belum ada tiket selesai'),
        f'⏳ Terbuka: {stats["pending"]}, lewat deadline: {stats["late"]}',
        f'⏱ Rata-rata respons pertama: {stats["avg_response_min"]} mnt '
        f'({stats["samples"]} sampel)',
    ]
    for row in late:
        lines.append(f'- {row["id"]}: {str(row["subject"])[:52]} (sejak {_when(row["sla_deadline"])})')
    return {'handled': True, 'ok': True, 'sla': stats, 'late': [row['id'] for row in late],
            'reply': _reply(*lines)}


def _topselling(now: float | None) -> dict:
    """Say what a per-item ranking would need; never rank by a number that does not exist.

    `payment_events` records an order, not what the order bought, and
    `premium_items` has no sales column. Listing items by price and calling it
    "best selling" would be the one fake report in the office.
    """
    live = int(_rows("SELECT COUNT(*) AS n FROM premium_items WHERE status = 'live'")[0]['n'])
    revoked = int(_rows("SELECT COUNT(*) AS n FROM premium_items WHERE status = 'revoked'")[0]['n'])
    reason = ('payment_events tidak menyimpan item_id dan premium_items tidak punya kolom '
              'penjualan, jadi ranking per item belum punya sumber data')
    return {'handled': True, 'ok': True, 'live': live, 'revoked': revoked,
            'insufficient': reason,
            'reply': _reply(f'📈 {live} item live di toko, {revoked} dicabut (chargeback).',
                            'Ranking terlaris belum ada: ' + reason + '.',
                            'Kantor tidak mengurutkan item berdasarkan harga lalu menyebutnya laris.')}


def _incidents(now: float | None) -> dict:
    """The latest `security_incidents` rows."""
    from hermes_agents import sec_ops

    at = _at(now)
    rows = sec_ops.incidents(24.0, now=at, limit=10)
    if not rows:
        return {'handled': True, 'ok': True, 'incidents': [],
                'reply': '✅ Tidak ada insiden keamanan dalam 24 jam.'}
    lines = [f'🚨 {len(rows)} insiden terakhir (24 jam):']
    for row in rows[: MAX_LINES - 1]:
        lines.append(f'- {_when(row["created_at"])} {row["rule"]}/{row["action"]} '
                     f'{row["target"]} oleh {row["actor"]}')
    return {'handled': True, 'ok': True,
            'incidents': [row['id'] for row in rows], 'reply': _reply(*lines)}


def _unban(args: list[str], now: float | None) -> dict:
    """A person lifts a block: a new `unban` row (SECURITY.md §10)."""
    from hermes_agents import sec_ops

    target = (args[0] if args else '').strip()
    if not target:
        return {'handled': True, 'ok': False, 'reply': _HELP['/unban']}
    was_banned = sec_ops.is_banned(target)
    result = sec_ops.unban(target, now=_at(now), actor='CEO (chat)')
    if not result.get('ok'):
        return {'handled': True, 'ok': False, 'target': target, 'unban': result,
                'reply': f'⚠️ unban {target} gagal: {result.get("reason") or "tidak tercatat"}'}
    return {'handled': True, 'ok': True, 'target': target, 'was_banned': was_banned,
            'unban': result.get('id'),
            'reply': _reply(f'🔓 {target} dibuka' + ('' if was_banned else ' (memang tidak diblokir)'),
                            f'audit: {result.get("id")}')}


def _schedule(now: float | None) -> dict:
    """The embargo queue: what is scheduled and when it publishes."""
    from hermes_bridge.db import init_db

    at = _at(now)
    init_db()
    counts = {row['status']: int(row['n']) for row in _rows(
        'SELECT status, COUNT(*) AS n FROM episode_schedule GROUP BY status')}
    if not counts:
        return {'handled': True, 'ok': True, 'reply': '🗓 episode_schedule kosong.'}
    upcoming = _rows("SELECT episode_id, anime_title, episode_number, embargo_until "
                     "FROM episode_schedule WHERE status = 'scheduled' "
                     'ORDER BY embargo_until LIMIT 3')
    lines = ['🗓 ' + ', '.join(f'{name} {n}' for name, n in sorted(counts.items()))]
    for row in upcoming:
        lines.append(f'- {row["episode_id"]} {str(row["anime_title"])[:40]} E{row["episode_number"]} '
                     f'— {_left(row["embargo_until"], at)}')
    if not upcoming:
        lines.append('Tidak ada episode yang menunggu embargo.')
    return {'handled': True, 'ok': True, 'schedule': counts,
            'upcoming': [row['episode_id'] for row in upcoming], 'reply': _reply(*lines)}


def _embargo(args: list[str], now: float | None) -> dict:
    """One schedule's detail, or the next few when no id is given."""
    at = _at(now)
    episode_id = (args[0] if args else '').strip()
    if not episode_id:
        return _schedule(now)
    row = _rows('SELECT * FROM episode_schedule WHERE episode_id = ?', (episode_id,))
    if not row:
        return {'handled': True, 'ok': False,
                'reply': f'❓ {episode_id} tidak ada di episode_schedule.'}
    item = row[0]
    published = _when(item.get('published_at')) if item.get('published_at') else 'belum'
    regions = item.get('regions') or '["*"]'
    return {'handled': True, 'ok': True, 'episode': item,
            'reply': _reply(
                f'⏳ {episode_id} {str(item["anime_title"])[:40]} E{item["episode_number"]}: '
                f'{item["status"]}',
                f'embargo {_when(item["embargo_until"])} ({_left(item["embargo_until"], at)})',
                f'regions: {regions} · published: {published}',
                f'batal: {item.get("cancel_reason") or "-"}',
            )}


def _translations(now: float | None) -> dict:
    """Subtitle tracks by status, and the episodes still needing a person."""
    counts = {row['status']: int(row['n']) for row in _rows(
        'SELECT status, COUNT(*) AS n FROM subtitle_tracks GROUP BY status')}
    if not counts:
        return {'handled': True, 'ok': True, 'reply': '📭 Belum ada subtitle_tracks.'}
    needs = _rows("SELECT episode_id, COUNT(*) AS n FROM subtitle_tracks "
                  "WHERE status = 'needs_review' GROUP BY episode_id ORDER BY episode_id LIMIT 3")
    lines = ['🌐 ' + ', '.join(f'{name} {n}' for name, n in sorted(counts.items()))]
    for row in needs:
        lines.append(f'- {row["episode_id"]}: {int(row["n"])} track perlu review')
    if not needs:
        lines.append('Tidak ada track yang menunggu review.')
    lines.append('Setujui dengan /approve-sub <episode_id>.')
    return {'handled': True, 'ok': True, 'translations': counts,
            'needs_review': [row['episode_id'] for row in needs], 'reply': _reply(*lines)}


def _approve_sub(args: list[str], now: float | None) -> dict:
    """`needs_review` -> `approved` for one episode; the DB is the only writer."""
    from hermes_agents import store

    at = _at(now)
    episode_id = (args[0] if args else '').strip()
    if not episode_id:
        needs = _rows("SELECT episode_id, COUNT(*) AS n FROM subtitle_tracks "
                      "WHERE status = 'needs_review' GROUP BY episode_id ORDER BY episode_id LIMIT 5")
        if not needs:
            return {'handled': True, 'ok': True,
                    'reply': '✅ Tidak ada subtitle yang menunggu review.'}
        lines = ['🌐 Pilih episode untuk /approve-sub:']
        lines += [f'- {row["episode_id"]} ({int(row["n"])} track)' for row in needs]
        return {'handled': True, 'ok': True, 'needs_review': [row['episode_id'] for row in needs],
                'reply': _reply(*lines)}

    con = store.connect()
    try:
        total = int(con.execute('SELECT COUNT(*) FROM subtitle_tracks WHERE episode_id = ?',
                                (episode_id,)).fetchone()[0])
        if not total:
            return {'handled': True, 'ok': False,
                    'reply': f'❓ {episode_id} tidak punya subtitle_tracks.'}
        cur = con.execute("UPDATE subtitle_tracks SET status = 'approved', updated_at = ? "
                          "WHERE episode_id = ? AND status = 'needs_review'", (at, episode_id))
        con.commit()
        approved = cur.rowcount
    finally:
        con.close()
    if not approved:
        return {'handled': True, 'ok': True, 'approved': 0,
                'reply': f'ℹ️ {episode_id}: tidak ada track needs_review.'}
    return {'handled': True, 'ok': True, 'episode': episode_id, 'approved': approved,
            'reply': f'✅ {episode_id}: {approved} subtitle di-approve.'}


def _reports(now: float | None) -> dict:
    """Today's user reports, by status and by category."""
    at = _at(now)
    since = _day_start(at)
    rows = _rows('SELECT status, category, COUNT(*) AS n FROM user_reports '
                 'WHERE created_at >= ? GROUP BY status, category', (since,))
    if not rows:
        return {'handled': True, 'ok': True, 'reply': '📭 Belum ada laporan user hari ini.'}
    total = sum(int(row['n']) for row in rows)
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for row in rows:
        by_status[str(row['status'])] = by_status.get(str(row['status']), 0) + int(row['n'])
        by_category[str(row['category'])] = by_category.get(str(row['category']), 0) + int(row['n'])
    newest = _rows('SELECT id, category, description, status FROM user_reports '
                   'WHERE created_at >= ? ORDER BY created_at DESC LIMIT 2', (since,))
    lines = [f'📨 {total} laporan hari ini: '
             + ', '.join(f'{name} {n}' for name, n in sorted(by_status.items())),
             'Kategori: ' + ', '.join(f'{name} {n}' for name, n in sorted(by_category.items()))]
    for row in newest:
        lines.append(f'- {row["id"]} [{row["category"]}/{row["status"]}] '
                     f'{str(row["description"] or "")[:56]}')
    return {'handled': True, 'ok': True, 'reports': by_status, 'categories': by_category,
            'reply': _reply(*lines)}


def _report_stats(now: float | None) -> dict:
    """The last 7 days of user reports, per day and per category."""
    at = _at(now)
    since = at - 7 * 86400.0
    per_day = _rows("SELECT date(created_at, 'unixepoch', 'localtime') AS day, "
                    'COUNT(*) AS n FROM user_reports WHERE created_at >= ? '
                    'GROUP BY day ORDER BY day', (since,))
    if not per_day:
        return {'handled': True, 'ok': True,
                'reply': '📭 Tidak ada laporan user dalam 7 hari terakhir.'}
    per_category = _rows('SELECT category, COUNT(*) AS n FROM user_reports '
                         'WHERE created_at >= ? GROUP BY category ORDER BY n DESC', (since,))
    lines = ['📈 Laporan 7 hari: '
             + ', '.join(f'{row["day"]} {int(row["n"])}' for row in per_day[: MAX_LINES - 2])]
    lines.append('Kategori: ' + ', '.join(
        f'{row["category"]} {int(row["n"])}' for row in per_category[:4]))
    return {'handled': True, 'ok': True,
            'days': {row['day']: int(row['n']) for row in per_day},
            'categories': {row['category']: int(row['n']) for row in per_category},
            'reply': _reply(*lines)}


def handle_command(text: object, now: float | None = None) -> dict[str, Any]:
    """Answer one chat line, or say `handled: False` so it stays a chat message.

    Returns `{handled, ok, reply, ...}`; `approval` names the item whose card the
    caller should queue (`premium.request_approval`), and is absent when there is
    nothing to ask.
    """
    line = str(text or '').strip()
    if not line.startswith('/'):
        return {'handled': False}
    parts = line.split()
    command = parts[0].lower()
    args = parts[1:]
    at = time.time() if now is None else float(now)

    if command not in COMMANDS:
        return {'handled': False}
    log.info('command: %s %s', command, ' '.join(args)[:80])
    try:
        if command == '/design':
            return _design(args, at)
        if command == '/pending-items':
            return _pending(at)
        if command == '/approve':
            return _approve(args, at)
        if command == '/revenue':
            return _revenue(at)
        if command == '/payments':
            return _payments(at)
        if command == '/subscriptions':
            return _subscriptions(at)
        if command == '/refunds':
            return _refunds(at)
        if command == '/chargeback':
            return _chargeback(at)
        if command == '/security':
            return _security(at)
        if command == '/takedown':
            return _takedown(args, at)
        # W10: the rest of API-REFERENCE.md §6
        if command == '/biz':
            return _biz(at)
        if command == '/leads':
            return _leads(at)
        if command == '/tickets':
            return _tickets(at)
        if command == '/sla':
            return _sla(at)
        if command == '/topselling':
            return _topselling(at)
        if command == '/incidents':
            return _incidents(at)
        if command == '/unban':
            return _unban(args, at)
        if command == '/schedule':
            return _schedule(at)
        if command == '/embargo':
            return _embargo(args, at)
        if command == '/translations':
            return _translations(at)
        if command == '/approve-sub':
            return _approve_sub(args, at)
        if command == '/reports':
            return _reports(at)
        return _report_stats(at)
    except Exception as err:  # noqa: BLE001 - the chat must get an answer, not a 500
        log.exception('command %s gagal: %s', command, err)
        return {'handled': True, 'ok': False, 'reply': f'❌ {command} gagal: {err}'}
