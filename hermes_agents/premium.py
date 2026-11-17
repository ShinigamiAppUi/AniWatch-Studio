"""premium.py - the premium item pipeline (W7): draft to live, with one gate.

Order (AGENTS.md §4.5):

    DesignAgent -> QAAgent -> PricingAgent -> PreviewAgent -> approval
        Approve -> Publisher (live)   Revisi -> DesignAgent again   Reject -> stop

Two decisions worth knowing:

- **The designs are generated here, deterministically.** AGENTS.md §4.5 used to
  say DesignAgent calls an image model and stops without `IMAGE_GEN_API_KEY`.
  That would make the whole pipeline unbuildable on a fresh machine and untestable
  in CI, so variations are SVGs composed from the theme's palette, and the result
  records `design_source: "template"`. An image-model call is **not** faked: the
  context says `image_gen: "belum diimplementasikan"` whenever the key is set, so
  nobody believes a model drew the file that is on disk.
- **Approval has one writer.** `decide()` is the only function that moves an item
  out of `pending_approval`, whether the answer came from the office card
  (`request_approval` -> `char.ask`) or from `/approve`. Approve publishes inside
  the same call, so both doors end in the same status (PLAN.md W7).

A timeout changes nothing: the item stays `pending_approval`, so a person can
still answer it with `/approve` after the card has gone. That is the same rule
`sla_check` follows (a timeout is not a decision).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from . import config, store

log = logging.getLogger(__name__)

#: The three kinds of item the store sells (DB-SCHEMA.md §8)
KINDS = ('border', 'nameplate', 'profile_effect')

#: Front licence for the keyboard: the button labels are what comes back
APPROVAL_OPTIONS = ('Approve', 'Revisi', 'Reject')

#: A money decision does not inherit `wait_for_approval`'s 300 s default
APPROVAL_TIMEOUT_S = 86400.0

#: DesignAgent gets two tries and one revision round before the item is rejected
MAX_ATTEMPTS = 2
MAX_ROUNDS = 3

#: Palette per theme. An unknown theme is a QA problem, not a crash: the item
#: then fails its checks and is rejected with the reason on the row.
THEMES: dict[str, tuple[str, ...]] = {
    'neon': ('#ff2e97', '#00e5ff', '#7c4dff', '#0b1020'),
    'sakura': ('#ffb7c5', '#ff7a9c', '#6d3b4f', '#fff5f7'),
    'ocean': ('#0ea5e9', '#22d3ee', '#1e3a8a', '#04121f'),
}

DEFAULT_THEME = 'neon'

#: Canvas per kind: (width, height). QA checks the resolution against this
CANVAS = {'border': (512, 512), 'nameplate': (640, 160), 'profile_effect': (512, 512)}

#: Complexity -> tier -> price. Deterministic, so the same design is always priced
#: the same (AGENTS.md §4.5: "angka tier dari analyze_complexity, bukan perkiraan")
TIERS = ((8, 'basic', 15_000), (16, 'premium', 35_000), (10**6, 'deluxe', 75_000))


def premium_root() -> Path:
    root = config.media_root() / 'premium'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Rows (DB-SCHEMA.md §8)
# ---------------------------------------------------------------------------

def _con(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return con if con is not None else store.connect()


def new_id() -> str:
    """`pm-1a2b3c4d5e`."""
    return f'pm-{uuid.uuid4().hex[:10]}'


def create_item(kind: str = 'border', theme: str = DEFAULT_THEME, *,
                con: sqlite3.Connection | None = None, now: float | None = None,
                item_id: str | None = None) -> dict:
    """Insert one `draft` row and return it."""
    at = time.time() if now is None else float(now)
    clean_kind = (kind or 'border').strip().lower()
    if clean_kind not in KINDS:
        raise ValueError(f'kind tidak dikenal: {kind!r} (yang sah: {", ".join(KINDS)})')
    item = item_id or new_id()
    connection = _con(con)
    connection.execute(
        'INSERT INTO premium_items (id, kind, theme, status, created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (item, clean_kind, (theme or DEFAULT_THEME).strip().lower(), 'draft', at, at),
    )
    connection.commit()
    log.info('premium: %s dibuat (%s/%s)', item, clean_kind, theme)
    return get_item(item, con=connection) or {}


def get_item(item_id: str, *, con: sqlite3.Connection | None = None) -> dict | None:
    row = _con(con).execute('SELECT * FROM premium_items WHERE id = ?', (item_id,)).fetchone()
    return dict(row) if row else None


def list_items(status: str | None = None, *, con: sqlite3.Connection | None = None,
               limit: int = 50) -> list[dict]:
    connection = _con(con)
    if status:
        rows = connection.execute(
            'SELECT * FROM premium_items WHERE status = ? ORDER BY created_at DESC LIMIT ?',
            (status, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            'SELECT * FROM premium_items ORDER BY created_at DESC LIMIT ?', (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def _set_status(item_id: str, patch: dict, *, con: sqlite3.Connection | None = None,
                now: float | None = None) -> dict:
    at = time.time() if now is None else float(now)
    data = {**patch, 'updated_at': at}
    assignments = ', '.join(f'{name} = ?' for name in data)
    # One connection for the write and its commit: two `_con()` calls would be
    # two connections, and the UPDATE would be rolled back when the first closes
    connection = _con(con)
    connection.execute(
        f'UPDATE premium_items SET {assignments} WHERE id = ?', (*data.values(), item_id),
    )
    connection.commit()
    return get_item(item_id, con=connection) or {}


def item_key(item_id: str) -> str:
    """SharedContext key for one item's working state."""
    return f'premium:{item_id}'


