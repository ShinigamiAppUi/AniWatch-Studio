"""inbox.py - reading the support mailbox over IMAP (standard library).

`send_reply` writes out; this is the way in. Gmail, Fastmail and any IMAP server
work with the same settings, and `imaplib` is in the standard library, so the
inbox needs no dependency either.

Three decisions worth knowing:

- `BODY.PEEK[]` instead of `RFC822`: reading a message does not clear the
  unseen flag, so a crash between fetch and ticket creation does not lose the
  mail. Deduplication is ours instead, keyed by UID in SharedContext
  (`inbox:seen`, capped so it cannot grow forever).
- Our own auto-replies are skipped (`Auto-Submitted` other than `no`), which is
  the header `mailer.py` sets. Without that, Support answers itself.
- `fetch_new(factory=...)`: the connection is injectable, so the selfcheck can
  drive the whole path with a fake mailbox and no network.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from email.header import decode_header, make_header

log = logging.getLogger(__name__)

#: How many UIDs we remember as already turned into tickets
SEEN_KEY = 'inbox:seen'
SEEN_MAX = 500

#: How many messages one run handles; the rest wait for the next 5 minutes
MAX_PER_RUN = 10

_QUOTED = re.compile(r'^\s*(>|On .*wrote:|Pada .*menulis:)', re.IGNORECASE)


def _env(name: str) -> str:
    return (os.environ.get(name) or '').strip()


def config() -> dict:
    """The IMAP settings as they are now."""
    try:
        port = int(_env('IMAP_PORT') or 993)
    except ValueError:
        port = 993
    try:
        limit = int(_env('IMAP_MAX_PER_RUN') or MAX_PER_RUN)
    except ValueError:
        limit = MAX_PER_RUN
    return {
        'host': _env('IMAP_HOST'),
        'port': port,
        'user': _env('IMAP_USER'),
        'password': os.environ.get('IMAP_PASSWORD') or '',
        'folder': _env('IMAP_FOLDER') or 'INBOX',
        'limit': max(1, min(limit, 50)),
    }


def configured() -> bool:
    """IMAP needs a host and a login; without both there is nothing to read."""
    cfg = config()
    return bool(cfg['host'] and cfg['user'])


def _connect(cfg: dict):
    """Open the mailbox. TLS always: a support inbox is not read in the clear."""
    client = imaplib.IMAP4_SSL(cfg['host'], cfg['port'])
    client.login(cfg['user'], cfg['password'])
    return client


def _header(value: str | None) -> str:
    """Decode `=?UTF-8?B?...?=` into readable text; a broken header stays raw."""
    if not value:
        return ''
    try:
        return ' '.join(str(make_header(decode_header(value))).split())
    except Exception:  # noqa: BLE001 - a malformed header is not a lost mail
        return ' '.join(str(value).split())


def _body_text(message) -> str:
    """The plain-text part, quotes trimmed: what the customer actually wrote."""
    text = ''
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == 'text/plain' and part.get_content_disposition() is None:
                payload = part.get_payload(decode=True) or b''
                charset = part.get_content_charset() or 'utf-8'
                text = payload.decode(charset, 'replace')
                break
    else:
        payload = message.get_payload(decode=True) or b''
        text = payload.decode(message.get_content_charset() or 'utf-8', 'replace')
    lines = [line for line in text.splitlines() if not _QUOTED.match(line)]
    return ' '.join(' '.join(lines).split())[:4000]


def parse_message(raw: bytes) -> dict:
    """One IMAP message -> `{uid?, from, from_name, subject, body}`."""
    message = email.message_from_bytes(raw)
    sender = email.utils.parseaddr(_header(message.get('From')))[1] if message.get('From') else ''
    name = email.utils.parseaddr(_header(message.get('From')))[0] if message.get('From') else ''
    return {
        'from': sender.strip().lower(),
        'from_name': name.strip(),
        'subject': _header(message.get('Subject'))[:200],
        'body': _body_text(message),
        'auto': (message.get('Auto-Submitted') or 'no').strip().lower() != 'no',
    }


def _seen() -> set[str]:
    try:
        from . import store

        stored = store.context().get(SEEN_KEY)
        return set(stored.get('uids') or []) if isinstance(stored, dict) else set()
    except Exception as err:  # noqa: BLE001 - a missing context means "nothing seen"
        log.debug('inbox: tidak bisa membaca daftar uid: %s', err)
        return set()


def _remember(uids: list[str]) -> None:
    try:
        from . import store

        merged = list(dict.fromkeys(uids + list(_seen())))
        store.context().set(SEEN_KEY, {'uids': merged[:SEEN_MAX]}, 'inbox')
    except Exception as err:  # noqa: BLE001
        log.warning('inbox: gagal menyimpan daftar uid (%s) - email bisa diproses dua kali', err)


def fetch_new(factory=None, *, now_seen: bool = True) -> list[dict]:
    """Fetch unread mail that was never turned into a ticket.

    Raises `RuntimeError` when IMAP is not configured: the caller decides
    whether that is a warning once an hour or a real error.
    """
    cfg = config()
    # A caller that brings its own connection does not need our settings; the
    # check is only about the client this function would build itself
    if factory is None and not configured():
        raise RuntimeError('IMAP belum dikonfigurasi (IMAP_HOST/IMAP_USER kosong)')

    client = (factory or _connect)(cfg)
    try:
        client.select(cfg['folder'])
        status, data = client.uid('search', None, 'UNSEEN')
        if status != 'OK':
            log.warning('inbox: pencarian gagal: %s', status)
            return []
        uids = [u.decode() if isinstance(u, bytes) else str(u) for u in (data[0] or b'').split()]
        skip = _seen()
        fresh = [uid for uid in uids if uid not in skip][:cfg['limit']]

        messages: list[dict] = []
        for uid in fresh:
            status, payload = client.uid('fetch', uid, '(BODY.PEEK[])')
            if status != 'OK' or not payload or not isinstance(payload[0], tuple):
                log.warning('inbox: uid %s tidak bisa diambil', uid)
                continue
            parsed = parse_message(payload[0][1])
            if parsed.pop('auto') or not parsed['from']:
                # Our own auto-reply, or no sender to answer
                continue
            parsed['uid'] = uid
            messages.append(parsed)
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001 - a failed logout is not a failed fetch
            pass

    if now_seen and messages:
        _remember([m['uid'] for m in messages])
    return messages
