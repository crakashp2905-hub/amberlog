"""Physical tenant isolation: one store file and one key directory per tenant.

`tenant_id` inside one store is an authorisation boundary (`identity.py`):
it holds against bugs in ranking, indexes and federation, not against
someone holding the database file. For tenants that must not share a file,
`TenantRouter` gives each its own:

    <root>/<tenant>/store.db      the event log and projections
    <root>/<tenant>/keys/         that tenant's content keys, outside the database

Nothing is shared between tenants: not a connection, a lock, an index, a
key or a cache. A request for one tenant can only ever open that tenant's
directory, and tenant ids are restricted to `[a-z0-9_-]` so an id cannot
name a path outside the root. Removing a tenant is deleting its directory,
which is an operator's decision and not offered here.
"""

from __future__ import annotations

__stability__ = "beta"

import re
import threading
from pathlib import Path
from typing import Any

from .fabric import Amberlog, TenantView
from .governance.erasure import DirectoryKeyProvider
from .identity import Principal

TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class TenantRouter:
    def __init__(self, root: str | Path, **fabric_kwargs: Any) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fabric_kwargs = fabric_kwargs
        self._open: dict[str, Amberlog] = {}
        self._lock = threading.Lock()

    def _dir(self, tenant_id: str) -> Path:
        if not TENANT_ID.match(tenant_id):
            raise ValueError(f"invalid tenant id {tenant_id!r}: use [a-z0-9_-], at most 64")
        path = (self.root / tenant_id).resolve()
        if path.parent != self.root.resolve():
            raise ValueError(f"tenant id {tenant_id!r} escapes the root")
        return path

    def store(self, tenant_id: str) -> Amberlog:
        """This tenant's own store, created on first use."""
        with self._lock:
            if tenant_id not in self._open:
                directory = self._dir(tenant_id)
                (directory / "keys").mkdir(parents=True, exist_ok=True)
                self._open[tenant_id] = Amberlog(
                    str(directory / "store.db"),
                    key_provider=DirectoryKeyProvider(str(directory / "keys")),
                    **self.fabric_kwargs)
            return self._open[tenant_id]

    def view(self, tenant_id: str, agent_id: str) -> TenantView:
        """A tenant-scoped handle on that tenant's own store."""
        fabric = self.store(tenant_id)
        return TenantView(fabric, Principal(agent_id=agent_id, tenant_id=tenant_id),
                          verified=True)

    def tenants(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and TENANT_ID.match(p.name) and (p / "store.db").exists())

    def close(self) -> None:
        with self._lock:
            for fabric in self._open.values():
                fabric.close()
            self._open.clear()
