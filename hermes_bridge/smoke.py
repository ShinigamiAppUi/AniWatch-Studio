"""smoke.py - prove a role appears at its desk, without running a real agent.

    python -m hermes_bridge.smoke --list           # the 30 roles, from src/types.ts
    python -m hermes_bridge.smoke --role Scraper   # one character appears and leaves
    python -m hermes_bridge.smoke --all            # all 30, one after another
    python -m hermes_bridge.smoke --approval Sales # raises a hand, waits for a card

The roles come from `src/types.ts` itself (the canonical table) rather than a
copy that would drift. The token comes from `OFFICE_TOKEN`, or from the office's
own `auth-token` file when the variable is not set - a dev convenience; a real
agent sets the variable (ENV-VARS.md §1).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES_TS = ROOT / 'src' / 'types.ts'
ROLE_RE = re.compile(r"^\s{2}([A-Za-z0-9_]+):\s+\{\s*color:\s*'", re.MULTILINE)


def roles() -> list[str]:
    """Every business role, in the order src/types.ts declares them."""
    try:
        text = TYPES_TS.read_text(encoding='utf-8')
    except OSError as err:
        raise SystemExit(f'cannot read {TYPES_TS}: {err}')
    block = text.split('GENERIC_BIZ_CONFIGS', 1)
    if len(block) < 2:
        raise SystemExit(f'{TYPES_TS} has no GENERIC_BIZ_CONFIGS')
    body = block[1].split('export type BusinessRole', 1)[0]
    found = ROLE_RE.findall(body)
    if not found:
        raise SystemExit(f'no roles found in {TYPES_TS}')
    return found


def resolve_token() -> str:
    """`OFFICE_TOKEN`, else the office's auth-token file; exits when neither exists."""
    token = os.environ.get('OFFICE_TOKEN', '').strip()
    if token:
        return token
    home = Path(os.environ.get('AGENT_OFFICE_HOME') or Path.home() / '.agent-office')
    path = home / 'auth-token'
    if path.exists():
        token = path.read_text(encoding='utf-8').strip()
        if token:
            print(f'token: read from {path} (set OFFICE_TOKEN for a real agent)')
            return token
    raise SystemExit(
        'no office token: set OFFICE_TOKEN, or start the office once so it writes\n'
        f'  {path}'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Put business characters in the office')
    parser.add_argument('--list', action='store_true', help='print the roles and exit')
    parser.add_argument('--role', help='one role: appear, work, finish')
    parser.add_argument('--all', action='store_true', help='every role, one after another')
    parser.add_argument('--approval', metavar='ROLE', help='appear, raise a hand, wait for a card')
    parser.add_argument('--timeout', type=float, default=120.0, help='approval wait, seconds')
    parser.add_argument('--delay', type=float, default=0.4, help='seconds between characters')
    parser.add_argument('--url', help='office base URL (sets OFFICE_URL)')
    args = parser.parse_args(argv)

    known = roles()
    if args.list:
        print('\n'.join(known))
        return 0

    if args.url:
        os.environ['OFFICE_URL'] = args.url
    os.environ['OFFICE_TOKEN'] = resolve_token()

    from . import bridge  # imported after the environment is ready

    print(f'office: {bridge.OFFICE_URL}')

    if args.approval:
        role = args.approval
        if role not in known:
            print(f'unknown role {role!r}; try --list', file=sys.stderr)
            return 2
        aid = bridge.agent_start(role, role, 'Smoke: minta persetujuan')
        bridge.agent_waiting(aid, 'Smoke test: setujui kartu ini?', ['Approve', 'Reject'])
        print(f'waiting up to {args.timeout:.0f}s for a button on {aid} ...')
        decision = bridge.wait_for_approval(aid, timeout=args.timeout)
        print(f'decision: {decision}')
        bridge.agent_done(aid, f'Smoke selesai ({decision})')
        return 0

    if args.role or args.all:
        chosen = known if args.all else [args.role]
        missing = [r for r in chosen if r not in known]
        if missing:
            print(f'unknown role(s): {", ".join(missing)}; try --list', file=sys.stderr)
            return 2
        for role in chosen:
            aid = bridge.agent_start(role, role, f'Smoke: {role}')
            bridge.agent_update(aid, 'Bekerja...', tool='smoke')
            time.sleep(args.delay)
            bridge.agent_done(aid, 'Smoke ok')
            print(f'{role:<18} {aid}')
        left = bridge.pending_events()
        if left:
            print(f'{left} event(s) are in the DLQ; is the office running?', file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
