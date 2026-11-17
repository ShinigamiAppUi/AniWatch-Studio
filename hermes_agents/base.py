"""base.py - one office character around one pipeline step.

`with Agent('Scraper', 'Scraper', 'Cari episode baru') as a:` puts the character
at its desk, and every `a.update(...)` is the bubble the person watching sees.
The step's work runs inside; success says done, an exception says error.

Headless: without `OFFICE_TOKEN` (or when the office is down) every call is
skipped with a warning, because the pipeline must not depend on the office
(ADR-3). The step still runs.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class Agent:
    """A bridge character whose lifetime is one `with` block."""

    def __init__(self, role: str, task: str, name: str | None = None) -> None:
        self.role = role
        self.task = task
        self.name = name or role
        self.id: str | None = None
        self._bridge = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> 'Agent':
        if not os.environ.get('OFFICE_TOKEN', '').strip():
            log.warning('%s: OFFICE_TOKEN kosong - jalan tanpa karakter di kantor', self.role)
            return self
        try:
            from hermes_bridge import bridge
            self._bridge = bridge
            self.id = bridge.agent_start(self.name, self.role, self.task)
        except Exception as err:  # noqa: BLE001 - the step must still run
            log.warning('%s: kantor tidak bisa dihubungi (%s) - lanjut headless', self.role, err)
            self._bridge = None
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._bridge and self.id:
            try:
                if exc is None:
                    self._bridge.agent_done(self.id, self.task)
                else:
                    self._bridge.agent_error(self.id, f'{exc_type.__name__}: {exc}', retrying=False)
            except Exception as err:  # noqa: BLE001
                log.warning('%s: gagal menutup karakter: %s', self.role, err)
        return False  # never swallow the step's exception

    # -- what the person sees ---------------------------------------------

    def update(self, status: str, tool: str | None = None) -> None:
        log.info('%s: %s', self.role, status)
        if self._bridge and self.id:
            try:
                self._bridge.agent_update(self.id, status, tool=tool)
            except Exception as err:  # noqa: BLE001
                log.debug('%s: update tidak terkirim: %s', self.role, err)

    def ask(self, message: str, options: list[str], timeout: float = 3600) -> str:
        """Raise a hand and wait for the button. `timeout` on purpose: the
        office's card is the only way to answer, so a headless run times out."""
        log.info('%s: minta persetujuan: %s %s', self.role, message, options)
        if not (self._bridge and self.id):
            return 'timeout'
        try:
            self._bridge.agent_waiting(self.id, message, options)
            return self._bridge.wait_for_approval(self.id, timeout=timeout)
        except Exception as err:  # noqa: BLE001
            log.warning('%s: approval gagal: %s', self.role, err)
            return 'timeout'
