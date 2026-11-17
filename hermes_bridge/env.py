"""env.py - the one place a process turns `.env` into environment variables.

Why one: four entry points need the same settings (the sidecar, the episode
pipeline, the self-check and the bridge's smoke run), and `.env` must never be
read by a *library* at import time - `bridge.py` stays import-safe
(docs/hermes-office/ENV-VARS.md §5).

Rules this loader keeps:

- A variable already in the environment wins, so one run can override one value:
  `OFFICE_TOKEN=$(cat ~/.agent-office/auth-token) python -m hermes_agents.pipeline`
- `KEY=value`, `# comments`, blank lines, an optional `export `, and a value in
  single or double quotes.
- `${VAR}`, `${VAR:-default}` and `$VAR` expand from the environment.
- `$(cat path)` and `$(cat "path")` read that file, because that is the form
  `.env.example` tells you to use for `OFFICE_TOKEN`; a plain reader would
  otherwise store the literal text `$(cat ...)` as the token.

No value is ever logged: a warning names the file, the line and the key only.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = ROOT / '.env'

_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_VAR_RE = re.compile(
    r'\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::-?(?P<default>[^}]*))?\}'
    r'|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))'
)
_CAT_RE = re.compile(r'^\$\(\s*cat\s+(?P<path>.+?)\s*\)$')


def env_path() -> Path:
    """`$HERMES_ENV_FILE`, else `.env` at the repository root."""
    explicit = os.environ.get('HERMES_ENV_FILE')
    return Path(explicit).expanduser() if explicit else DEFAULT_ENV_PATH


def load_env(path: Path | None = None, *, override: bool = False) -> int:
    """Set the variables in `path` (default: `env_path()`).

    Args:
        path: the file to read; a missing file is not an error (every value has
            a default, and a container passes its variables in the environment)
        override: replace variables that are already set (off: the environment
            wins, which is what a one-off `FOO=bar python ...` needs)

    Returns:
        How many variables were set - 0 for a missing or empty file.
    """
    target = Path(path).expanduser() if path else env_path()
    try:
        text = target.read_text(encoding='utf-8')
    except FileNotFoundError:
        return 0
    except OSError as err:  # a directory, a permission problem: say so, do not crash
        log.warning('env: cannot read %s: %s', target, err)
        return 0

    loaded = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            log.warning('env: %s:%d is not KEY=value; skipped', target, number)
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _value(value.strip(), target, number)
        loaded += 1
    return loaded


def _value(raw: str, target: Path, number: int) -> str:
    """A line's value: `$(cat ...)`, else quotes removed and variables expanded.

    A trailing ` # note` is dropped from an unquoted value, as a shell would; it
    is kept inside quotes (`B="a # b"`), where it is part of the value.
    """
    cat = _CAT_RE.match(raw)
    if cat:
        return _read_file(cat.group('path'), target, number)
    if raw[:1] in ('"', "'"):
        return _expand(_unquote(raw))
    return _expand(raw.split(' #', 1)[0].strip())


def _read_file(spec: str, target: Path, number: int) -> str:
    """The trimmed contents of the file named in `$(cat ...)`; '' when unreadable."""
    name = _expand(_unquote(spec.strip()))
    try:
        return Path(name).expanduser().read_text(encoding='utf-8').strip()
    except OSError as err:
        log.warning('env: %s:%d cannot read %s: %s', target, number, name, err)
        return ''


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _expand(value: str) -> str:
    """`${VAR}`, `${VAR:-default}` and `$VAR` from the environment.

    Expanded more than once (bounded) so a nested default such as
    `${AGENT_OFFICE_HOME:-$HOME/.agent-office}` resolves all the way through.
    """

    def replace(match: re.Match[str]) -> str:
        braced = match.group('braced')
        if braced:
            return os.environ.get(braced, match.group('default') or '')
        return os.environ.get(match.group('bare') or '', '')

    result = value
    for _ in range(5):
        expanded = _VAR_RE.sub(replace, result)
        if expanded == result:
            break
        result = expanded
    return result
