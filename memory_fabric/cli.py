"""Command-line interface.

Reads through `observability.report`, the same model the dashboard uses, so the
two surfaces cannot tell different stories about one store.

Read commands never write. The commands that do change something — `release`,
`forget`, `retention --apply` — say so and are never the default.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .fabric import MemoryFabric, NotFound, PolicyViolation
from .governance.cipher import default_suite, envelope_version
from .governance.erasure import (
    ERASED_MARKER,
    DirectoryKeyProvider,
    KeyUnavailable,
)
from .identity import DEFAULT_TENANT
from .model import (
    BLOCKED_STATES,
    SCHEMA_VERSION,
    WEAK_BASES,
    LifecycleState,
    WithdrawalBasis,
)
from .observability import report
from .observability.auth import ENV_TOKEN
from .outbox import MAX_ATTEMPTS
from .protocol import PropagationState

# --- terminal formatting ----------------------------------------------------

_NO_COLOUR = bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


class C:
    RESET = "" if _NO_COLOUR else "\033[0m"
    DIM = "" if _NO_COLOUR else "\033[2m"
    BOLD = "" if _NO_COLOUR else "\033[1m"
    RED = "" if _NO_COLOUR else "\033[31m"
    YELLOW = "" if _NO_COLOUR else "\033[33m"
    GREEN = "" if _NO_COLOUR else "\033[32m"
    BLUE = "" if _NO_COLOUR else "\033[34m"


class G:
    """Box-drawing glyphs, swapped for ASCII on consoles that cannot encode them.

    A Windows console defaults to a legacy code page (cp1252 here), where writing
    these characters raises UnicodeEncodeError and takes the whole command down.
    `configure_output` picks the set that the actual stream can carry.
    """

    RULE = "─"
    TEE = "├─ "
    ELBOW = "└─ "
    PIPE = "│  "
    BLANK = "   "
    BULLET = "·"
    ELLIPSIS = "…"


_ASCII_GLYPHS = {
    "RULE": "-",
    "TEE": "|- ",
    "ELBOW": "`- ",
    "PIPE": "|  ",
    "BLANK": "   ",
    "BULLET": "*",
    "ELLIPSIS": "...",
}

_PROBE = "─│└├…·"


def configure_output() -> None:
    """Make stdout able to carry the output, or fall back to ASCII.

    Tries UTF-8 first, since that fixes non-ASCII coming from the data as well as
    from the glyphs. Whatever the outcome, `errors="replace"` guarantees that an
    unencodable character degrades to a marker instead of raising.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass

    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        _PROBE.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        for name, glyph in _ASCII_GLYPHS.items():
            setattr(G, name, glyph)


_SEVERITY_COLOUR = {"high": C.RED, "medium": C.YELLOW, "low": C.BLUE}
_STATE_COLOUR = {
    "quarantined": C.RED,
    "deleted": C.RED,
    "contested": C.YELLOW,
    "active": C.GREEN,
    "candidate": C.DIM,
    "deprecated": C.DIM,
}


def width() -> int:
    return shutil.get_terminal_size((100, 24)).columns


def heading(text: str) -> None:
    print(f"\n{C.BOLD}{text}{C.RESET}")
    print(C.DIM + G.RULE * min(len(text), width()) + C.RESET)


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    keep = max(limit - len(G.ELLIPSIS), 0)
    return text[:keep].rstrip() + G.ELLIPSIS


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], right: Sequence[int] = ()) -> None:
    """Plain column layout that respects the terminal width."""
    if not rows:
        print(f"{C.DIM}(none){C.RESET}")
        return
    cols = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(_strip(row[i])))

    # Shrink the widest column until the table fits.
    available = width() - (cols - 1) * 2
    while sum(widths) > available and max(widths) > 8:
        widths[widths.index(max(widths))] -= 1

    def fmt(cells: Sequence[str], dim: bool) -> str:
        parts = []
        for i, cell in enumerate(cells):
            visible = _strip(cell)
            text = cell if len(visible) <= widths[i] else clip(visible, widths[i])
            pad = " " * max(widths[i] - len(_strip(text)), 0)
            parts.append(pad + text if i in right else text + pad)
        line = "  ".join(parts).rstrip()
        return f"{C.DIM}{line}{C.RESET}" if dim else line

    print(fmt(headers, dim=True))
    for row in rows:
        print(fmt(row, dim=False))


def _strip(text: str) -> str:
    """Length without ANSI escapes, so padding stays correct."""
    out, i = [], 0
    text = str(text)
    while i < len(text):
        if text[i] == "\033":
            while i < len(text) and text[i] != "m":
                i += 1
            i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def state_badge(state: str) -> str:
    return f"{_STATE_COLOUR.get(state, '')}{state}{C.RESET}"


def value_cell(row: dict[str, Any]) -> str:
    if row["value_mean"] is None:
        return f"{C.DIM}—{C.RESET}"
    mean = row["value_mean"]
    if not row["value_contrastive"]:
        # The asterisk marks a figure that cannot show benefit.
        return f"{C.DIM}{mean:+.2f}*{C.RESET}"
    colour = C.GREEN if mean > 0 else C.RED
    return f"{colour}{mean:+.2f}{C.RESET}"


# --- commands ---------------------------------------------------------------


