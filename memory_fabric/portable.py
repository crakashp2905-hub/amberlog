"""Move a store between backends or machines with every tombstone intact (GOV-16).

`backup` copies a SQLite file and `restore` puts it back; neither moves a
store from SQLite to PostgreSQL, or into a fresh store elsewhere. This does,
by moving the thing everything else is built from: the event log.

    from memory_fabric.portable import export_events, import_events
    export_events(old, "store.events.jsonl")       # every event, as stored
    import_events(new, "store.events.jsonl")       # into an empty store; replays

Because withdrawals, erasures, corrections, copy links and tenancy are all
events, they all arrive: a withdrawn memory is still withdrawn, an erased one
is still erased, versions and lineage are unchanged. Content travels exactly as
it was stored, so **encrypted content stays encrypted**, and it is sealed to
the source store's identity and per-memory keys, which the file never carries:
`import_events` refuses an export holding encrypted content (move such a store
with `backup`/`restore` or the database's own tools). The destination keeps its
own store identity; the source's is reported as `imported_from`, so federation
peers never mistake the copy for the original. The file
ends with a manifest line carrying the event count and a SHA-256 over every
event line, and `import_events` refuses a file whose count or digest disagrees,
or a destination that is not empty.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

FORMAT = "mf-events/1"


def _line(event: Any) -> str:
    return json.dumps({"event_id": event.event_id, "ts": event.ts, "type": event.type,
                       "agent_id": event.agent_id, "episode_id": event.episode_id,
                       "schema_version": event.schema_version, "payload": event.payload},
                      sort_keys=True, separators=(",", ":"), default=str)


def export_events(fabric: "MemoryFabric", path: str | Path) -> dict[str, Any]:
    """Write every event in log order, then a manifest line. Returns the manifest."""
    digest = hashlib.sha256()
    count = 0
    with open(path, "w", encoding="utf-8") as out:
        for event in fabric.log.read():
            line = _line(event)
            digest.update(line.encode("utf-8") + b"\n")
            out.write(line + "\n")
            count += 1
        manifest = {"format": FORMAT, "events": count, "sha256": digest.hexdigest(),
                    "store_id": getattr(fabric, "store_id", None)}
        out.write(json.dumps({"manifest": manifest}, sort_keys=True) + "\n")
    return manifest


def import_events(fabric: "MemoryFabric", path: str | Path) -> dict[str, Any]:
    """Append an export's events to an empty store, then replay. Refuses a damaged file."""
    from .events import Event

    if any(e.type != "StoreIdentified" for e in fabric.log.read()):
        raise ValueError("the destination store is not empty; import into a new store")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("empty export")
    try:
        manifest = json.loads(lines[-1])["manifest"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("no manifest line: the export is truncated or not an export") from exc
    body = lines[:-1]
    digest = hashlib.sha256("".join(line + "\n" for line in body).encode("utf-8")).hexdigest()
    if manifest.get("format") != FORMAT or manifest.get("events") != len(body) or manifest.get("sha256") != digest:
        raise ValueError("the export's count or digest does not match its manifest")
    if any('"enc:v' in line for line in body):
        # Content is sealed to the source store's identity and per-memory keys,
        # which this file deliberately does not carry. Refuse before writing
        # anything rather than fail half-way through the replay.
        raise ValueError("the export holds encrypted content, sealed to the source store's identity "
                         "and keys; move that store with backup/restore (SQLite) or the database's "
                         "own tools (PostgreSQL)")
    events = []
    source_id = None
    for line in body:
        d = json.loads(line)
        if d["type"] == "StoreIdentified":
            # The destination keeps its own identity: it is a new store holding
            # the old one's history, and peers must not mistake it for the original.
            source_id = d["payload"].get("store_id")
            continue
        events.append(Event(type=d["type"], ts=d["ts"], payload=d["payload"], agent_id=d["agent_id"],
                            episode_id=d["episode_id"], event_id=d["event_id"],
                            schema_version=d["schema_version"]))
    fabric._emit(*events)
    fabric.rebuild()
    return {"imported": len(events), "imported_from": source_id, **manifest}
