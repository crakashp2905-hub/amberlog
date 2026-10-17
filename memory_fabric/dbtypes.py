"""The connection and row types the storage-sharing modules accept.

`EventLog`, `IntegrityChain`, `ContentVault`, `Outbox` and the revocation store
share one connection, which is either a `sqlite3.Connection` or the
`pgcompat.PgConnection` that presents psycopg as the same interface. Annotating
them as `sqlite3.Connection` was true until the Postgres backend existed and
has been a lie to the type checker since: 15 of mypy's 27 findings were that
one mismatch. This names the union once.

Typing only. Nothing here runs, and importing it does not import psycopg.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:  # pragma: no cover
    from .pgcompat import PgConnection
    from .pgcompat import Row as PgRow

Connection = Union[sqlite3.Connection, "PgConnection"]
Row = Union[sqlite3.Row, "PgRow"]

__all__ = ["Connection", "Row"]
