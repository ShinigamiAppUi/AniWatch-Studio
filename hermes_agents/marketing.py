"""marketing.py - MarketingAgent: the Monday 09.00 report, from real numbers.

Tools from AGENTS.md §4.1: `fetch_analytics`, `generate_report` (and the post
tools it shares with `channels.py`). The trigger is `weekly_analytics`, which
`jobs.run_marketing_report()` fires from the `weekly_report` job.

The report is a markdown file under `media/published/reports/`, written every
week whether or not anyone reads it, plus a one-line summary to Discord when
`DISCORD_WEBHOOK_URL` is set. Every section states where its numbers came from
(`growth_data.py` labels the source): a week with no AniWatch export says so in
the report instead of showing a watch-time chart nobody measured.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import channels, config, growth_data

log = logging.getLogger(__name__)

REPORT_DIR = 'reports'


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
