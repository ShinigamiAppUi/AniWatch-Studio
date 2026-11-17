"""hermes_bridge - the Python side of Hermes Office.

A business agent never talks to Express directly: it imports this package and
calls `bridge.agent_start()` / `agent_update()` / `agent_done()`, and the
character appears at its own desk on floor 2 (docs/hermes-office/ROOMS.md).

Only `hex` and `sqlite3` from the standard library are needed to draw an
agent; `httpx` is for the calls to the office server.
"""

__all__ = ['bridge', 'queue', 'shared_context', 'db', 'smoke']

__version__ = '0.2.0'
