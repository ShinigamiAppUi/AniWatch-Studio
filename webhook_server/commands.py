"""commands.py - the business slash commands the chat panel sends (W7).

The chat panel is the office's own surface (`POST /chat` -> `server/biz-events.js`),
and the work lives in Python, so a business command is relayed here and answered
with one short chat line (API-REFERENCE.md §6: one message, at most six lines).

The three commands W7 introduces:

    /design [kind] [tema]   create the item, design/QA/price/preview it
    /pending-items          what is waiting for approval
    /approve [id]           the same decision the card's Approve button makes

`/approve` calls `premium.decide`, which is the only writer out of
`pending_approval`; the card's answer goes through the same function from
`premium.request_approval`. That is what makes both doors end in the same status
(PLAN.md W7), and it is checked in `hermes_agents.selfcheck`.

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
COMMANDS = ('/design', '/pending-items', '/approve')

#: Chat panel, not a dashboard: the office's own rule for business replies
MAX_LINES = 6
MAX_LINE = 220

_HELP = {
    '/design': 'tulis /design <border|nameplate|profile_effect> <tema>',
    '/approve': 'tulis /approve <id>',
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
        return _approve(args, at)
    except Exception as err:  # noqa: BLE001 - the chat must get an answer, not a 500
        log.exception('command %s gagal: %s', command, err)
        return {'handled': True, 'ok': False, 'reply': f'❌ {command} gagal: {err}'}