def _remember(item_id: str, patch: dict) -> None:
    try:
        store.context().update(item_key(item_id), patch, 'PremiumPipeline')
    except Exception as err:  # noqa: BLE001 - the row is the durable record
        log.warning('premium: context %s tidak tersimpan: %s', item_id, err)


def _recall(item_id: str) -> dict:
    value = store.context().get(item_key(item_id))
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# DesignAgent - deterministic SVG variations
# ---------------------------------------------------------------------------

def _svg(kind: str, theme: str, palette: tuple[str, ...], variation: int) -> tuple[str, int]:
    """One design: the SVG text and how many drawable elements it has."""
    width, height = CANVAS[kind]
    main, accent, third, ink = (palette + ('#ffffff',) * 4)[:4]
    stroke = 8 + 4 * (variation % 3)
    elements: list[str] = []

    if kind == 'border':
        elements.append(f'<rect x="12" y="12" width="{width - 24}" height="{height - 24}" '
                        f'rx="28" fill="none" stroke="{main}" stroke-width="{stroke}"/>')
        elements.append(f'<rect x="40" y="40" width="{width - 80}" height="{height - 80}" '
                        f'rx="20" fill="none" stroke="{accent}" stroke-width="3" '
                        'stroke-dasharray="14 10"/>')
        for corner_x, corner_y in ((72, 72), (width - 72, 72), (72, height - 72),
                                   (width - 72, height - 72)):
            elements.append(f'<circle cx="{corner_x}" cy="{corner_y}" r="{10 + variation}" '
                            f'fill="{third}" opacity="0.85"/>')
        if variation % 2 == 0:
            elements.append(f'<path d="M {width // 2} 24 L {width - 24} {height // 2} '
                            f'L {width // 2} {height - 24} L 24 {height // 2} Z" '
                            f'fill="none" stroke="{accent}" stroke-width="2" opacity="0.5"/>')
    elif kind == 'nameplate':
        elements.append(f'<rect x="4" y="4" width="{width - 8}" height="{height - 8}" rx="24" '
                        f'fill="{ink}" stroke="{main}" stroke-width="{stroke // 2}"/>')
        elements.append(f'<rect x="22" y="22" width="{width - 44}" height="{height - 44}" rx="16" '
                        f'fill="none" stroke="{accent}" stroke-width="2"/>')
        elements.append(f'<text x="{width // 2}" y="{height // 2 + 14}" text-anchor="middle" '
                        f'font-family="sans-serif" font-size="44" font-weight="700" '
                        f'fill="{third}">AniWatch</text>')
        if variation % 2 == 1:
            elements.append(f'<circle cx="46" cy="{height // 2}" r="12" fill="{main}"/>')
            elements.append(f'<circle cx="{width - 46}" cy="{height // 2}" r="12" fill="{main}"/>')
    else:  # profile_effect
        for ring in range(2 + variation % 2):
            elements.append(f'<circle cx="{width // 2}" cy="{height // 2}" r="{140 + ring * 60}" '
                            f'fill="none" stroke="{main}" stroke-width="{6 - ring}" '
                            f'opacity="{0.7 - ring * 0.2:.2f}"/>')
        elements.append(f'<polygon points="{width // 2},{height // 2 - 180} '
                        f'{width // 2 + 60},{height // 2} {width // 2},{height // 2 + 180} '
                        f'{width // 2 - 60},{height // 2}" fill="{accent}" opacity="0.35"/>')
        elements.append(f'<circle cx="{width // 2}" cy="{height // 2}" r="28" fill="{third}"/>')

    text = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">' + ''.join(elements) + '</svg>\n')
    return text, len(elements)


