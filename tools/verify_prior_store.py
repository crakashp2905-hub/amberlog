"""Verify pre-migration store identity, exact event bytes, decryption and chain.

The synthetic store and expected JSON must be captured before changing source.
This read-only check makes no event writes and does not edit the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from amberlog import Amberlog

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("expected", type=Path)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text())
    with Amberlog(str(args.database), recognise_copies=False) as fabric:
        rows = [tuple(row) for row in fabric.log._conn.execute("SELECT * FROM events ORDER BY seq")]
        checks = {
            "store_identity": fabric.store_id == expected["store_id"],
            "prior_content_decrypted": fabric.get(expected["memory_id"]).content == expected["plaintext"],
            "events_unchanged": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
                                == expected["events_sha256"],
            "hash_chain": fabric.log.chain.verify(fabric.log.read()).ok,
        }
    print(json.dumps(checks, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
