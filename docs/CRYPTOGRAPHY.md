# Cryptography and key management: the decisions, for review

Every cryptographic decision in Memory Fabric, with where it lives and what
it is meant to guarantee. Written as a brief for an **independent
cryptographic review, which has not yet taken place**. Nothing here has been
reviewed by anyone outside the project.

## 1. Content encryption

| | |
|---|---|
| Purpose | Confidentiality of memory content at rest, and **crypto-erasure**: destroying a memory's key makes its content unrecoverable while the append-only log, lineage and audit trail stay intact |
| Key | One 256-bit key per memory, from `secrets.token_bytes(32)` (`governance/erasure.py`) |
| Production suite (`enc:v3`) | AES-256-GCM from the maintained `cryptography` library; 96-bit random nonce per seal (`os.urandom(12)`) |
| Production profile | `MEMORY_FABRIC_CRYPTO_PROFILE=production` (the Docker image's default): only `enc:v3` is written, and a store refuses to open if the library is missing or broken (`governance/cipher.py`, `require_profile`) |
| Compatible suite (`enc:v2`) | Used only outside the production profile, when `cryptography` is unavailable. An in-house composition of standard primitives: encryption and MAC subkeys by HKDF-Expand (SHA-256) from the memory key; HMAC-SHA256 in counter mode as the keystream (128-bit random nonce); encrypt-then-MAC with HMAC-SHA256 over nonce, ciphertext and AAD with their lengths; constant-time tag comparison before any decryption |
| Legacy (`enc:v1`) | Unauthenticated HMAC-CTR. Read-only, for stores written before `v2`; never written |
| Associated data | `store_id`, `memory_id` and `version`, so a ciphertext moved between memories, versions or stores fails authentication (no copy-paste or rollback of sealed content) |

**Questions for the reviewer.**
1. Random 96-bit GCM nonces: a key seals one memory's versions only, so the
   expected number of seals per key is small. Is per-key random nonce use
   acceptable here, or should nonces be derived (or the AES-GCM-SIV mode used)?
2. `enc:v2`: is the composition sound, and should it be removed from any
   release rather than kept as a zero-dependency fallback?
3. Are the AAD fields sufficient to prevent substitution between stores that
   share a key provider?

## 2. Key storage

| provider | where | protection |
|---|---|---|
| `DirectoryKeyProvider` (the default from `init`, and the Docker image) | One file per memory key in a directory **outside** the database | directory 0700, files 0600, written via a temporary file and renamed |
| `SqliteKeyProvider` (legacy) | In the database's `content_keys` table | none beyond the database file; `migrate-keys` moves keys out |

Erasure deletes the key material. **Not covered:** secure deletion on the
underlying medium (journaling or copy-on-write filesystems, SSD
wear-levelling, backups). Copies of the key directory in backups are the
operator's responsibility (`backup --with-keys` makes one explicitly).

## 3. Agent credentials

`identity.py`. A credential is the principal (agent, tenant, roles), issue
and expiry times and a key id, **signed with HMAC-SHA256** using the agent's
signing key, held by the service. Verified with `hmac.compare_digest` on
every operation. Revocation is per credential id, kept durably by
`MemoryService`. Bearer tokens: transport must be confidential (TLS).

## 4. Federation

`protocol.py`, `transport.py`. Each pair of stores shares a symmetric key.
Retractions, hostile-source notices and offers are **HMAC-SHA256 over a
canonical JSON encoding**, verified with the key of the store that sent the
message (for a forwarded retraction, the forwarder), named by key id.
Replay: retractions are deduplicated by campaign and target; offers are
idempotent at the recipient. Rotation uses an overlap window (`previous_keys`;
RUNBOOKS §3). **Not provided:** confidentiality on the wire (use TLS:
`--behind-tls`), or protection against a compromised peer that holds a valid
key.

## 5. Tamper evidence

`integrity.py`. Every event is digested with SHA-256 and chained (each link
hashes the previous chain digest with the event digest). Tampering with any
event breaks the chain. **An attacker who can write the database can
recompute the whole chain**; detection then depends on a checkpoint
`(seq, chain digest)` stored independently: the manager writes one per cycle
to `--checkpoint-dir`, and `memory-fabric checkpoint --verify <file>` checks
the store against it (`tests/test_checkpoint_rewrite.py`).

## 6. Randomness

`secrets` and `os.urandom` (the operating system's CSPRNG) for every key and
nonce. `random` is used only in experiments and simulations, always seeded.

## 7. What a review should also consider

- Side channels: the stdlib HMAC paths are not constant-time beyond the
  final comparison; content decryption happens in-process with the key in
  Python memory.
- There is no hardware key storage (HSM/KMS) integration; `KeyProvider` is
  the seam where one would plug in.
- Key rotation for **content** keys is by revision (a new version is sealed
  under the memory's key); there is no re-keying of a memory.