def design(item_id: str, variation: int = 0, char: Any = None) -> dict:
    """Write all the variations of one item; the best QA result picks one."""
    item = get_item(item_id)
    if item is None:
        return {'error': f'item {item_id} tidak ada'}
    palette = THEMES.get(item['theme'], ())
    folder = premium_root() / item_id
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    made: list[dict] = []
    for index in range(3):
        text, elements = _svg(item['kind'], item['theme'], palette, variation + index)
        path = folder / f'design-{variation + index + 1}.svg'
        path.write_text(text, encoding='utf-8')
        made.append({'path': str(path), 'elements': elements, 'text': text,
                     'variation': variation + index})
    if char:
        char.update(f'{len(made)} variasi {item["kind"]}/{item["theme"]}', tool='generate_design')
    _remember(item_id, {
        'designs': [{'path': d['path'], 'elements': d['elements']} for d in made],
        'design_source': 'template',
        'image_gen': ('belum diimplementasikan (IMAGE_GEN_API_KEY diisi, provider image-gen '
                      'tidak dipanggil fork ini)' if os.environ.get('IMAGE_GEN_API_KEY') else None),
        'variation': variation,
    })
    return {'designs': made, 'theme': item['theme'], 'kind': item['kind']}


# ---------------------------------------------------------------------------
# QAAgent - three real checks on the generated files
# ---------------------------------------------------------------------------

def qa(designs: list[dict], theme: str) -> dict:
    """Resolution, palette consistency and transparency, scored 0..1.

    The checks read the file, not the intent: a design is what is on disk. An
    unknown theme has no palette to be consistent with, which is exactly the
    failure the item should surface.
    """
    palette = THEMES.get(theme, ())
    scored: list[dict] = []
    for candidate in designs:
        text = candidate['text']
        width, height = CANVAS.get(candidate.get('kind') or 'border', (0, 0))
        problems: list[str] = []

        # resolution: the canvas the design declares must be at least the kind's
        found = re.search(r'width="(\d+)" height="(\d+)"', text)
        if not found:
            problems.append('ukuran kanvas tidak terbaca')
        else:
            w, h = int(found.group(1)), int(found.group(2))
            if w < width or h < height:
                problems.append(f'resolusi {w}x{h} < {width}x{height}')

        colours = {c.upper() for c in re.findall(r'#[0-9a-fA-F]{6}', text)}
        unknown = sorted(c for c in colours if c not in {p.upper() for p in palette})
        if not palette:
            problems.append(f'tema {theme!r} tidak dikenal (tidak ada palet)')
        elif unknown:
            problems.append('warna di luar palet: ' + ', '.join(unknown))

        if '<rect x="0"' in text or 'width="100%" height="100%"' in text:
            problems.append('latar penuh menutupi transparansi')

        score = (3 - len(problems)) / 3
        scored.append({**candidate, 'score': round(max(0.0, score), 3), 'problems': problems})

    passed = [row for row in scored if not row['problems']]
    best = max(passed or scored, key=lambda row: (row['score'], -row['elements']), default=None)
    return {
        'passed': bool(passed),
        'score': (best or {}).get('score', 0.0),
        'problems': (best or {}).get('problems', ['tidak ada desain']),
        'chosen': best,
        'checked': len(scored),
    }


