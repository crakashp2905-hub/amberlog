"""The production cryptography profile uses the maintained library or refuses to run."""

from __future__ import annotations

import unittest
from unittest import mock

from amberlog import Amberlog
from amberlog.governance import cipher
from amberlog.governance.cipher import IntegrityError


def sealed(f: Amberlog) -> str:
    row = f.log._conn.execute("SELECT payload FROM events WHERE type = 'MemoryCreated'").fetchone()
    return str(row["payload"])


class Profiles(unittest.TestCase):
    def tearDown(self) -> None:
        cipher._profile = None
        cipher._reset_aead_status()

    @unittest.skipUnless(cipher.aead_available(), "cryptography not installed")
    def test_production_writes_only_aes_gcm(self) -> None:
        f = Amberlog(":memory:", crypto_profile="production")
        self.addCleanup(f.close)
        f.remember("a", "Valve V7 opens below 4 bar.")
        self.assertIn(cipher.GCM_PREFIX, sealed(f))

    def test_production_refuses_to_open_without_the_library(self) -> None:
        with mock.patch.object(cipher, "aead_status", return_value=(False, "not installed")):
            with self.assertRaises(IntegrityError):
                Amberlog(":memory:", crypto_profile="production")

    def test_compatible_falls_back_to_encrypt_then_mac(self) -> None:
        with mock.patch.object(cipher, "aead_status", return_value=(False, "not installed")):
            f = Amberlog(":memory:", crypto_profile="compatible")
            self.addCleanup(f.close)
            f.remember("a", "Valve V7 opens below 4 bar.")
            self.assertIn(cipher.ETM_PREFIX, sealed(f))

    def test_an_unknown_profile_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            cipher.set_profile("fast")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
