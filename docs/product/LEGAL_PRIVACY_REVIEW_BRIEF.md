# Brief for legal and privacy review (blueprint §12.3, gap G10)

For counsel reviewing Memory Fabric before any compliance claim is made. It
states what the software does, with the code that does it, and the questions
that need a legal answer. **No compliance claim is made today**, and the
product says so (`docs/LIMITATIONS.md`; capability `compliance.certification`
is listed as unsupported).

## What the software does

1. **Append-only event log.** Every change is an event; nothing is edited or
   removed. Events are hash-chained for tamper evidence (`integrity.py`).
2. **Cryptographic erasure.** Each memory's content is encrypted with its own
   key; erasure destroys the key (`governance/erasure.py`,
   `Memory Fabric.erase_content`). The event remains, the text is unreadable.
   Indexes holding plaintext are cleared, and summaries written from an erased
   memory are erased with it (`decay.py`).
3. **What erasure does not reach**, reported per request by
   `Memory Fabric.erasure_scope`: backups taken before the erasure, copies
   already shared with other stores (each is sent a signed retraction and
   reports back; the origin cannot verify deletion there), exports, and
   anything a model was already given.
4. **Metadata that remains after erasure:** memory id, author id, timestamps,
   lifecycle events, and a record that erasure happened and why.
5. **Retention.** Policies retire memories by age and state
   (`governance/retention.py`); deletion is applied only when an operator
   enables it.
6. **Federation.** Stores on different machines exchange signed offers and
   retractions; each store decides independently.
7. **Audit export** writes decisions and access events **without content**
   (`posture.py`).

## Questions that need a legal answer

1. Does destroying a per-record key, leaving ciphertext and metadata in an
   immutable log, satisfy erasure obligations (e.g. GDPR Art. 17) in the
   jurisdictions you care about? Is the retained metadata itself personal data?
2. How long may pre-erasure backups be kept, and what must happen to them?
3. For memories shared with another organisation's store, who is controller
   and processor, and what does a retraction acknowledgement have to prove?
4. Agent memories may capture personal data incidentally ("the user's
   daughter starts school in May"). What lawful basis and notice apply, and
   should such writes be blocked, held for review, or allowed?
5. Is the hash chain an obstacle to rectification (Art. 16), given that a
   correction is a new version and the old one stays in history?
6. Cross-border transfer when stores federate across regions.
7. What may the product's documentation say about deletion without it being
   a misleading claim?

## How to verify the behaviour

```bash
python -m unittest tests.test_erasure tests.test_erasure_residue tests.test_decay
```

`tests/test_erasure_residue.py` checks that erased text cannot be found
through history, search, export or caches.