# ---------------------------------------------------------------------------
# PricingAgent - tier from complexity
# ---------------------------------------------------------------------------

def price(elements: int) -> dict:
    """`analyze_complexity` -> `assign_tier`: a table, not a guess."""
    for ceiling, tier, price_idr in TIERS:
        if elements <= ceiling:
            return {'tier': tier, 'price_idr': price_idr, 'elements': int(elements)}
    _, tier, price_idr = TIERS[-1]
    return {'tier': tier, 'price_idr': price_idr, 'elements': int(elements)}


# ---------------------------------------------------------------------------
# PreviewAgent - light and dark mockups
# ---------------------------------------------------------------------------

def preview(item_id: str, design_path: str, kind: str) -> dict:
    """Write `preview-light.svg` and `preview-dark.svg` around the design."""
    source = Path(design_path).read_text(encoding='utf-8')
    width, height = CANVAS.get(kind, (512, 512))
    inner = source[source.index('>') + 1:source.rindex('</svg>')]
    folder = premium_root() / item_id
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    written: dict[str, str] = {}
    for mode, background in (('light', '#ffffff'), ('dark', '#0b1020')):
        body = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">'
                f'<rect x="0" y="0" width="{width}" height="{height}" fill="{background}"/>'
                f'{inner}</svg>\n')
        path = folder / f'preview-{mode}.svg'
        path.write_text(body, encoding='utf-8')
        written[mode] = str(path)
    return written


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def prepare(item_id: str, char: Any = None, now: float | None = None) -> dict:
    """Design -> QA -> price -> preview, ending at `pending_approval`.

    Each step is its own character, so the office shows the four agents working
    in order. A QA failure sends the item back to DesignAgent once; a second
    failure rejects it with the problems on the row.
    """
    from .base import Agent

    item = get_item(item_id)
    if item is None:
        return {'error': f'item {item_id} tidak ada', 'id': item_id}

    attempt = int(_recall(item_id).get('attempt') or 0)
    result: dict[str, Any] = {}
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        _remember(item_id, {'attempt': attempt})

        with Agent('DesignAgent', f'Desain {item["kind"]}/{item["theme"]}', name='Design Agent') as designer:
            designed = design(item_id, variation=(attempt - 1) * 3, char=designer)

        with Agent('QAAgent', f'QA {item_id}', name='QA Agent') as checker:
            verdict = qa([{**d, 'kind': item['kind']} for d in designed['designs']], item['theme'])
            checker.update(f'qa_score {verdict["score"]} ({verdict["checked"]} variasi)',
                           tool='check_resolution')
            if not verdict['passed']:
                checker.update('gagal: ' + '; '.join(verdict['problems'])[:150], tool='check_consistency')

        if not verdict['passed']:
            log.warning('premium: %s QA gagal (percobaan %d): %s', item_id, attempt,
                        verdict['problems'])
            if attempt >= MAX_ATTEMPTS:
                rejected = _set_status(item_id, {'status': 'rejected', 'qa_score': verdict['score']},
                                       now=now)
                _remember(item_id, {'qa_problems': verdict['problems'], 'rejected_at': now})
                return {**rejected, 'problems': verdict['problems']}
            continue

        chosen = verdict['chosen']
        priced = price(chosen['elements'])
        with Agent('PricingAgent', f'Harga {item_id}', name='Pricing Agent') as pricer:
            pricer.update(f'{priced["tier"]}: Rp{priced["price_idr"]:,}'.replace(',', '.'),
                          tool='assign_tier')

        with Agent('PreviewAgent', f'Mockup {item_id}', name='Preview Agent') as previewer:
            previewer.update('render_mockup light + dark', tool='render_mockup')
            shots = preview(item_id, chosen['path'], item['kind'])

        result = _set_status(item_id, {
            'status': 'pending_approval',
            'design_path': chosen['path'],
            'preview_light': shots['light'],
            'preview_dark': shots['dark'],
            'qa_score': verdict['score'],
            'tier': priced['tier'],
            'price_idr': priced['price_idr'],
        }, now=now)
        _remember(item_id, {'qa_problems': [], 'priced': priced})
        return result
    return result


