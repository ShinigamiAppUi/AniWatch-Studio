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
            '/subscriptions', '/refunds', '/chargeback', '/security', '/takedown')

#: Chat panel, not a dashboard: the office's own rule for business replies
MAX_LINES = 6
MAX_LINE = 220

_HELP = {
    '/design': 'tulis /design <border|nameplate|profile_effect> <tema>',
    '/approve': 'tulis /approve <id>',
    '/takedown': 'tulis /takedown <episode_id> [alasan]',
}


def _line(text: object) -> str:
    return ' '.join(str(text or '').split())[:MAX_LINE]


def _reply(*lines: str) -> str:
    kept = [line for line in lines if line][:MAX_LINES]
    return '\n'.join(kept)


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
        return _takedown(args, at)
    except Exception as err:  # noqa: BLE001 - the chat must get an answer, not a 500
        log.exception('command %s gagal: %s', command, err)
        return {'handled': True, 'ok': False, 'reply': f'❌ {command} gagal: {err}'}
