"""Physical tenant isolation: separate files, separate keys, nothing shared."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from amberlog.governance.erasure import DirectoryKeyProvider
from amberlog.tenancy import TenantRouter


class Router(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.router = TenantRouter(self.root, auto_activate=True)
        self.addCleanup(self.router.close)

    def test_each_tenant_has_its_own_file_and_keys(self) -> None:
        a = self.router.view("acme", "ann").remember("Acme plans to acquire Contoso.", scope="team")
        self.router.view("globex", "gus").remember("Globex ships valves.", scope="team")
        self.assertEqual(self.router.tenants(), ["acme", "globex"])
        self.assertNotIn(a, self.router.store("globex").state.memories)
        self.assertEqual(self.router.view("globex", "gus").retrieve("acquire Contoso").exposed, [])
        self.assertNotEqual(self.router.store("acme").store_id, self.router.store("globex").store_id)

    def test_another_tenants_keys_cannot_read_the_file(self) -> None:
        self.router.view("acme", "ann").remember("Acme plans to acquire Contoso.", scope="team")
        self.router.view("globex", "gus").remember("x", scope="team")
        self.router.close()
        try:
            wrong = Amberlog(str(self.root / "acme" / "store.db"),
                                 key_provider=DirectoryKeyProvider(str(self.root / "globex" / "keys")))
        except Exception:  # noqa: BLE001 - refusing to open is the strongest outcome
            return
        try:
            readable = [m.content for m in wrong.state.memories.values()]
        finally:
            wrong.close()
        self.assertFalse(any("Contoso" in c for c in readable), readable)

    def test_tenant_ids_cannot_name_a_path(self) -> None:
        for bad in ("../acme", "Acme", "a/b", "", "a" * 65, "..", "acme x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.router.store(bad)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
