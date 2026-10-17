"""Authenticated encryption for memory content, and where the keys live.

Split out of `erasure.py` because two different questions were tangled there:
*how is content protected* and *what does destroying a key mean*. The second is
the interesting one and it was buried under the first.

## What was wrong with the previous scheme

`enc:v1` was an HMAC-SHA256 counter-mode keystream with **no authentication
tag**, which makes the ciphertext malleable: XOR a chosen delta into it and the
plaintext changes to whatever the attacker picked, byte for byte. The
docstring justified this by saying "the append-only log and the event digests
provide [integrity]".

The append-only triggers do raise the bar — a tamper needs file write access to
drop `events_no_update` first, and `memory-fabric doctor` now checks for that.
But **there are no event digests.** The log has `seq`, `event_id`, `ts`,
`type`, `agent_id`, `episode_id`, `schema_version` and `payload`, and nothing
chains or signs them. The justification named a mechanism that does not exist,
which is the same class of defect as a docstring claiming a request is refused
before it is parsed: the code was weaker than the sentence describing it.

## What replaces it

Two suites behind one seam, and the envelope version says which produced a
given ciphertext, so a store can hold all three generations at once:

| envelope | suite | status |
|---|---|---|
| `enc:v1:` | HMAC-CTR, unauthenticated | **read-only.** Decrypted so existing stores still work; never written again. |
| `enc:v2:` | HMAC-CTR + HMAC-SHA256 encrypt-then-MAC | the zero-dependency default |
| `enc:v3:` | AES-256-GCM via `cryptography` | used automatically when the library is installed |

`v2` is a textbook composition of standard primitives, not a new cipher:
independent encryption and MAC subkeys derived by HKDF-Expand, encrypt-then-MAC
in that order, and a constant-time tag comparison **before** any decryption.
That ordering is the point — verifying after decrypting hands an attacker a
decryption oracle, and it is the mistake the previous version could not even
make because it had no tag at all.

`v3` exists because "use a maintained cryptographic library" is the right
default advice and this module should not be the reason someone cannot follow
it. Installing `cryptography` switches new writes to AES-GCM with no
configuration and no migration; `v2` ciphertexts stay readable.

## Associated data, which is the half a tag alone does not cover

A tag proves a ciphertext was not edited. It does not prove the ciphertext is
*the one that belongs here*. Without binding, an attacker with write access
could copy memory X's sealed content over memory Y's — both tags verify, both
are authentic, and Y now says what X said. Worse, an old version's ciphertext
could be pasted over the current one to silently roll a memory back after a
correction, which is precisely the failure the retraction machinery exists to
prevent.

So the AAD binds `store_id`, `memory_id` and `version`. Moving a ciphertext
between memories, between versions, or between stores fails authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import warnings
from typing import Protocol

TAG_BYTES = 32
NONCE_BYTES = 16
GCM_NONCE_BYTES = 12
SUBKEY_INFO_ENC = b"memory-fabric/content/enc/v2"
SUBKEY_INFO_MAC = b"memory-fabric/content/mac/v2"

LEGACY_PREFIX = "enc:v1:"
ETM_PREFIX = "enc:v2:"
GCM_PREFIX = "enc:v3:"

ENVELOPE_PREFIXES = (LEGACY_PREFIX, ETM_PREFIX, GCM_PREFIX)


class IntegrityError(Exception):
    """A ciphertext failed authentication.

    Never recoverable and never silently absorbed. The previous scheme's
    `unseal` decoded with `errors="replace"`, so corrupted ciphertext produced
    mojibake that flowed into a `Memory.content` and from there into an agent's
    context. A tamper has to stop being data and become an exception.
    """


def is_sealed(content: str) -> bool:
    return content.startswith(ENVELOPE_PREFIXES)


def envelope_version(content: str) -> str | None:
    for prefix in ENVELOPE_PREFIXES:
        if content.startswith(prefix):
            return prefix.rstrip(":").rsplit(":", 1)[-1]
    return None


def _hkdf_expand(key: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-Expand (RFC 5869) with SHA-256.

    Extract is skipped deliberately: the input is already 32 uniformly random
    bytes from `secrets.token_bytes`, which is what Extract exists to produce.
    Expand is still needed, because the encryption and MAC keys must be
    independent — using one key for both is the standard way to turn a sound
    composition into an unsound one.
    """
    out = bytearray()
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(key, block + info + bytes([counter]), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(
            hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        )
        counter += 1
    return bytes(out[:length])


class CipherSuite(Protocol):
    name: str
    prefix: str

    def seal(self, plaintext: bytes, key: bytes, aad: bytes) -> str: ...

    def unseal(self, envelope: str, key: bytes, aad: bytes) -> bytes: ...


class EncryptThenMac:
    """`enc:v2` — HMAC-CTR for confidentiality, HMAC-SHA256 for integrity."""

    name = "hmac-ctr+hmac-sha256"
    prefix = ETM_PREFIX

    def seal(self, plaintext: bytes, key: bytes, aad: bytes) -> str:
        enc_key = _hkdf_expand(key, SUBKEY_INFO_ENC)
        mac_key = _hkdf_expand(key, SUBKEY_INFO_MAC)
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = bytes(
            a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext)))
        )
        tag = self._tag(mac_key, nonce, ciphertext, aad)
        return f"{self.prefix}{nonce.hex()}:{ciphertext.hex()}:{tag.hex()}"

    def unseal(self, envelope: str, key: bytes, aad: bytes) -> bytes:
        try:
            _, _, nonce_hex, payload_hex, tag_hex = envelope.split(":", 4)
            nonce = bytes.fromhex(nonce_hex)
            ciphertext = bytes.fromhex(payload_hex)
            tag = bytes.fromhex(tag_hex)
        except ValueError as exc:
            raise IntegrityError(f"malformed v2 envelope: {exc}") from None

        mac_key = _hkdf_expand(key, SUBKEY_INFO_MAC)
        expected = self._tag(mac_key, nonce, ciphertext, aad)
        # Constant time, and **before** decrypting. Verifying afterwards would
        # make this a decryption oracle.
        if not hmac.compare_digest(expected, tag):
            raise IntegrityError(
                "content failed authentication: the ciphertext, its nonce, or "
                "the memory it is bound to has been altered"
            )
        enc_key = _hkdf_expand(key, SUBKEY_INFO_ENC)
        return bytes(
            a ^ b
            for a, b in zip(ciphertext, _keystream(enc_key, nonce, len(ciphertext)))
        )

    @staticmethod
    def _tag(mac_key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
        # Lengths are covered so that (nonce ‖ ct ‖ aad) cannot be re-split a
        # different way to produce the same tag for different inputs — the
        # canonicalisation bug that makes otherwise-sound MACs forgeable.
        mac = hmac.new(mac_key, digestmod=hashlib.sha256)
        for part in (nonce, ciphertext, aad):
            mac.update(len(part).to_bytes(8, "big"))
            mac.update(part)
        return mac.digest()


class AesGcm:
    """`enc:v3` — AES-256-GCM from `cryptography`, when it is installed."""

    name = "aes-256-gcm"
    prefix = GCM_PREFIX

    def __init__(self) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aesgcm = AESGCM

    def seal(self, plaintext: bytes, key: bytes, aad: bytes) -> str:
        nonce = os.urandom(GCM_NONCE_BYTES)
        ciphertext = self._aesgcm(key).encrypt(nonce, plaintext, aad)
        return f"{self.prefix}{nonce.hex()}:{ciphertext.hex()}"

    def unseal(self, envelope: str, key: bytes, aad: bytes) -> bytes:
        try:
            _, _, nonce_hex, payload_hex = envelope.split(":", 3)
            nonce = bytes.fromhex(nonce_hex)
            ciphertext = bytes.fromhex(payload_hex)
        except ValueError as exc:
            raise IntegrityError(f"malformed v3 envelope: {exc}") from None
        try:
            return self._aesgcm(key).decrypt(nonce, ciphertext, aad)
        except Exception:  # InvalidTag, and anything else it raises
            raise IntegrityError(
                "content failed authentication (AES-GCM): the ciphertext, its "
                "nonce, or the memory it is bound to has been altered"
            ) from None


class LegacyKeystream:
    """`enc:v1` — read-only. Unauthenticated, so it is never written again.

    Kept because existing stores contain it and the alternative is unreadable
    history. A caller that decrypts one of these learns nothing about whether
    it was tampered with, which is why `Fabric` re-seals on revision and
    `doctor` reports how many remain.
    """

    name = "hmac-ctr (unauthenticated, legacy)"
    prefix = LEGACY_PREFIX

    def seal(self, plaintext: bytes, key: bytes, aad: bytes) -> str:
        raise IntegrityError(
            "enc:v1 is unauthenticated and read-only; new content is sealed "
            "with v2 or v3"
        )

    def unseal(self, envelope: str, key: bytes, aad: bytes) -> bytes:
        try:
            _, _, nonce_hex, payload_hex = envelope.split(":", 3)
            nonce = bytes.fromhex(nonce_hex)
            ciphertext = bytes.fromhex(payload_hex)
        except ValueError as exc:
            raise IntegrityError(f"malformed v1 envelope: {exc}") from None
        return bytes(
            a ^ b for a, b in zip(ciphertext, _keystream(key, nonce, len(ciphertext)))
        )


_INTERRUPTS = (KeyboardInterrupt, SystemExit, GeneratorExit)
_aead_state: tuple[bool, str] | None = None


def aead_status() -> tuple[bool, str]:
    """Whether AES-GCM can be used here, and if not, why.

    The reason is `"not installed"` when `cryptography` is absent, which is
    the zero-dependency default and is not a problem, or a description of the
    failure when it is installed and broken.

    A broken install does not always raise `ImportError`. A Debian
    `python3-cryptography` with no matching `_cffi_backend`, imported under
    another interpreter, raises `pyo3_runtime.PanicException`, which derives
    from `BaseException`. That escaped the old `except Exception`, so every
    write crashed. Anything but an interrupt now counts as "unavailable".

    Decided once per process and cached. Re-importing a module whose native
    half panicked can panic again, and the answer cannot change without a
    restart.
    """
    global _aead_state
    if _aead_state is None:
        _aead_state = _probe_aead()
        if not _aead_state[0] and _aead_state[1] != "not installed":
            warnings.warn(
                "the `cryptography` package is installed but cannot be used "
                f"({_aead_state[1]}); new content is sealed with "
                "encrypt-then-MAC (HMAC-SHA256) instead of AES-GCM, and "
                "existing AES-GCM content cannot be read on this host. Repair "
                "or reinstall `cryptography` for this interpreter.",
                RuntimeWarning, stacklevel=2,
            )
    return _aead_state


def _probe_aead() -> tuple[bool, str]:
    try:
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "cryptography":
            return False, "not installed"
        return False, f"installed but broken: {type(exc).__name__}: {exc}"
    except _INTERRUPTS:
        raise
    except BaseException as exc:  # noqa: BLE001 - see aead_status
        return False, f"installed but broken: {type(exc).__name__}: {exc}"
    try:
        AesGcm()
    except _INTERRUPTS:
        raise
    except BaseException as exc:  # noqa: BLE001 - see aead_status
        return False, f"installed but AES-GCM unusable: {type(exc).__name__}: {exc}"
    return True, "available"


def aead_available() -> bool:
    return aead_status()[0]


def _reset_aead_status() -> None:
    """For tests: forget the cached probe."""
    global _aead_state
    _aead_state = None


def default_suite() -> CipherSuite:
    """AES-GCM when `cryptography` works here, otherwise encrypt-then-MAC.

    Automatic rather than configurable: a deployment that installed a
    maintained cryptographic library should get the benefit without having to
    discover a setting, and one that did not must still get authenticated
    encryption rather than a warning it will not read.

    Falling back is never silent when the library is installed but broken:
    `aead_status` warns once and `memory-fabric doctor` names the reason.
    """
    return AesGcm() if aead_available() else EncryptThenMac()


_SUITES: dict[str, CipherSuite] = {
    LEGACY_PREFIX: LegacyKeystream(),
    ETM_PREFIX: EncryptThenMac(),
}


def suite_for(envelope: str) -> CipherSuite:
    """The suite that produced this ciphertext, by its version prefix."""
    if envelope.startswith(GCM_PREFIX):
        available, reason = aead_status()
        if not available:
            raise IntegrityError(
                "this content was sealed with AES-GCM (enc:v3) and "
                f"`cryptography` is {reason} here. Install or repair it, or "
                "read the store from a host that has it — refusing rather than "
                "returning anything, because a decryption failure must not "
                "look like erasure."
            )
        return AesGcm()  # pragma: no cover - depends on the environment
    for prefix, suite in _SUITES.items():
        if envelope.startswith(prefix):
            return suite
    raise IntegrityError(f"unknown content envelope: {envelope[:16]!r}")


def associated_data(store_id: str, memory_id: str, version: int) -> bytes:
    """What a ciphertext is bound to.

    A tag proves the bytes were not edited; this proves they are the bytes that
    belong *here*. Without it, sealed content could be copied from one memory
    to another, or an old version's ciphertext pasted over the current one to
    roll a memory back after a correction — both authentic, both wrong.
    """
    return b"\x1f".join(
        (
            b"memory-fabric/aad/v1",
            store_id.encode("utf-8"),
            memory_id.encode("utf-8"),
            str(int(version)).encode("ascii"),
        )
    )
