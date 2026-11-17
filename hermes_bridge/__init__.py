"""hermes_bridge - the Python side of Hermes Office.

A business agent never talks to Express directly: it imports this package and
calls `bridge.agent_start()` / `agent_update()` / `agent_done()`, and the
character appears at its own desk on floor 2 (docs/hermes-office/ROOMS.md).

Only `hex` and `sqlite3` from the standard library are needed to draw an
agent; `httpx` is for the calls to the office server. `env.py` is the one
`.env` loader, called by an entry point (never at import time).
"""

__all__ = ['bridge', 'env', 'handoff', 'queue', 'shared_context', 'db', 'smoke']

__version__ = '0.5.0'
