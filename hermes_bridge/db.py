"""db.py - the business database: one place that connects and initialises it.

`~/.hermes-office/hermes.db` (override with `HERMES_DB`), created and chmodded
here so no agent ever needs to know where it lives or how it is opened
(DB-SCHEMA.md §12). The DDL is `schema_biz.sql` next to this file, read by
path rather than by working directory.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / 'schema_biz.sql'


def db_path() -> Path:
    explicit = os.environ.get('HERMES_DB')
    return Path(explicit) if explicit else Path.home() / '.hermes-office' / 'hermes.db'


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the business DB with row access by name and WAL enabled."""
    target = Path(path) if path else db_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    con = sqlite3.connect(str(target), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return con


def init_db(path: Path | None = None) -> None:
    """Create every table that does not exist yet. Safe to call on each start."""
    con = connect(path)
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        con.commit()
    finally:
        con.close()


def migrate(path: Path | None = None) -> None:
    """Add columns this fork introduced to an older database.

    Idempotent and additive only: never `DROP`. A destructive change belongs in
    `scripts/migrations/`, run by a person.
    """
    con = connect(path)
    try:
        cols = {r['name'] for r in con.execute('PRAGMA table_info(tickets)')}
        if cols and 'assignee' not in cols:
            con.execute('ALTER TABLE tickets ADD COLUMN assignee TEXT')
        # W10: the SLA gauge needs a measured first response, not a guess from
        # `resolved_at` (resolution time is not response time)
        if cols and 'first_response_at' not in cols:
            con.execute('ALTER TABLE tickets ADD COLUMN first_response_at REAL')
        cols = {r['name'] for r in con.execute('PRAGMA table_info(premium_items)')}
        if cols and 'preview_dark' not in cols:
            con.execute('ALTER TABLE premium_items ADD COLUMN preview_dark TEXT')
        con.commit()
    finally:
        con.close()


def backup(dest: Path | None = None) -> Path:
    """Write a consistent copy (SQLite's own backup API, safe while in use)."""
    target = Path(dest) if dest else db_path().with_suffix('.backup.db')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    src = connect()
    out = sqlite3.connect(str(target))
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target