def cmd_overview(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    data = report.overview(fabric)
    if args.json:
        print(json.dumps(report.jsonable(data.to_json()), indent=2, allow_nan=False))
        return 0

    heading("Store")
    table(
        ["", ""],
        [
            ["path", data.path],
            ["events", str(data.events)],
            ["memories", str(data.total_memories)],
            ["episodes", f"{data.episodes} ({data.episodes_with_outcome} with a verified outcome)"],
            ["exposures", f"{data.exposures} exposed / {data.withholdings} withheld"
             f" ({data.randomised_exposures} randomised)"],
            ["estimator", data.estimator],
            ["schema", f"{data.schema_version} installed"
             + (f", log written by {', '.join(data.log_schema_versions)}"
                if data.log_schema_versions != [data.schema_version] else "")],
            ["policies in log", ", ".join(data.logged_policies) or "none"],
            ["policy for new writes", f"{data.configured_policy}"
             f"{'' if data.configured_policy_declares_overlap else ' (deterministic)'}"],
            ["oldest", str(data.oldest_memory)],
            ["newest", str(data.newest_memory)],
        ],
    )

    heading("Memories")
    for label, counts in (
        ("state", data.by_state),
        ("scope", data.by_scope),
        ("type", data.by_type),
    ):
        pairs = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"
        print(f"  by {label:<6} {pairs}")
    print(f"  {'no value evidence':<21} {data.no_value_evidence}")
    print(f"  {'contrastive evidence':<21} {data.contrastive_evidence}")
    print(f"  {'with both arms':<21} {data.memories_with_both_arms}")
    print(f"  {'never exposed':<21} {data.never_exposed}")
    print(f"  {'open disagreements':<21} {data.open_hypothesis_sets}")

    if data.diagnostics:
        heading("What this store can and cannot tell you")
        for note in data.diagnostics:
            print(f"  {C.YELLOW}{G.BULLET}{C.RESET} {note}")
    return 0


def cmd_attention(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    items = report.attention(fabric)
    if args.severity:
        items = [i for i in items if i.severity == args.severity]
    if args.json:
        print(json.dumps(report.jsonable([i.to_json() for i in items]), indent=2, allow_nan=False))
        return 0

    if not items:
        print(f"{C.GREEN}Nothing needs attention.{C.RESET}")
        return 0

    heading(f"Needs attention ({len(items)})")
    for item in items:
        colour = _SEVERITY_COLOUR.get(item.severity, "")
        print(f"\n{colour}[{item.severity}]{C.RESET} {C.BOLD}{item.title}{C.RESET}")
        if item.memory_id:
            print(f"  {C.DIM}{item.memory_id}{C.RESET}")
        for line in item.detail.splitlines():
            print(f"  {line}")
        print(f"  {C.DIM}$ {item.action}{C.RESET}")
    # A non-zero exit lets this run as a health check in a script.
    return 1 if any(i.severity == "high" for i in items) else 0


def cmd_checkpoint(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Print or verify an integrity checkpoint.

    A checkpoint is `(seq, chain_digest)`: small enough to commit to another
    repository, write to append-only storage, paste into a ticket or read out
    loud. It is worth nothing stored beside the database — whoever could
    rewrite the chain could rewrite it too — and that is exactly why the
    command prints it rather than filing it somewhere for you.
    """
    chain = fabric.log.chain
    if args.verify:
        payload = json.loads(pathlib.Path(args.verify).read_text(encoding="utf-8"))
        from .integrity import Checkpoint

        result = chain.verify_against(Checkpoint.from_json(payload))
        if args.json:
            print(json.dumps(result.to_json(), indent=2))
        elif result.ok:
            print(f"{C.GREEN}{result.detail}{C.RESET}")
        else:
            print(f"{C.RED}{result.detail}{C.RESET}", file=sys.stderr)
        return 0 if result.ok else 5

    checkpoint = chain.checkpoint()
    verification = chain.verify(fabric.log.read())
    if args.json:
        print(json.dumps(
            {**checkpoint.to_json(), "verification": verification.to_json()},
            indent=2,
        ))
        return 0 if verification.ok else 5

    heading("Integrity checkpoint")
    table(
        ["", ""],
        [
            ["store", fabric.store_id],
            ["sequence", str(checkpoint.seq)],
            ["chain digest", checkpoint.chain_digest],
            ["chained events", str(checkpoint.events)],
            ["verified", "yes" if verification.ok else "NO"],
        ],
    )
    if verification.unchained_before:
        print(f"\n  {C.YELLOW}{G.BULLET}{C.RESET} {verification.unchained_before} "
              "event(s) predate the chain and are not covered.")
    print(f"\n  {C.DIM}Store this where the database cannot reach it. A chain "
          f"verifies against itself; only an external digest catches one "
          f"rewritten wholesale.{C.RESET}")
    return 0 if verification.ok else 5


def cmd_tenants(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Which tenants this store holds, and how many memories each has.

    The first question about a store someone inherited, and the one a store
    believed to be single-tenant can answer surprisingly. `doctor` reports the
    same fact as a warning; this prints it plainly.
    """
    counts = fabric.tenants()
    if args.json:
        print(json.dumps({"tenants": counts, "store_id": fabric.store_id}, indent=2))
        return 0
    heading(f"Tenants ({len(counts)})")
    if not counts:
        print("  no memories yet")
        return 0
    table(
        ["TENANT", "MEMORIES"],
        [[tenant, str(count)] for tenant, count in counts.items()],
    )
    if len(counts) > 1:
        print(
            f"\n  {C.YELLOW}{G.BULLET}{C.RESET} Several tenants in one store. The "
            "boundary is enforced on every read, but one file is one blast "
            "radius; prefer one store per tenant where the isolation has to "
            "survive a compromised process."
        )
    return 0


def cmd_list(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    rows = report.memory_rows(
        fabric,
        state=args.state,
        scope=args.scope,
        type=args.type,
        query=args.query,
        limit=args.limit,
        sort=args.sort,
        tenant=getattr(args, "tenant", None),
    )
    if args.json:
        print(json.dumps(report.jsonable([r.to_json() for r in rows]), indent=2, allow_nan=False))
        return 0

    heading(f"Memories ({len(rows)})")
    table(
        ["ID", "TYPE", "STATE", "SCOPE", "EXP", "WTH", "VALUE", "CONTENT"],
        [
            [
                row.id[:10],
                row.type[:10],
                state_badge(row.lifecycle_state),
                row.scope,
                str(row.exposures),
                str(row.withholdings),
                value_cell(row.to_json()),
                row.content,
            ]
            for row in rows
        ],
        right=(4, 5, 6),
    )
    return 0


def cmd_show(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    detail = report.memory_detail(fabric, args.id)
    if args.json:
        print(json.dumps(report.jsonable(detail), indent=2, allow_nan=False))
        return 0
    print(detail["narrative"])
    if detail["redacted_kinds"]:
        print(
            f"\n{C.YELLOW}Secrets redacted for display: "
            f"{', '.join(detail['redacted_kinds'])}.{C.RESET}\n"
            f"{C.DIM}The stored value is unchanged; it is simply not printed, so reviewing "
            f"this cannot leak it into a terminal scrollback.{C.RESET}"
        )
    return 0


def cmd_lineage(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    tree = report.lineage_tree(fabric, args.id, direction=args.direction, max_depth=args.depth)
    if args.json:
        print(json.dumps(report.jsonable(tree.to_json()), indent=2, allow_nan=False))
        return 0

    label = "Derived from" if args.direction == "ancestors" else "What depends on this"
    heading(f"{label}: {args.id}")
    if args.direction == "descendants" and tree.children:
        print(f"{C.DIM}Quarantining this memory would contest everything below.{C.RESET}\n")

    def walk(node: report.LineageNodeView, prefix: str, last: bool, root: bool) -> None:
        if root:
            print(f"{state_badge(node.lifecycle_state)}  {C.BOLD}{node.content}{C.RESET}")
            print(f"{C.DIM}{node.id}{C.RESET}")
        else:
            branch = G.ELBOW if last else G.TEE
            print(f"{prefix}{branch}{state_badge(node.lifecycle_state)}  {node.content}")
            print(f"{prefix}{G.BLANK if last else G.PIPE}{C.DIM}{node.id}{C.RESET}")
        child_prefix = "" if root else prefix + (G.BLANK if last else G.PIPE)
        for index, child in enumerate(node.children):
            walk(child, child_prefix, index == len(node.children) - 1, False)
        if node.truncated:
            print(f"{child_prefix}{C.DIM}{G.ELLIPSIS} depth limit reached{C.RESET}")

    walk(tree, "", True, True)
    if not tree.children:
        print(f"\n{C.DIM}(nothing){C.RESET}")
    return 0


def cmd_audit(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    events = report.memory_detail(fabric, args.id)["audit"]
    if args.json:
        print(json.dumps(report.jsonable(events), indent=2, allow_nan=False))
        return 0
    heading(f"Audit trail: {args.id}")
    rows = []
    for event in events:
        payload = {k: v for k, v in event["payload"].items() if k != "memory_id"}
        rows.append(
            [
                f"#{event['seq']}",
                str(event["ts"]),
                event["type"],
                clip(
                    " ".join(
                        f"{k}={json.dumps(v) if isinstance(v, (dict, list)) else v}"
                        for k, v in payload.items()
                    ),
                    200,
                ),
            ]
        )
    table(["SEQ", "WHEN", "EVENT", "DETAIL"], rows)
    return 0


def cmd_episodes(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    rows = report.episode_rows(fabric, limit=args.limit)
    if args.json:
        print(json.dumps(report.jsonable(rows), indent=2, allow_nan=False))
        return 0
    heading(f"Episodes ({len(rows)})")
    table(
        ["ID", "TASK", "AGENT", "EXP", "OUTCOME", "VERIFIER", "STARTED"],
        [
            [
                row["id"][:10],
                str(row["task_id"]),
                str(row["agent_id"]),
                str(row["exposures"]),
                f"{C.DIM}—{C.RESET}" if row["outcome"] is None else f"{row['outcome']:.2f}",
                row["verifier_id"] or f"{C.DIM}none{C.RESET}",
                str(row["started_at"] or ""),
            ]
            for row in rows
        ],
        right=(3, 4),
    )
    return 0


def cmd_search(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    hits = report.preview_search(fabric, args.query, k=args.limit, all_states=not args.retrievable)
    if args.json:
        print(json.dumps(report.jsonable([h.to_json() for h in hits]), indent=2, allow_nan=False))
        return 0
    heading(f"Index search: {args.query!r}")
    print(f"{C.DIM}Reads the index directly and logs nothing, so this cannot affect "
          f"any value estimate.{C.RESET}\n")
    table(
        ["SCORE", "STATE", "LIVE", "ID", "CONTENT"],
        [
            [
                f"{hit.relevance:.3f}",
                state_badge(hit.lifecycle_state),
                "yes" if hit.retrievable else f"{C.RED}no{C.RESET}",
                hit.id[:10],
                hit.content,
            ]
            for hit in hits
        ],
        right=(0,),
    )
    if not hits:
        print(f"{C.DIM}Nothing above the relevance floor.{C.RESET}")
    return 0


def cmd_retention(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    decisions = report.retention_preview(fabric)
    if args.json and not args.apply:
        print(json.dumps(report.jsonable(decisions), indent=2, allow_nan=False))
        return 0

    heading("Retention" + (" (applying)" if args.apply else " (dry run)"))
    table(
        ["ACTION", "ID", "REASON"],
        [[d["action"], d["memory_id"][:10], d["reason"]] for d in decisions],
    )
    if not decisions:
        return 0
    if args.apply:
        fabric.sweep_retention(apply=True)
        print(f"\n{C.YELLOW}Applied {len(decisions)} change(s).{C.RESET}")
    else:
        print(f"\n{C.DIM}Nothing changed. Re-run with --apply to act on these.{C.RESET}")
    return 0


def cmd_release(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    fabric.release(args.id, actor=args.actor, reason=args.reason)
    print(f"{args.id} released to candidate. Validate it to make it retrievable:")
    print(f"  {C.DIM}$ memory-fabric validate {args.id} --actor {args.actor}{C.RESET}")
    return 0


def cmd_validate(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    fabric.validate(args.id, actor=args.actor, reason=args.reason)
    print(f"{args.id} is now active.")
    return 0


def cmd_forget(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    fabric.forget(args.id, reason=args.reason, actor=args.actor)
    print(f"{args.id} deprecated. Retention deletes it later; nothing is destroyed now.")
    return 0


def cmd_quarantine(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    contested = fabric.quarantine(
        args.id, reason=args.reason, actor=args.actor,
        propagate=not args.no_propagate, basis=args.basis,
    )
    print(f"{args.id} quarantined.")
    if not args.basis:
        print(f"{C.YELLOW}No --basis given, so this is recorded as 'unstated' and "
              f"will show in `attention` as a withdrawal on weak evidence.{C.RESET}")
    if contested:
        print(f"{len(contested)} derived memory/ies contested, their justification retracted:")
        for memory_id in contested:
            print(f"  {memory_id}")
    elif args.no_propagate:
        print(f"{C.YELLOW}Descendants were left untouched (--no-propagate).{C.RESET}")
    return 0


def cmd_serve(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    from .observability.auth import ENV_TOKEN, InsecureConfiguration, build_config
    from .observability.server import serve

    try:
        config = build_config(
            bind_host=args.host,
            token=args.token or os.environ.get(ENV_TOKEN),
            no_auth=args.no_auth,
            allowed_hosts=args.allowed_host,
        )
    except InsecureConfiguration as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5

    serve(fabric, host=args.host, port=args.port, quiet=args.quiet, auth=config)
    return 0


def cmd_backup(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Consistent snapshot of the event log while the store is live.

    This exists because the alternative is telling an operator to use the
    `sqlite3` CLI, and a project that calls the event log its source of truth
    should not outsource the one operation that protects it. It also avoids the
    mistake `cp` makes: the store runs in WAL mode, so a plain file copy taken
    mid-write yields a database plus an uncommitted write-ahead log, and whether
    that restores depends on timing.

    The backup is verified by replaying it, because an openable file is not the
    same as a complete one — a truncated backup opens fine and reports fewer
    events, which nothing else would tell you.
    """
    import sqlite3

    # An in-memory store cannot be backed up by path. `--db :memory:` opens a
    # *fresh, empty* store, so without this the command copied its zero events,
    # compared zero against zero, and reported success — handing the operator a
    # verified-looking backup of nothing. A command whose only job is protecting
    # the event log must not do that. Found by the live validation, which asked
    # for a backup of an in-memory store and got a green tick.
    if fabric.log.path == ":memory:":
        print(f"{C.RED}This store is in memory, so there is nothing on disk to "
              f"copy and --db :memory: opens an empty one. Point --db at a file."
              f"{C.RESET}", file=sys.stderr)
        return 6

    target = Path(args.path)
    if target.exists() and not args.force:
        print(f"{C.RED}{target} exists. Pass --force to overwrite it.{C.RESET}",
              file=sys.stderr)
        return 4
    target.parent.mkdir(parents=True, exist_ok=True)

    source_events = len(fabric.log)
    destination = sqlite3.connect(target)
    try:
        fabric.log._conn.backup(destination)
        destination.commit()
    finally:
        # `with sqlite3.connect(...)` commits but does not close, which leaks
        # the handle. On Windows that leaves the file locked against the very
        # next operation, including the verification read below.
        destination.close()

    verifier = MemoryFabric(str(target))
    try:
        copied = len(verifier.log)
        memories = len(verifier.state.memories)
    finally:
        verifier.close()

    print(f"{fabric.log.path} -> {target}")
    print(f"  {copied} events, {memories} memories, replayed from the copy")
    if copied != source_events:
        print(f"{C.RED}Source had {source_events} events; the copy has {copied}. "
              f"Do not keep this backup.{C.RESET}", file=sys.stderr)
        return 5
    size = target.stat().st_size
    print(f"  {size / 1_000_000:.1f} MB")
    return 0


def cmd_demo(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Seed a store that exercises every panel, so the surfaces can be looked at."""
    from .demo import seed

    summary = seed(fabric)
    print(f"Seeded {summary['memories']} memories and {summary['episodes']} episodes "
          f"into {fabric.log.path}")
    print(f"\nTry:\n  {C.DIM}$ memory-fabric --db {fabric.log.path} attention{C.RESET}")
    print(f"  {C.DIM}$ memory-fabric --db {fabric.log.path} serve{C.RESET}")
    return 0


# --- doctor -----------------------------------------------------------------
#
# `attention` answers "what should a human look at in this knowledge base?".
# `doctor` answers a different question: "is this installation sound enough
# that the answers it gives can be believed?". The two were worth separating,
# because a store can be perfectly healthy and full of memories needing review,
# or hold nothing worth reviewing while its append-only triggers are missing.
#
# Every check here reports one of three things, and the distinction is the
# whole point of the command:
#
#   ok    — verified, not merely "no error raised"
#   warn  — a real condition that does not invalidate the store's answers
#   fail  — the store's answers cannot be relied on until this is fixed
#
# A check that cannot run reports `warn` with the reason, never `ok`.


@dataclass
class Finding:
    status: str  # "ok" | "warn" | "fail"
    name: str
    detail: str
    fix: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "name": self.name,
            "detail": self.detail,
            "fix": self.fix,
        }


def _check_append_only(fabric: MemoryFabric) -> Finding:
    """The triggers, not the intention.

    Append-only is enforced by two SQLite triggers. If a restore, a migration
    or a hand-edit dropped them, every other guarantee in the system becomes a
    convention — and nothing would raise, because the code never tries to
    update an event anyway.
    """
    rows = {
        row[0]
        for row in fabric.log._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    missing = {"events_no_update", "events_no_delete"} - rows
    if missing:
        return Finding(
            "fail",
            "append-only enforcement",
            f"missing trigger(s): {', '.join(sorted(missing))}. The event log can "
            "be rewritten, so nothing derived from it can be trusted.",
            "Restore from a verified backup: memory-fabric --db <path> backup <out>",
        )
    # Prove it rather than asserting it. Cheap, and the only form of this check
    # that distinguishes "triggers present" from "triggers working".
    #
    # Rolled back unconditionally. A probe that commits when it *succeeds* would
    # modify the event log of exactly the store it had just found unprotected,
    # which is the one store where that is unrecoverable — so the rollback is in
    # a `finally`, not on the success path.
    connection = fabric.log._conn
    probed_through = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE events SET ts = ts + 1 WHERE seq = 1")
        probed_through = True
    except sqlite3.DatabaseError:
        pass
    finally:
        connection.rollback()
    if probed_through:
        return Finding(
            "fail",
            "append-only enforcement",
            "an UPDATE against the event log succeeded (rolled back)",
            "Do not trust this store. Restore from a verified backup.",
        )
    return Finding(
        "ok", "append-only enforcement", "both triggers present and refusing writes"
    )


def _check_replay(fabric: MemoryFabric) -> Finding:
    """Rebuild the projections from the log and compare.

    AGENTS.md principle 3: memory records are *projections* of the log. If a
    rebuild disagrees with the live state, one of them is wrong and an operator
    has been reading the wrong one.
    """
    from .projections import Projection

    try:
        rebuilt = Projection.rebuild(fabric.log, unsealer=fabric._unseal_content)
    except Exception as exc:  # pragma: no cover - a replay failure is the finding
        return Finding(
            "fail", "replay from the log", f"the log does not replay: {exc}",
            "Report this with the store attached; a log that will not replay is a bug.",
        )
    live = fabric.state
    mismatches = []
    if set(rebuilt.state.memories) != set(live.memories):
        only_live = len(set(live.memories) - set(rebuilt.state.memories))
        only_replay = len(set(rebuilt.state.memories) - set(live.memories))
        mismatches.append(f"{only_live} memory/ies only in live state, {only_replay} only in replay")
    for memory_id in set(rebuilt.state.memories) & set(live.memories):
        if rebuilt.state.memories[memory_id].lifecycle_state is not live.memories[memory_id].lifecycle_state:
            mismatches.append(f"{memory_id} lifecycle differs")
    if mismatches:
        return Finding(
            "fail", "replay from the log",
            "; ".join(mismatches[:5]),
            "The live projection and the log disagree. The log is authoritative.",
        )
    return Finding(
        "ok", "replay from the log",
        f"{len(fabric.log)} event(s) replay to the same {len(live.memories)} memory/ies",
    )


def _check_schema(fabric: MemoryFabric) -> Finding:
    written = fabric.log.schema_versions()
    if not written:
        return Finding("warn", "schema version", "the log is empty, so nothing to compare")
    newer = [
        v for v in written
        if report._version(v) > report._version(SCHEMA_VERSION)
    ]
    if newer:
        return Finding(
            "fail", "schema version",
            f"written by {', '.join(newer)}, this install is {SCHEMA_VERSION}. "
            "Events it does not understand are being skipped silently.",
            "Upgrade: pip install -U memory-fabric",
        )
    older = [v for v in written if v != SCHEMA_VERSION]
    if older:
        return Finding(
            "ok", "schema version",
            f"{SCHEMA_VERSION} installed, log written by {', '.join(sorted(set(written)))} "
            "(older versions replay unchanged)",
        )
    return Finding("ok", "schema version", f"{SCHEMA_VERSION} throughout")


def _check_retractions(fabric: MemoryFabric) -> Finding:
    """The one guarantee the research supported is the one that can rot quietly.

    A retraction stuck retrying is not an error anywhere: the origin's own copy
    is withdrawn, the local store looks correct, and the recipient goes on
    exposing knowledge that was withdrawn hours ago. Nothing raises. This is
    the check that makes it visible.
    """
    # `pending()` is everything *not* in a terminal state, and FAILED is
    # terminal — so a permanent failure, the worst case here, never appears in
    # it. Found by the test that expected a failure and got a clean bill of
    # health. Queried directly instead.
    failed = fabric.log._conn.execute(
        "SELECT count(*) FROM outbox WHERE state = ?",
        (PropagationState.FAILED.value,),
    ).fetchone()[0]
    pending = fabric.outbox.pending()
    retrying = [row for row in pending if row.attempts > 0]
    if failed:
        return Finding(
            "fail", "retraction delivery",
            f"{failed} retraction(s) permanently failed; those recipients are "
            "still exposing withdrawn knowledge",
            "Check the route to each recipient, then re-run the dispatcher.",
        )
    if retrying:
        worst = max(row.attempts for row in retrying)
        return Finding(
            "warn", "retraction delivery",
            f"{len(retrying)} retraction(s) retrying (worst: {worst} attempt(s) of "
            f"{MAX_ATTEMPTS})",
            "Transient if a recipient is restarting; a route problem if it persists.",
        )
    if pending:
        return Finding(
            "ok", "retraction delivery",
            f"{len(pending)} queued, none failing",
        )
    return Finding("ok", "retraction delivery", "nothing outstanding")


def _check_weak_withdrawals(fabric: MemoryFabric) -> Finding:
    """PA′ measured this: of naive blame's 87 withdrawals, 57 were about a
    completely different fault. A withdrawal recorded on a weak basis is more
    likely to be a mistake than the memory is to be wrong, so it points at
    *releasing* the memory rather than at reviewing it."""
    weak = [
        memory_id
        for memory_id, basis in fabric.state.withdrawal_basis.items()
        if basis in {b.value for b in WEAK_BASES}
        and memory_id in fabric.state.memories
        and fabric.state.memories[memory_id].lifecycle_state is LifecycleState.QUARANTINED
    ]
    if not weak:
        return Finding("ok", "withdrawal evidence", "no memory is withdrawn on a weak basis")
    return Finding(
        "warn", "withdrawal evidence",
        f"{len(weak)} memory/ies withdrawn on co-occurrence or no stated basis",
        f"memory-fabric --db {fabric.log.path} attention",
    )


def _check_sealed_content(fabric: MemoryFabric) -> Finding:
    """A sealed memory whose key is gone reads as erased, which is correct. A
    sealed memory whose key is gone *and was not erased on purpose* is data
    loss, and the two are distinguishable only by whether a `ContentErased`
    event exists."""
    erased = set(fabric.state.erased)
    unreadable = []
    for memory_id in fabric.state.memories:
        try:
            content = fabric.state.memories[memory_id].content
        except Exception:  # pragma: no cover - the exception is the finding
            unreadable.append(memory_id)
            continue
        if content == ERASED_MARKER and memory_id not in erased:
            unreadable.append(memory_id)
    if unreadable:
        return Finding(
            "fail", "content keys",
            f"{len(unreadable)} memory/ies have unreadable content with no erasure "
            "event to explain it",
            "A key store was lost or replaced. Restore it, or record the erasure.",
        )
    if erased:
        return Finding(
            "ok", "content keys",
            f"{len(erased)} memory/ies erased on purpose; every other content readable",
        )
    return Finding("ok", "content keys", "all content readable")


def _check_blocked_not_exposed(fabric: MemoryFabric) -> Finding:
    """Invariant 1, checked against this store rather than in a test.

    The enforcement layer is one function and the tests cover it, but a store
    whose projections were rebuilt by an older version, or restored
    mid-migration, can hold a blocked memory that the exposure path still
    considers eligible. Cheap to verify directly.
    """
    leaked = [
        memory_id
        for memory_id, memory in fabric.state.memories.items()
        if memory.lifecycle_state in BLOCKED_STATES
        and fabric.enforcer.check(memory_id).usable
    ]
    if leaked:
        return Finding(
            "fail", "withdrawn knowledge is not exposed",
            f"{len(leaked)} blocked memory/ies pass the enforcement check: "
            f"{', '.join(leaked[:3])}",
            "Do not use this store for decisions. Report it with the store attached.",
        )
    blocked = sum(
        1 for m in fabric.state.memories.values() if m.lifecycle_state in BLOCKED_STATES
    )
    return Finding(
        "ok", "withdrawn knowledge is not exposed",
        f"{blocked} blocked memory/ies, none of them usable",
    )


def _check_event_chain(fabric: MemoryFabric) -> Finding:
    """Recompute the hash chain over the event log.

    This is the check two earlier security claims cited before the mechanism
    existed. The append-only triggers are a guard; once dropped, edited and
    recreated, nothing in the log disagrees with the edit. The chain does.

    Reports `ok` when the chain verifies, and prints the current checkpoint in
    the detail so an operator can copy it somewhere else.

    An earlier version warned *every* time, on the grounds that a chain alone
    is tamper-evident rather than tamper-proof and only an external checkpoint
    closes that. True — but a warning that can never be cleared is noise, and
    noise is what teaches an operator to stop reading warnings. The limitation
    belongs in the advice and in SECURITY.md, not in a permanent amber light.
    """
    chain = fabric.log.chain
    result = chain.verify(fabric.log.read())
    if not result.ok:
        return Finding(
            "fail", "event chain",
            f"{result.detail} (first bad sequence: {result.first_bad_seq})",
            "The event log has been modified. Restore from a verified backup "
            "and compare against an external checkpoint.",
        )
    if result.checked == 0:
        return Finding(
            "warn", "event chain",
            "no hash chain recorded, so nothing about this log's history is "
            "verifiable beyond the append-only triggers",
            "A store written before chaining existed. New events are chained "
            "from now on; there is deliberately no backfill, because hashing "
            "old events today proves only that they agree with themselves.",
        )
    checkpoint = chain.checkpoint()
    detail = (
        f"{result.checked} event(s) verified; checkpoint seq {checkpoint.seq} "
        f"{checkpoint.chain_digest[:16]}…"
    )
    if result.unchained_before:
        return Finding(
            "warn", "event chain",
            f"{detail}; {result.unchained_before} event(s) predate the chain "
            "and are not covered",
            "A store that adopted chaining late. There is deliberately no "
            "backfill: hashing old events today proves only that they agree "
            "with themselves.",
        )
    return Finding("ok", "event chain", detail)


def _check_content_cipher(fabric: MemoryFabric) -> Finding:
    """Which cipher generation this store's content is sealed with.

    `enc:v1` was an unauthenticated keystream: a ciphertext could be edited and
    the plaintext became whatever the editor chose, with nothing to detect it.
    It is still *readable* so existing stores work, and it is never written
    again — so the number remaining is a real operational figure and it only
    goes down, as memories are revised.

    Also reports where the keys live, because keys beside the ciphertext make
    erasure possible and do nothing against someone holding the file.
    """
    counts: dict[str, int] = {}
    for event in fabric.log.read():
        if event.type not in ("MemoryCreated", "MemoryVersioned"):
            continue
        content = (event.payload.get("memory") or {}).get("content")
        if not isinstance(content, str):
            continue
        version = envelope_version(content) or "plaintext"
        counts[version] = counts.get(version, 0) + 1

    custody = type(fabric.vault.keys).__name__
    where = (
        "in this database, beside the ciphertext"
        if custody == "SqliteKeyProvider"
        else f"externally ({custody})"
    )
    legacy = counts.get("v1", 0)
    summary = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))

    if legacy:
        return Finding(
            "warn", "content cipher",
            f"{legacy} content version(s) still sealed with the unauthenticated "
            f"enc:v1 keystream ({summary}); keys {where}",
            "v1 ciphertext can be edited undetectably. Revising a memory "
            "re-seals it; there is no bulk migration because rewriting the log "
            "is the one thing this design forbids.",
        )
    if not counts:
        return Finding("ok", "content cipher", f"no content yet; keys {where}")
    plaintext = counts.get("plaintext", 0)
    if plaintext and not fabric.encrypt_content:
        return Finding(
            "warn", "content cipher",
            f"encryption is off for this store: {plaintext} content version(s) "
            "in plaintext, so erasing a key would be cosmetic",
            "Open the store with encrypt_content=True for new writes.",
        )
    return Finding(
        "ok", "content cipher",
        f"authenticated ({default_suite().name}); {summary}; keys {where}",
    )


def _check_tenant_isolation(fabric: MemoryFabric) -> Finding:
    """Can any tenant's agent reach another tenant's memory?

    Driven against the store rather than asserted from the code, because the
    boundary is only as good as the data behind it: a memory created before
    tenancy existed, imported by a federation call that did not name a tenant,
    or restored from a mixed backup all end up labelled `tn_default`, and a
    store whose operator believes it is partitioned would then be serving one
    label to everyone.

    Reported as a *warning* when the store is multi-tenant and everything
    holds, not as `ok`: one SQLite file holding several tenants is one blast
    radius whatever the labels say, and an operator who thinks otherwise should
    read it here rather than in an incident. See `identity.py`.
    """
    counts = fabric.tenants()
    if len(counts) <= 1:
        only = next(iter(counts), DEFAULT_TENANT)
        return Finding(
            "ok", "tenant isolation",
            f"single-tenant store ({only}); nothing to cross",
        )

    leaks = []
    for memory_id, memory in fabric.state.memories.items():
        for tenant in counts:
            if tenant == memory.tenant_id:
                continue
            if fabric.enforcer.check(memory_id, tenant_id=tenant).usable:
                leaks.append(f"{memory_id} readable from {tenant}")
                break
    if leaks:
        return Finding(
            "fail", "tenant isolation",
            f"{len(leaks)} memory/ies readable from another tenant: {leaks[0]}",
            "Stop serving this store. Report it with the store attached.",
        )
    return Finding(
        "warn", "tenant isolation",
        f"{len(counts)} tenants in one store ({', '.join(f'{t}:{n}' for t, n in counts.items())}); "
        "the boundary holds, but one file is one blast radius",
        "Prefer one store per tenant where the isolation has to survive a "
        "compromised process. See DEPLOYMENT.md.",
    )


def _check_dashboard_asset(fabric: MemoryFabric) -> Finding:
    """A packaging failure that only shows up when someone opens the web UI.

    The dashboard is served from disk at runtime, so a wheel built without the
    `package-data` entry installs cleanly, passes every test, and 500s the
    first time an operator opens the page. Worth one line here.
    """
    from pathlib import Path as _Path

    from .observability import server as _server

    asset = _Path(_server.__file__).parent / "static" / "dashboard.html"
    if asset.exists():
        return Finding("ok", "dashboard asset", f"present ({asset.stat().st_size} bytes)")
    return Finding(
        "warn", "dashboard asset",
        "dashboard.html did not ship with this install; `serve` will fail",
        "Reinstall from a wheel built with the package-data entry.",
    )


DOCTOR_CHECKS = (
    _check_append_only,
    _check_event_chain,
    _check_replay,
    _check_schema,
    _check_retractions,
    _check_weak_withdrawals,
    _check_sealed_content,
    _check_content_cipher,
    _check_blocked_not_exposed,
    _check_tenant_isolation,
    _check_dashboard_asset,
)


def cmd_doctor(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Is this installation sound enough that its answers can be believed?

    Exit codes are meant for a health check in a script: 0 sound, 1 sound with
    warnings, 5 not sound.
    """
    findings: list[Finding] = []
    for check in DOCTOR_CHECKS:
        try:
            findings.append(check(fabric))
        except Exception as exc:
            # A check that cannot run is never reported as ok. The honest
            # outcome of "I could not tell" is a warning with the reason.
            findings.append(
                Finding("warn", getattr(check, "__name__", "check"),
                        f"this check could not run: {exc!r}")
            )

    failures = [f for f in findings if f.status == "fail"]
    warnings = [f for f in findings if f.status == "warn"]

    if args.json:
        print(json.dumps(
            {
                "store": str(fabric.log.path),
                "store_id": fabric.store_id,
                "schema_version": SCHEMA_VERSION,
                "python": platform.python_version(),
                "sound": not failures,
                "findings": [f.to_json() for f in findings],
            },
            indent=2, allow_nan=False,
        ))
        return 5 if failures else (1 if warnings else 0)

    heading("Doctor")
    print(f"  {C.DIM}{fabric.log.path}  ·  {fabric.store_id}  ·  "
          f"schema {SCHEMA_VERSION}  ·  Python {platform.python_version()}{C.RESET}\n")
    marks = {
        "ok": f"{C.GREEN}ok  {C.RESET}",
        "warn": f"{C.YELLOW}warn{C.RESET}",
        "fail": f"{C.RED}FAIL{C.RESET}",
    }
    for finding in findings:
        print(f"  [{marks[finding.status]}] {C.BOLD}{finding.name}{C.RESET}")
        print(f"         {finding.detail}")
        if finding.fix and finding.status != "ok":
            print(f"         {C.DIM}{G.BULLET} {finding.fix}{C.RESET}")

    print()
    if failures:
        print(f"  {C.RED}Not sound: {len(failures)} failing check(s).{C.RESET}")
        print(f"  {C.DIM}Answers from this store should not be used for decisions "
              f"until they are fixed.{C.RESET}")
        return 5
    if warnings:
        print(f"  {C.YELLOW}Sound, with {len(warnings)} warning(s).{C.RESET}")
        return 1
    print(f"  {C.GREEN}Sound. Every check verified, none skipped.{C.RESET}")
    return 0


# --- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-fabric",
        description="Inspect a Memory Fabric store. Read-only unless a command says otherwise.",
    )
    parser.add_argument(
        "--db", default="memory.db", help="path to the store (default: memory.db)"
    )
    parser.add_argument(
        "--estimator",
        default="naive_usage",
        help="value estimator for display: naive_usage (default) or ips",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of tables")
    parser.add_argument(
        "--keys",
        metavar="DIR",
        help="directory holding this store's content keys, when they are kept "
        "outside the database. Without it a store whose keys are external "
        "cannot be opened at all — which is the correct refusal, not a bug.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="create the store if it does not exist (otherwise a missing path is an error)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        sp.set_defaults(func=func)
        return sp

    add("overview", cmd_overview, "Store health and what it can and cannot tell you")
    add("tenants", cmd_tenants, "Which tenants this store holds")
    p = add("checkpoint", cmd_checkpoint,
            "Print an integrity checkpoint, or verify against a saved one")
    p.add_argument("--verify", metavar="FILE",
                   help="a checkpoint JSON file saved earlier, elsewhere")
    add("doctor", cmd_doctor,
        "Whether this installation's answers can be believed (exit 0/1/5)")

    p = add("attention", cmd_attention, "Triage list: what needs a human, worst first")
    p.add_argument("--severity", choices=["high", "medium", "low"])

    p = add("list", cmd_list, "List memories")
    p.add_argument("--state")
    p.add_argument("--scope")
    p.add_argument("--tenant", help="only memories belonging to this tenant")
    p.add_argument("--type")
    p.add_argument("-q", "--query", help="substring of content or id")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument(
        "--sort", choices=["created", "exposures", "value", "state"], default="created"
    )

    p = add("show", cmd_show, "Why the system remembers one memory")
    p.add_argument("id")

    p = add("lineage", cmd_lineage, "Derivation tree in either direction")
    p.add_argument("id")
    p.add_argument("--direction", choices=["descendants", "ancestors"], default="descendants")
    p.add_argument("--depth", type=int, default=6)

    p = add("audit", cmd_audit, "Every logged event that touched one memory")
    p.add_argument("id")

    p = add("episodes", cmd_episodes, "List episodes and their verified outcomes")
    p.add_argument("--limit", type=int, default=50)

    p = add("search", cmd_search, "Search the index without logging anything")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument(
        "--retrievable", action="store_true", help="only states an agent could actually receive"
    )

    p = add("retention", cmd_retention, "Preview retention; --apply to act on it")
    p.add_argument("--apply", action="store_true", help="WRITES: apply the decisions")

    p = add("validate", cmd_validate, "WRITES: promote a candidate to active")
    p.add_argument("id")
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", default="validated")

    p = add("release", cmd_release, "WRITES: return a quarantined memory to candidate")
    p.add_argument("id")
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", default="reviewed and released")

    p = add("forget", cmd_forget, "WRITES: deprecate a memory")
    p.add_argument("id")
    p.add_argument("--actor", default="operator")
    p.add_argument("--reason", required=True)

    p = add("quarantine", cmd_quarantine,
            "WRITES: quarantine a memory and contest its descendants. Quarantine on "
            "evidence about the memory, not on it having been in context at a failure "
            "- Phase A measured that policy making an agent much worse.")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", default="operator")
    p.add_argument(
        "--basis",
        choices=[b.value for b in WithdrawalBasis],
        help="what kind of evidence this rests on. Omitted is recorded as "
        "'unstated', which the attention list then flags - as it does "
        "'co_occurrence', because being present when something failed is "
        "agreement, not causation.",
    )
    p.add_argument(
        "--no-propagate",
        action="store_true",
        help="leave descendants alone (they keep a retracted justification)",
    )

    p = add("serve", cmd_serve, "Start the read-only web dashboard")
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default 127.0.0.1). Anything else needs authentication.",
    )
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--quiet", action="store_true", help="do not log requests")
    p.add_argument(
        "--token",
        help=f"fixed session token; a random one is generated if omitted. "
        f"Also read from ${ENV_TOKEN}, which keeps it out of the process list.",
    )
    p.add_argument(
        "--no-auth",
        action="store_true",
        help="serve without authentication; refused unless bound to loopback",
    )
    p.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="HOST",
        help="extra Host header value to accept; repeatable. Needed when reaching "
        "the server by a name or address other than localhost.",
    )

    p = add("backup", cmd_backup,
            "Consistent snapshot of the event log, verified by replaying it")
    p.add_argument("path", help="where to write the copy")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")

    add("demo", cmd_demo, "WRITES: seed a demonstration store")
    return parser


CREATING_COMMANDS = frozenset({"demo"})


def main(argv: Sequence[str] | None = None) -> int:
    # `mcp` is dispatched before anything else runs, and that ordering is the
    # whole point. On stdio, stdout *is* the protocol: one stray byte and the
    # host sees a parse failure and drops the server. `configure_output()`
    # adjusts console encoding and colour, and the shared parser and store
    # setup below were written for a human at a terminal. None of it may run
    # first, so the server gets a clean stream and owns its own arguments.
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "mcp":
        from .mcp.stdio import main as mcp_main

        return mcp_main(raw[1:])

    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    # Opening a store creates it, so a typo in --db would otherwise produce an
    # empty store and a confident report of nothing wrong. For an inspection
    # tool that is the worst possible failure: it looks like an answer.
    if (
        args.db != ":memory:"
        and args.command not in CREATING_COMMANDS
        and not args.create
        and not os.path.exists(args.db)
    ):
        print(
            f"{C.RED}no store at {args.db}{C.RESET}\n"
            f"{C.DIM}Check the path, or pass --create to start an empty one. "
            f"To populate a demo store: memory-fabric --db {args.db} demo{C.RESET}",
            file=sys.stderr,
        )
        return 2

    key_provider = None
    if args.keys:
        key_provider = DirectoryKeyProvider(args.keys)

    try:
        fabric = MemoryFabric(
            args.db, estimator=args.estimator, key_provider=key_provider
        )
    except KeyUnavailable as exc:
        # Distinguished from any other open failure, because the remedy is
        # specific and the default message would send someone looking at the
        # database instead of at the key store they did not mount.
        print(
            f"{C.RED}could not open {args.db}: {exc}{C.RESET}\n"
            f"{C.DIM}If this store's content keys are kept outside the "
            f"database, point at them with --keys <dir>.{C.RESET}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"{C.RED}could not open {args.db}: {exc}{C.RESET}", file=sys.stderr)
        return 2

    try:
        return args.func(fabric, args)
    except NotFound as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 3
    except PolicyViolation as exc:
        print(f"{C.RED}refused: {exc}{C.RESET}", file=sys.stderr)
        return 4
    except BrokenPipeError:  # piping into `head`
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        fabric.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
