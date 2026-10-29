"""Red team for the sensitive-data screen: obfuscated secrets.

`test_sensitive_patterns.py` checks each pattern against a plain positive and a
near-miss. This checks what someone does to get a secret *past* a pattern.
Before 2026-10-16 the screen caught **none** of the 13 obfuscations below at
high severity: an invisible character, a space or a base64 wrapper was enough
(three drew a medium-severity entropy or phone warning, which does not
quarantine). Variant scanning in `governance/sensitive.py` now catches 12; the
one left is in `KNOWN_MISSES` with its reason, so a regression and a known gap
read differently.

Near-miss negatives matter as much here as there: a variant pass that decodes
every ULID and hash into a finding would make the screen useless.

All values are invented and shaped like credentials, and the file is
allow-listed in `tools/scan_secrets.py` for that reason.
"""

from __future__ import annotations

import base64
import unittest

from amberlog.governance.sensitive import SensitiveDataDetector, scrub, secret_values

AWS = "AKIA" + "QQQQWWWWEEEERRRR"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FULLWIDTH = "".join(chr(ord(c) + 0xFEE0) if c.isalnum() else c for c in AWS)

# name -> text that must be caught at high severity
EVASIONS: dict[str, str] = {
    "zero-width character inside": "deploy key AKIA​QQQQWWWWEEEERRRR",
    "split by spaces": "deploy key AKIA QQQQ WWWW EEEE RRRR",
    "split by hyphens": "deploy key AKIA-QQQQ-WWWW-EEEE-RRRR",
    "base64 wrapped": "blob " + base64.b64encode(f"key={AWS}".encode()).decode(),
    "base64 wrapped token": "cfg " + base64.b64encode(GH.encode()).decode(),
    "hex wrapped": "blob " + AWS.encode().hex(),
    "full-width characters": "deploy key " + FULLWIDTH,
    "cyrillic look-alike": "deploy key АKIAQQQQWWWWEEEERRRR",
    "url-encoded": "https://x.example/cb?token%3D" + GH,
    "password in prose": "the admin password is Tr0ub4dor&3xq for the router",
    "lowercase PEM header": "-----begin rsa private key-----",
    "PEM header split across lines": "-----BEGIN RSA PRIVATE\nKEY-----",
}

# name -> (text, why it is accepted as a miss)
KNOWN_MISSES: dict[str, tuple[str, str]] = {
    "reversed": (
        "deploy key " + AWS[::-1],
        "no fixed transformation undoes an arbitrary one; reversal, ROT13 and "
        "custom ciphers need a model, not a pattern",
    ),
}

# Must produce no high-severity finding.
NEAR_MISSES: dict[str, str] = {
    "a ULID": "memory 01M51P1V06V34B503PB1HPYEJG was validated",
    "a sha256": "digest 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "a uuid": "request 3f2504e0-4f89-11d3-9a0c-0305e82c3301 failed",
    "base64 of ordinary text": "note " + base64.b64encode(b"swap the pilot cable first").decode(),
    "hex of ordinary text": "note " + b"pump seven is fine".hex(),
    "spaced capitals": "SITE ALPHA PUMP SEVEN is offline",
    "full-width prose": "Ｐｕｍｐ 7 is offline",
    "percent signs": "efficiency rose 12%3 times this year",
    "password policy": "the password is rotated every 90 days",
}


class ObfuscatedSecretsAreCaught(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = SensitiveDataDetector()

    def test_every_evasion_is_caught(self) -> None:
        for name, text in EVASIONS.items():
            with self.subTest(name):
                self.assertTrue(self.detector.has_high_severity(text), text)

    def test_known_misses_are_still_misses(self) -> None:
        """If one starts being caught, move it to EVASIONS: the gap closed."""
        for name, (text, _why) in KNOWN_MISSES.items():
            with self.subTest(name):
                self.assertFalse(self.detector.has_high_severity(text))

    def test_the_scorecard(self) -> None:
        caught = sum(self.detector.has_high_severity(t) for t in EVASIONS.values())
        self.assertEqual(caught, len(EVASIONS))
        self.assertEqual(len(EVASIONS) + len(KNOWN_MISSES), 13)


class NearMissesStayQuiet(unittest.TestCase):
    def test_no_high_severity_finding(self) -> None:
        detector = SensitiveDataDetector()
        for name, text in NEAR_MISSES.items():
            with self.subTest(name):
                high = [f for f in detector.scan(text) if f.severity == "high"]
                self.assertEqual(high, [], text)


class ScrubbingRemovesTheObfuscatedValue(unittest.TestCase):
    """A finding located in a variant must still point at the characters that
    hold the secret in the original, or display scrubbing redacts the wrong
    span and the secret reaches the screen it was quarantined to keep it off."""

    def test_spans_map_back_to_the_original(self) -> None:
        detector = SensitiveDataDetector()
        for name in ("split by spaces", "zero-width character inside",
                     "full-width characters", "base64 wrapped", "url-encoded"):
            text = EVASIONS[name]
            with self.subTest(name):
                cleaned = scrub(text, secret_values(detector, text))
                self.assertIn("[REDACTED:", cleaned)
                self.assertFalse(detector.has_high_severity(cleaned), cleaned)


if __name__ == "__main__":
    unittest.main()
