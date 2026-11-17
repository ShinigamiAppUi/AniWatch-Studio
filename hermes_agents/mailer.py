"""mailer.py - the one way Support sends mail: SMTP, standard library only.

Why SMTP rather than the Gmail API ENV-VARS.md §3 mentions: SMTP needs no OAuth
round trip and no extra dependency, and every provider (Gmail with an app
password, Mailgun, SES, a local Postfix) speaks it. One host and one password is
a setup a self-hosted office can actually finish.

Failure is a value, never an exception: `send()` returns
`{sent, error, to, subject, at}` and writes the attempt to the outbox whether it
went out or not. Support keeps the ticket `open` when the mail did not leave, so
the next SLA run bills it instead of the ticket looking answered.

`transport` exists for tests and for a caller that wants to send its own way: the
default is the SMTP client below, and anything callable that takes the built
`EmailMessage` can stand in.
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

#: Deliberately loose: one @, something on both sides, a dot in the domain.
RECIPIENT_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

#: The reply says so in its headers, so a mail client can loop-guard on it
AUTO_SUBMITTED = 'auto-replied'

_PORTS = {'ssl': 465, 'starttls': 587, 'none': 25}


def _env(name: str) -> str:
    return (os.environ.get(name) or '').strip()


def config() -> dict:
    """The SMTP settings as they are now; every value has a safe default."""
    security = _env('SMTP_SECURITY').lower()
    if security not in _PORTS:
        security = 'starttls'
    try:
        port = int(_env('SMTP_PORT') or _PORTS[security])
    except ValueError:
        port = _PORTS[security]
    try:
        timeout = float(_env('SMTP_TIMEOUT_S') or 15)
    except ValueError:
        timeout = 15.0
    user = _env('SMTP_USER')
    return {
        'host': _env('SMTP_HOST'),
        'port': port,
        'security': security,
        'user': user,
        'password': os.environ.get('SMTP_PASSWORD') or '',
        'sender': _env('SUPPORT_FROM') or user or 'support@aniwatch.example',
        'sender_name': _env('SUPPORT_FROM_NAME') or 'AniWatch Support',
        'timeout': timeout,
    }


def configured() -> bool:
    """True when mail can go out at all (a host is the one thing SMTP needs)."""
    return bool(config()['host'])


def outbox_path() -> Path:
    """Where every attempt is logged: `HERMES_OUTBOX` or ~/.hermes-office/outbox."""
    explicit = _env('HERMES_OUTBOX')
    return Path(explicit) if explicit else Path.home() / '.hermes-office' / 'outbox' / 'replies.jsonl'


def _clip(value: object, limit: int) -> str:
    return ' '.join(str(value or '').split())[:limit]


def _build(cfg: dict, to: str, subject: str, body: str) -> EmailMessage:
    """One plain-text reply, with the headers a real mailbox expects."""
    message = EmailMessage()
    message['From'] = f'{cfg["sender_name"]} <{cfg["sender"]}>'
    message['To'] = to
    message['Subject'] = _clip(subject, 200) or 'AniWatch Support'
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=cfg['sender'].split('@')[-1] or 'aniwatch.example')
    message['Auto-Submitted'] = AUTO_SUBMITTED
    message.set_content(str(body or ''))
    return message


def _smtp_send(cfg: dict, message: EmailMessage) -> None:
    """The default transport: connect, authenticate if asked, send, hang up."""
    if cfg['security'] == 'ssl':
        server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=cfg['timeout'])
    else:
        server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=cfg['timeout'])
    try:
        if cfg['security'] == 'starttls':
            server.starttls()
        if cfg['user']:
            server.login(cfg['user'], cfg['password'])
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001 - a broken QUIT must not mask the send result
            server.close()


def _record(entry: dict) -> dict:
    """Append the attempt to the outbox and return it. Never raises."""
    path = outbox_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        entry['outbox'] = str(path)
    except OSError as err:
        log.warning('mailer: outbox tidak bisa ditulis (%s)', err)
        entry['outbox'] = None
    return entry


def send(to: str, subject: str, body: str, *, transport: Callable[[EmailMessage], object] | None = None,
         now: float | None = None) -> dict:
    """Send one reply. Returns `{at, to, subject, sent, error, outbox}`.

    A missing recipient, missing SMTP settings or a transport that raises all
    come back as `sent: False` with the reason in `error` — the caller decides
    what that means for its ticket, and the outbox keeps the record.
    """
    at = time.time() if now is None else float(now)
    recipient = _clip(to, 200)
    entry = {'at': at, 'to': recipient, 'subject': _clip(subject, 200)}

    if not RECIPIENT_RE.match(recipient):
        return _record({**entry, 'sent': False, 'error': 'penerima bukan alamat email'})

    cfg = config()
    if transport is None and not cfg['host']:
        return _record({**entry, 'sent': False,
                        'error': 'SMTP belum dikonfigurasi (SMTP_HOST kosong)'})

    try:
        message = _build(cfg, recipient, entry['subject'], body)
        if transport is None:
            _smtp_send(cfg, message)
        else:
            transport(message)
    except Exception as err:  # noqa: BLE001 - a mail server problem is a ticket state, not a crash
        log.warning('mailer: kirim ke %s gagal: %s', recipient, err)
        return _record({**entry, 'sent': False, 'error': _clip(err, 300)})

    log.info('mailer: balasan terkirim ke %s', recipient)
    return _record({**entry, 'sent': True, 'error': None})


def attempts(limit: int = 20) -> list[dict]:
    """The last `limit` attempts, newest first; [] when nothing was tried yet."""
    path = outbox_path()
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError as err:
        log.warning('mailer: outbox tidak bisa dibaca (%s)', err)
        return []
    return rows[-max(1, int(limit)):][::-1]


def last_attempt() -> dict | None:
    """The newest attempt, for `/health` and `npm run doctor`."""
    rows = attempts(1)
    return rows[0] if rows else None


def status() -> dict:
    """A small, safe summary: configured or not, and the last attempt."""
    last = last_attempt()
    return {
        'configured': configured(),
        'last': None if last is None else {'at': last.get('at'), 'to': last.get('to'),
                                           'sent': bool(last.get('sent')), 'error': last.get('error')},
    }