def publish(item_id: str, now: float | None = None) -> dict:
    """Publisher: `insert_db` + `activate_item`; only from `approved`.

    Idempotent on purpose: the card thread and `/approve` may both arrive, and
    the second one must be a no-op rather than a second manifest.
    """
    item = get_item(item_id)
    if item is None:
        return {'error': f'item {item_id} tidak ada'}
    if item['status'] == 'live':
        return {**item, 'published': False, 'reason': 'sudah live'}
    if item['status'] != 'approved':
        return {**item, 'published': False, 'reason': f'status {item["status"]} bukan approved'}

    at = time.time() if now is None else float(now)
    manifest = {
        'id': item_id,
        'kind': item['kind'],
        'theme': item['theme'],
        'tier': item['tier'],
        'price_idr': item['price_idr'],
        'qa_score': item['qa_score'],
        'design': item['design_path'],
        'preview_light': item['preview_light'],
        'preview_dark': item['preview_dark'],
        'live_at': at,
        # No documented upload endpoint exists, so nothing is uploaded and the
        # manifest says so instead of pointing at a CDN path that is not there
        'cdn': {'uploaded': False,
                'reason': 'upload CDN belum diimplementasikan (CDN_API_KEY/CDN_BASE_URL tidak dipakai untuk upload)'},
    }
    path = config.media_root() / 'published' / 'premium' / f'{item_id}.json'
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    live = _set_status(item_id, {'status': 'live'}, now=at)
    _remember(item_id, {'live_at': at, 'manifest': str(path)})
    log.info('premium: %s live (%s Rp%s) -> %s', item_id, item['tier'], item['price_idr'], path)
    return {**live, 'published': True, 'manifest': str(path)}


def revoke_item(item_id: str, reason: str, *, now: float | None = None,
                con: sqlite3.Connection | None = None) -> dict:
    """Chargeback (W9): take a live item out of the store, keeping its row.

    Only `live` can be revoked - an item that never shipped has nothing to
    revoke - and the reason is stored in context so the row stays explainable.
    """
    at = time.time() if now is None else float(now)
    item = get_item(item_id, con=con)
    if item is None:
        return {'revoked': False, 'error': f'item {item_id} tidak ada'}
    if item['status'] != 'live':
        return {'revoked': False, 'id': item_id, 'status': item['status'],
                'reason': f'status {item["status"]} bukan live'}
    row = _set_status(item_id, {'status': 'revoked'}, con=con, now=at)
    _remember(item_id, {'revoked_at': at, 'revoke_reason': str(reason)[:200]})
    log.warning('premium: %s dicabut (%s)', item_id, reason)
    return {**row, 'revoked': True, 'reason': str(reason)[:200]}


