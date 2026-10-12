"""An adversarial corpus for the sensitive-data screen.

`SECURITY.md` and `docs/VALIDATION.md` both record the same weakness: the
detector is pattern-based and has had **no adversarial testing**. Adding
patterns does not address that — a count is not a quality — so this file is the
part that does.

Every class gets two cases:

* a **positive**: a synthetic credential of that shape, which must be detected;
* a **near-miss negative**: something with the same flavour that must *not* be, because a screen that quarantines ordinary prose is one an operator turns off.

All values here are invented. They are shaped like credentials and are not
credentials, which is exactly why the whole file is allow-listed in
`tools/scan_secrets.py` with that reason — the documented workflow for a
deliberate fixture.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric.governance.sensitive import (  # noqa: E402
    _PATTERNS, SensitiveDataDetector,
)

# kind -> (must be detected, must NOT be detected as that kind)
CASES: dict[str, tuple[str, str]] = {
    "private_key": (
        "-----BEGIN RSA PRIVATE KEY-----",
        "the private key ceremony is documented in the runbook",
    ),
    "aws_access_key": (
        "AKIAQQQQWWWWEEEERRRR",
        "AKIA is the prefix AWS uses for access key ids",
    ),
    "github_token": (
        "ghp_" + "a1b2c3d4e5" * 3 + "f6g7h8",
        "ghp_short is not a token",
    ),
    "slack_token": (
        "xoxb-1111111111-2222222222-abcdefghijklmnop",
        "xoxb- prefixes a Slack bot token",
    ),
    "anthropic_key": (
        "sk-ant-api03-" + "Z" * 20,
        "sk-ant is the prefix, not the key",
    ),
    "openai_key": (
        "sk-" + "A1b2C3d4" * 4 + "Zz",
        "sk-tooshort",
    ),
    "jwt": (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27u",
        "eyJ is how a base64 JSON header begins",
    ),
    "google_api_key": (
        "AIza" + "Sy" + "B" * 33,
        "AIzaSy is the Google key prefix",
    ),
    "google_oauth_secret": (
        "GOCSPX-" + "q" * 28,
        "GOCSPX- marks a Google OAuth client secret",
    ),
    "stripe_key": (
        "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
        "sk_live_ is the Stripe prefix",
    ),
    "gitlab_token": (
        "glpat-" + "x" * 20,
        "glpat- is the GitLab personal access token prefix",
    ),
    "huggingface_token": (
        "hf_" + "Q" * 34,
        "hf_ prefixes a Hugging Face token",
    ),
    "npm_token": (
        "npm_" + "n" * 36,
        "npm_ is the registry token prefix",
    ),
    "sendgrid_key": (
        "SG." + "a" * 22 + "." + "b" * 43,
        "SG. is a SendGrid prefix",
    ),
    "twilio_sid": (
        "AC" + "0123456789abcdef" * 2,
        "AC prefixes a Twilio account sid",
    ),
    "slack_webhook": (
        "https://hooks.slack.com/services/T0000/B0000/abcdefghijklmnopqrst",
        "https://hooks.slack.com/ is the webhook host",
    ),
    "connection_string": (
        "postgres://svc_user:hunter2hunter2@db.internal:5432/app",
        "postgres://db.internal:5432/app has no credentials in it",
    ),
    "azure_storage_key": (
        "AccountKey=" + "k" * 44,
        "AccountKey is read from the environment",
    ),
    "iban": (
        "GB29NWBK60161331926819",
        "GB is the country code for the United Kingdom",
    ),
    "ni_number_uk": (
        # A *valid* prefix. My first attempt used "QQ", which the pattern
        # correctly rejects: real NI prefixes exclude D, F, I, Q, U and V, and
        # the character class encodes that. The test was wrong and the pattern
        # was right, which is the useful direction for a first failure.
        "AB123456C",
        "NI numbers are two letters, six digits and a letter",
    ),
    "password_assignment": (
        "password = correcthorsebattery",
        "the password policy requires rotation every ninety days",
    ),
    "credit_card": (
        "4111 1111 1111 1111",
        "invoice 4111 for the quarter",
    ),
    "ssn_us": (
        "123-45-6789",
        "extension 123-45 on the directory",
    ),
    "email": (
        "ops.lead+alerts@example.com",
        "contact the ops lead at the address on file",
    ),
    "ipv4": (
        "192.168.10.24",
        "version 1.2.3 of the agent",
    ),
    "phone": (
        "+44 20 7946 0958",
        "call extension 4412",
    ),
}


def kinds_found(text: str) -> set[str]:
    detector = SensitiveDataDetector(check_entropy=False)
    return {finding.kind for finding in detector.scan(text)}


class TestEveryPatternHasBothCases(unittest.TestCase):
    def test_no_pattern_is_untested(self):
        """A pattern nobody tried is a pattern nobody has checked.

        This is the assertion that makes the file worth having: a new pattern
        cannot be added without a positive and a near-miss, which is the
        discipline `SECURITY.md` says was missing.
        """
        declared = {kind for kind, _, _ in _PATTERNS}
        self.assertEqual(
            declared - set(CASES), set(),
            "every pattern needs a positive and a near-miss negative here")

    def test_no_case_names_a_pattern_that_does_not_exist(self):
        declared = {kind for kind, _, _ in _PATTERNS}
        self.assertEqual(set(CASES) - declared, set())


class TestPositives(unittest.TestCase):
    def test_every_class_is_detected(self):
        for kind, (positive, _) in CASES.items():
            with self.subTest(kind=kind):
                found = kinds_found(positive)
                self.assertTrue(
                    found,
                    f"{kind}: nothing detected in a synthetic credential")
                # Attribution is checked loosely on purpose: the table is
                # ordered most-specific-first and several classes legitimately
                # overlap -- an Anthropic key also matches the OpenAI prefix,
                # and a connection string also contains a password. What must
                # not happen is nothing firing at all.
                self.assertIn(
                    kind, found | {"password_assignment", "openai_key",
                                   "high_entropy_string"},
                    f"{kind}: detected as {sorted(found)} instead")


class TestNearMissNegatives(unittest.TestCase):
    def test_prose_about_a_secret_is_not_a_secret(self):
        """The failure that gets a screen switched off.

        Each negative mentions the same vendor, prefix or concept as its
        positive. A detector that cannot tell "AKIA is the prefix AWS uses"
        from an actual key quarantines the documentation that explains itself.
        """
        for kind, (_, negative) in CASES.items():
            with self.subTest(kind=kind):
                self.assertNotIn(
                    kind, kinds_found(negative),
                    f"{kind} fired on: {negative!r}")


class TestTheHighSeverityBoundary(unittest.TestCase):
    """Which classes stop a write, and which only annotate it."""

    def test_credentials_are_high_and_contact_details_are_medium(self):
        severity = {kind: level for kind, level, _ in _PATTERNS}
        for kind in ("private_key", "aws_access_key", "connection_string",
                     "stripe_key", "iban", "ni_number_uk"):
            with self.subTest(kind=kind):
                self.assertEqual(severity[kind], "high")
        for kind in ("email", "ipv4", "phone"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    severity[kind], "medium",
                    "an email address in a memory is worth annotating and not "
                    "worth refusing a write for")


class TestItDoesNotFireOnOrdinaryMemories(unittest.TestCase):
    """The false-positive rate that matters: normal content.

    Sampled from the benchmark fixtures' own vocabulary rather than invented,
    because the shapes that trip a detector are identifiers and numbers, and
    this project's memories are full of both.
    """

    ORDINARY = [
        "crane-5 requires 2.4 m of clearance at the coastal site.",
        "Bay 17 at the depot-12 site is assigned to chiller-1.",
        "Survey S-204 measured the inland quay at 31 tonnes per square metre.",
        "Vehicles with the standard axle set run 4.0 bar in summer.",
        "01M4NYMRBFF85WF52JMPF30FN2 is the memory id of the root observation.",
        "The weighbridge is calibrated every six months and passed in February.",
        "At the estuary site, swap the tug-8 signal cable every 180 days.",
    ]

    def test_nothing_fires(self):
        for text in self.ORDINARY:
            with self.subTest(text=text[:40]):
                self.assertEqual(
                    kinds_found(text), set(),
                    f"a screen that fires on this would quarantine the corpus")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