def decide(item_id: str, decision: str, *, now: float | None = None,
           release_card: bool = True) -> dict:
    """The one writer out of `pending_approval`.

    Approve -> `approved` then `publish` (live), Revisi -> back to `draft` for
    another DesignAgent round, Reject -> `rejected`. `timeout`/unknown labels
    change nothing, so the item stays billable by `/approve`.
    """
    item = get_item(item_id)
    if item is None:
        return {'error': f'item {item_id} tidak ada', 'id': item_id}

    label = str(decision or '').strip()
    if release_card:
        agent = _recall(item_id).get('awaiting_agent')
        if agent:
            try:
                from webhook_server.approval import store as approval_store

                approval_store().set_decision(str(agent), label)
            except Exception as err:  # noqa: BLE001 - no waiting card is fine
                log.debug('premium: card %s tidak bisa dilepas: %s', agent, err)

    if label == 'Approve':
        approved = _set_status(item_id, {'status': 'approved'}, now=now)
        _remember(item_id, {'decision': label, 'decided_at': now})
        return publish(item_id, now=now)
    if label == 'Revisi':
        draft = _set_status(item_id, {'status': 'draft'}, now=now)
        _remember(item_id, {'decision': label, 'revision_requested': True,
                            'revision_at': now, 'awaiting_agent': None})
        return {**draft, 'decision': label}
    if label == 'Reject':
        rejected = _set_status(item_id, {'status': 'rejected'}, now=now)
        _remember(item_id, {'decision': label, 'rejected_at': now, 'awaiting_agent': None})
        return {**rejected, 'decision': label}
    return {**item, 'decision': None, 'reason': f'keputusan {label or "kosong"} tidak mengubah status'}


def request_approval(item_id: str, char: Any = None, timeout: float = APPROVAL_TIMEOUT_S,
                     now: float | None = None) -> dict:
    """Raise the card (PreviewAgent) and carry out whatever the person chose.

    Runs in a worker thread, never inside a request: `char.ask` blocks until the
    button is pressed. A revision round re-prepares the item and raises a second
    card, bounded by MAX_ROUNDS.
    """
    from .base import Agent

    item = get_item(item_id)
    if item is None:
        return {'error': f'item {item_id} tidak ada'}
    if item['status'] == 'draft':
        item = prepare(item_id, now=now)

    for round_number in range(1, MAX_ROUNDS + 1):
        if item.get('status') != 'pending_approval':
            return {**item, 'approval': None}
        message = (f'Item premium {item_id} ({item["kind"]}/{item["theme"]}, '
                   f'{item.get("tier")} Rp{item.get("price_idr")}) siap. Publish?')

        def _run(character) -> str:
            _remember(item_id, {'awaiting_agent': character.id})
            character.update('minta approval publish', tool='bundle_preview')
            return character.ask(message, list(APPROVAL_OPTIONS), timeout=timeout)

        decision = _run(char) if char is not None else None
        if char is None:
            with Agent('PreviewAgent', f'Approval {item_id}', name='Preview Agent') as card:
                decision = _run(card)

        item = decide(item_id, decision, now=now, release_card=False)
        log.info('premium: %s ronde %d -> %s (%s)', item_id, round_number, decision,
                 item.get('status'))
        if item.get('status') == 'draft' and round_number < MAX_ROUNDS:
            item = prepare(item_id, now=now)
            continue
        return {**item, 'approval': decision, 'rounds': round_number}

    return {**item, 'approval': 'timeout', 'rounds': MAX_ROUNDS}


# ---------------------------------------------------------------------------
# Entry point used by `/design`
# ---------------------------------------------------------------------------

def start(kind: str = 'border', theme: str = DEFAULT_THEME, *, now: float | None = None,
          con: sqlite3.Connection | None = None) -> dict:
    """Create the item and prepare it; the approval card is the caller's job."""
    item = create_item(kind, theme, con=con, now=now)
    if not item:
        return {'error': 'item gagal dibuat'}
    prepared = prepare(item['id'], now=now)
    return {**prepared, 'id': item['id']}
