"""Command-line interface.

Reads through `observability.report`, the same model the dashboard uses, so the
two surfaces cannot tell different stories about one store.

Read commands never write. The commands that do change something — `release`,
`forget`, `retention --apply` — say so and are never the default.
"""

from __future__ import annotations

__stability__ = "stable"

import argparse
import json
import os
import subprocess
import time
import pathlib
import platform
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .fabric import MemoryFabric, NotFound, PolicyViolation
from .governance.cipher import aead_status, default_suite, envelope_version
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


def _shown(db: str) -> str:
    """The store argument as it may be displayed: a database URL loses its
    password. Every message that names the store goes through this, because
    the store argument is the one place a credential reaches the CLI."""
    from .pgcompat import is_postgres_url, redact

    return redact(db) if is_postgres_url(db) else db


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


def cmd_anchor(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Anchor the current checkpoint somewhere the store's writer cannot rewrite.

    A checkpoint only detects a rewritten log if it is kept beyond the reach
    of whoever can rewrite it (security review O3). This makes that one
    command, run from cron or a timer, to any mix of:

    * `dir:/path`: append to `<path>/<store_id>.anchors.jsonl` (other storage);
    * `git:/repo`: append there and commit (a repository the writer cannot push to);
    * `http(s)://...`: POST the checkpoint as JSON (an audit service or chat hook).

    `--verify PATH` checks the store against every anchor in a file or a
    `dir:` directory and names the first one that no longer holds.
    """
    import urllib.request

    from .integrity import Checkpoint

    chain = fabric.log.chain
    if args.verify:
        path = pathlib.Path(args.verify.removeprefix("dir:").removeprefix("git:"))
        if path.is_dir():
            path = path / f"{fabric.store_id}.anchors.jsonl"
        payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        mine = [p for p in payloads if p.get("store_id") in (None, fabric.store_id)]
        if not mine:
            print(f"no anchors for store {fabric.store_id} in {path}", file=sys.stderr)
            return 5
        for payload in mine:
            result = chain.verify_against(Checkpoint.from_json(payload))
            if not result.ok:
                print(f"{C.RED}anchor at seq {payload.get('seq')} no longer holds: "
                      f"{result.detail}{C.RESET}", file=sys.stderr)
                return 5
        print(f"{C.GREEN}{len(mine)} anchor(s) hold{C.RESET}")
        return 0

    if not args.to:
        print("give at least one --to dir:PATH | git:REPO | https://URL", file=sys.stderr)
        return 2
    record = {**chain.checkpoint().to_json(), "store_id": fabric.store_id,
              "anchored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    line = json.dumps(record, sort_keys=True)
    failed = 0
    for target in args.to:
        try:
            if target.startswith(("http://", "https://")):
                request = urllib.request.Request(target, data=line.encode(), method="POST",
                                                 headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    response.read()
            elif target.startswith(("dir:", "git:")):
                folder = pathlib.Path(target[4:])
                folder.mkdir(parents=True, exist_ok=True)
                name = f"{fabric.store_id}.anchors.jsonl"
                with open(folder / name, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                if target.startswith("git:"):
                    for cmd in (["add", name],
                                ["-c", "user.name=memory-fabric", "-c",
                                 "user.email=anchor@memory-fabric.invalid", "commit", "-q",
                                 "-m", f"anchor {fabric.store_id} seq {record.get('seq')}"]):
                        subprocess.run(["git", "-C", str(folder), *cmd], check=True,
                                       capture_output=True)
            else:
                raise ValueError(f"unknown anchor target {target!r}")
            print(f"anchored seq {record.get('seq')} to {target}")
        except Exception as exc:  # noqa: BLE001 - each target reports separately
            failed += 1
            print(f"{C.RED}anchor to {target} failed: {exc}{C.RESET}", file=sys.stderr)
    return 5 if failed else 0


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
        from .integrity import Checkpoint

        # One JSON object, or the manager's `<store>.checkpoint.jsonl` with a
        # line per cycle: every checkpoint in it must still hold, and the
        # first one that does not is reported.
        text = pathlib.Path(args.verify).read_text(encoding="utf-8").strip()
        lines = [line for line in text.splitlines() if line.strip()]
        payloads = ([json.loads(line) for line in lines] if len(lines) > 1
                    else [json.loads(text)])
        result = None
        for payload in payloads:
            result = chain.verify_against(Checkpoint.from_json(payload))
            if not result.ok:
                break
        assert result is not None
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
        agent=getattr(args, "agent", None),
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
    print()
    heading("Status")
    for label in detail["status"]:
        mark = {True: f"{C.GREEN}yes{C.RESET}", False: f"{C.YELLOW}no{C.RESET}",
                None: f"{C.DIM}n/a{C.RESET}"}[label["established"]]
        print(f"  {label['label']:<24} {mark}  {label['detail']}")
        print(f"  {'':<24} {C.DIM}does not establish: {label['does_not_mean']}{C.RESET}")
    r = detail["reach"]
    print()
    heading("Who can reach this")
    print(f"  may read       {r['may_read']}"
          + ("" if r["readable_now"] else f"  {C.YELLOW}(nobody now: {r['why_not']}){C.RESET}"))
    seen = ", ".join(f"{a} x{n}" for a, n in r["seen_by"].items()) or "nobody yet"
    print(f"  has seen it    {seen}")
    if r["refused"]:
        print(f"  refused        {', '.join(f'{a} x{n}' for a, n in r['refused'].items())}")
    stores = ", ".join(f"{s['store_id']} (as {s['imported_memory_id']})" for s in r["stores"])
    print(f"  other stores   {stores or 'none'}")
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


ENV_PEERS = "MEMORY_FABRIC_PEERS"
ENV_CHECKPOINT_DIR = "MEMORY_FABRIC_CHECKPOINT_DIR"


def _manager_for(fabric: MemoryFabric, args: argparse.Namespace):
    """A background manager configured from flags, then the environment."""
    from .manager import MemoryManager, load_peers
    from .transport import HttpTransport

    peers = getattr(args, "peers", None) or os.environ.get(ENV_PEERS)
    transport = HttpTransport(load_peers(peers), origin_store_id=fabric.store_id) if peers else None
    return MemoryManager(fabric, interval_s=getattr(args, "maintain_interval", 60.0),
                         transport=transport,
                         checkpoint_dir=getattr(args, "checkpoint_dir", None)
                         or os.environ.get(ENV_CHECKPOINT_DIR),
                         allow_delete=getattr(args, "retention_delete", False))


def _start_manager(fabric: MemoryFabric, args: argparse.Namespace):
    """Servers maintain their store unless told not to (`--no-maintain`)."""
    if getattr(args, "no_maintain", False):
        return None
    try:
        return _manager_for(fabric, args).start()
    except Exception as exc:  # noqa: BLE001 - a bad peer file must not stop the server
        print(f"{C.YELLOW}background manager not started: {exc}{C.RESET}", file=sys.stderr)
        return None


def cmd_maintain(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Run the background manager: once, continuously, or report its last cycle."""
    from .manager import findings, last_run

    if args.status:
        run = last_run(fabric)
        if run is None:
            print("no maintenance cycle has run on this store")
            return 1
        print(json.dumps({"last_cycle": run, "needs_a_person": findings(fabric)}, indent=2,
                         default=str))
        return 0
    manager = _manager_for(fabric, args)
    if args.once:
        report = manager.run_once()
        print(json.dumps({"leader": report.leader, "tasks": report.tasks}, indent=2, default=str))
        return 0
    print(f"maintaining {fabric.store_id} every {manager.interval_s:g}s as {manager.holder} "
          "(Ctrl-C to stop)", file=sys.stderr)
    manager.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        manager.stop()
    return 0


def _server_limits(fabric: MemoryFabric) -> None:
    """Servers meter writes: payload size, per-agent quota, per-peer import budget (`limits.py`)."""
    from .limits import SERVER_DEFAULTS, Meter

    fabric.limits = Meter(SERVER_DEFAULTS)


def cmd_serve(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    _server_limits(fabric)
    from .observability.auth import (
        ENV_TOKEN, InsecureConfiguration, build_config, load_operators,
    )
    from .observability.server import serve

    try:
        operators = load_operators(args.operators_file) if args.operators_file else None
        config = build_config(
            bind_host=args.host,
            token=args.token or os.environ.get(ENV_TOKEN),
            no_auth=args.no_auth,
            allowed_hosts=args.allowed_host,
            operators=operators,
        )
    except (InsecureConfiguration, OSError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5

    access_log = args.access_log
    if access_log is None and operators and args.db != ":memory:":
        # Named operators exist to make access attributable; recording it is
        # the point, so it is on unless explicitly turned off.
        # A database URL is not a path, and would carry its password into a
        # filename.
        from .pgcompat import is_postgres_url

        access_log = ("memory-fabric.access.jsonl" if is_postgres_url(args.db)
                      else f"{args.db}.access.jsonl")
    if access_log == "-":
        access_log = None

    manager = _start_manager(fabric, args)
    try:
        serve(fabric, host=args.host, port=args.port, quiet=args.quiet, auth=config,
              access_log=access_log)
    finally:
        if manager is not None:
            manager.stop()
    return 0


def cmd_mcp(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Serve this store to one agent over MCP on stdio.

    The identity is fixed for the life of the process, so a client configured
    for one agent cannot act as another by changing an argument. Stdout is the
    protocol stream; the one human-readable line goes to stderr.
    """
    _server_limits(fabric)
    from .adapters.mcp import McpServer, serve_stdio
    from .sdk import agent

    client = agent(fabric, args.agent, args.tenant)
    print(
        f"memory-fabric MCP server: agent {args.agent}, tenant {args.tenant}, "
        f"store {_shown(args.db)}",
        file=sys.stderr,
    )
    if args.trusted_local:
        print(
            "trusted-local: this agent's clean writes become active WITHOUT "
            "review and feed back into its own recall. Use only for a single "
            "user's local assistant, never for a shared or federated store.",
            file=sys.stderr,
        )
    manager = _start_manager(fabric, args)
    try:
        return serve_stdio(McpServer(client, fabric, trusted_local=args.trusted_local,
                                     extended=args.extended_tools))
    finally:
        # Stopped before the interpreter finalises: a manager thread inside a
        # SQLite call at exit crashed the process (CI, exit -11).
        if manager is not None:
            manager.stop()


def _print_scope(fabric: MemoryFabric, memory_id: str, as_json: bool) -> None:
    scope = fabric.erasure_scope(memory_id)
    if as_json:
        print(json.dumps(scope, indent=2, default=str))
        return
    heading(f"Erasure scope — {memory_id}")
    state = "ERASED" if scope["erased"] else "not erased"
    print(f"  {state}" + (f" ({scope['reason']})" if scope["reason"] else ""))
    print(f"  key custody: {scope['key_custody']}"
          + ("" if scope["provider_can_destroy"] else "  (provider CANNOT destroy keys)"))
    print("\n  Reached, verified:")
    for check, ok in scope["reached"].items():
        print(f"    {'yes' if ok else 'NO '}  {check.replace('_', ' ')}")
    print("\n  Kept deliberately:")
    for item in scope["kept_deliberately"]:
        print(f"    - {item}")
    print("\n  Outside this store — act on these separately:")
    outside = scope["outside_this_store"]
    print(f"    backups before erasure: {outside['backups_taken_before_erasure']}")
    print(f"    exports, logs, traces:  {outside['exports_logs_and_model_traces']}")
    print(f"    federated copies:       {outside['federated_copies']}")
    if outside["federated_copies"] != "none recorded":
        print(f"      {outside['federated_copies_note']}")


def cmd_erase(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Crypto-erase one memory's content, then report what that reached."""
    erased = fabric.erase_content(args.id, reason=args.reason, actor=args.actor)
    if not erased and not fabric.erasure_scope(args.id)["erased"]:
        print(f"{C.RED}{args.id} was not erased: the key provider could not "
              f"destroy its key{C.RESET}", file=sys.stderr)
        _print_scope(fabric, args.id, args.json)
        return 4
    _print_scope(fabric, args.id, args.json)
    return 0


def cmd_erasure_scope(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    _print_scope(fabric, args.id, args.json)
    return 0


def _agent_service(fabric: MemoryFabric, agents_file: str):
    from .agent_api import load_agents, register_all
    from .service import MemoryService

    service = MemoryService(fabric=fabric)
    register_all(service, load_agents(agents_file))
    return service


def cmd_agent_api(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Serve agents over authenticated HTTP. See `agent_api.py`."""
    _server_limits(fabric)
    from .agent_api import AgentApi, ConfigurationError, RateLimit, build_agent_server

    try:
        service = _agent_service(fabric, args.agents_file)
        limits = RateLimit(rate=args.rate_limit, burst=args.burst)
        server = build_agent_server(AgentApi(service, limits), host=args.host,
                                    port=args.port, behind_tls=args.behind_tls)
    except (ConfigurationError, OSError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5
    host, port = server.server_address[:2]
    if isinstance(host, bytes):  # AF_UNIX only; see transport.endpoint
        host = host.decode()
    print(f"Memory Fabric agent API on http://{host}:{port}/v1/  (store {_shown(args.db)})")
    print("  POST /v1/recall | fetch | verify | remember   with  Authorization: Bearer <credential>")
    print(f"  Issue a credential:  memory-fabric --db {_shown(args.db)} agent-api-issue "
          f"--agents-file {args.agents_file} --agent <id>")
    try:
        manager = _start_manager(fabric, args)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        if manager is not None:
            manager.stop()
        server.server_close()
    return 0


def cmd_federate(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Receive signed retractions and notices from peers, and deliver this store's to them.

    The federation endpoints (`/federation/retraction`, `/notice`,
    `/reconcile`) on their own port, apart from the read-only dashboard, plus
    the background manager for outbound delivery. Every message is
    HMAC-signed with the key in the peers file and replay-checked; a peer not
    in the file is refused. Messages carry ids, reasons and store ids, never
    memory content, but a bind beyond loopback still needs `--behind-tls` or
    an explicit `--allow-plain-http` for a private network.
    """
    _server_limits(fabric)
    from .manager import load_peers
    from .transport import build_federation_server

    peers_path = args.peers or os.environ.get(ENV_PEERS)
    if not peers_path:
        print(f"{C.RED}federate needs --peers (or ${ENV_PEERS}): the stores it may talk to"
              f"{C.RESET}", file=sys.stderr)
        return 2
    loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not (args.behind_tls or args.allow_plain_http):
        print(f"{C.RED}refusing to bind {args.host} over plain HTTP: pass --behind-tls when "
              f"TLS terminates in front, or --allow-plain-http on a private network{C.RESET}",
              file=sys.stderr)
        return 5
    registry = load_peers(peers_path)
    try:
        server = build_federation_server(fabric, registry, args.host, args.port)
    except OSError as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5
    host, port = server.server_address[:2]
    if isinstance(host, bytes):
        host = host.decode()
    print(f"Memory Fabric federation on http://{host}:{port}/federation/  "
          f"(store {fabric.store_id}, {len(registry)} peer(s))", flush=True)
    manager = None
    try:
        args.peers = peers_path
        manager = _start_manager(fabric, args)
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("stopped")
    finally:
        if manager is not None:
            manager.stop()
        server.server_close()
    return 0


def cmd_offer(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Offer one memory to a peer store over HTTP; it lands there as a candidate."""
    from .federation import offer_remote
    from .manager import load_peers
    from .transport import HttpTransport, TransportError

    peers_path = args.peers or os.environ.get(ENV_PEERS)
    if not peers_path:
        print(f"{C.RED}offer needs --peers (or ${ENV_PEERS}){C.RESET}", file=sys.stderr)
        return 2
    registry = load_peers(peers_path)
    if args.to not in registry:
        print(f"{C.RED}{args.to} is not in the peers file{C.RESET}", file=sys.stderr)
        return 2
    try:
        result = offer_remote(fabric, args.id, HttpTransport(registry, fabric.store_id),
                              args.to, recipient_agent=args.actor)
    except TransportError as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5
    if args.json:
        print(json.dumps({"accepted": result.accepted, "decision": result.decision.value,
                          "reasons": result.reasons,
                          "imported_memory_id": result.imported_memory_id}, indent=2))
    elif result.accepted:
        print(f"{C.GREEN}accepted{C.RESET} by {args.to} as candidate {result.imported_memory_id}")
    else:
        print(f"{C.YELLOW}refused{C.RESET}: " + "; ".join(result.reasons))
    return 0 if result.accepted else 1


def cmd_agent_api_issue(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Mint a signed, expiring credential for one agent in the agents file."""
    from .agent_api import ConfigurationError, encode_credential
    from .identity import IdentityError

    try:
        service = _agent_service(fabric, args.agents_file)
        credential = service.issue(args.agent, ttl_seconds=args.ttl)
    except (ConfigurationError, IdentityError, OSError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5
    print(encode_credential(credential))
    return 0


def cmd_incident(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Detect, assess, contain, record. See `response.py`."""
    from . import response

    db = _shown(args.db)
    if args.id is None:
        found = response.candidates(fabric)
        if args.json:
            print(json.dumps(found, indent=2))
            return 0
        heading(f"Possible incidents ({len(found)})")
        for c in found:
            print(f"  {c['memory_id']}  {'; '.join(c['why'])}")
        if found:
            print(f"\n{C.DIM}Assess one: memory-fabric --db {db} incident <id>{C.RESET}")
        return 0
    if args.id not in fabric.state.memories:
        print(f"{C.RED}no memory {args.id}{C.RESET}", file=sys.stderr)
        return 4
    if args.verify:
        result = response.verify_recovery(fabric, args.id)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"{args.id}: {result['status']}")
            for reason in result["unresolved"]:
                print(f"  unresolved: {reason}")
            for action in result["actions_to_review"]:
                print(f"  action to review: {action.get('tool')} (seq {action.get('seq')})")
            used = result["influence"]
            print(f"  exposed to {len(used['exposed_to'])} agent(s); relied on in "
                  f"{len(used['relied_on_in'])} episode(s); evidence for {len(used['actions'])} action(s)")
        return {"contained": 0, "contained, actions need review": 1}.get(result["status"], 3)
    if args.contain:
        if not args.reason or not args.actor:
            print(f"{C.RED}containing needs --reason and --actor{C.RESET}", file=sys.stderr)
            return 2
        result = response.contain(fabric, args.id, reason=args.reason, actor=args.actor)
        owed = ", ".join(result.get("owed_to") or []) or "no other store"
        print(f"contained {args.id}" + (" (already quarantined)" if result.get("already_quarantined")
                                         else f"; retraction owed to {owed}"))
        if result["review_next"]:
            print(f"Same author's other active memories, review next: "
                  f"{', '.join(result['review_next'])}")
        print(f"{C.DIM}Record it: memory-fabric --db {db} incident {args.id} --record incident.md{C.RESET}")
        return 0
    if args.record:
        data = response.record(fabric, args.id)
        out = Path(args.record)
        out.write_text(json.dumps(data, indent=2) if out.suffix == ".json"
                       else response.record_markdown(data), encoding="utf-8")
        print(f"wrote the incident record to {out} ({len(data['timeline'])} events, "
              f"{len(data['outstanding'])} delivery/ies outstanding)")
        return 0
    a = response.assess(fabric, args.id)
    if args.json:
        print(json.dumps(a, indent=2))
        return 0
    heading(f"Incident assessment: {args.id}")
    print(f"  content        {a['content']}")
    print(f"  author         {a['author']}   state {a['state']}")
    print(f"  author's other active memories  {len(a['author_other_active'])}")
    print(f"  seen by        {', '.join(f'{k} x{v}' for k, v in a['seen_by'].items()) or 'nobody'}")
    print(f"  other stores   {', '.join(s['store_id'] for s in a['stores']) or 'none'}")
    br = a["blast_radius"]
    print(f"  withdrawing it contests {len(br['would_contest'])}, "
          f"leaves {len(br['would_survive'])} standing on independent support")
    for act in a["actions_using_it"]:
        print(f"  action seq {act['seq']}: {act['tool']} by {act['agent']}, "
              f"{'allowed' if act['allowed'] else 'refused'}; necessary source: {act['necessary_source']}")
    print(f"\n{C.DIM}Contain: memory-fabric --db {db} incident {args.id} --contain "
          f"--reason WHY --actor YOU{C.RESET}")
    return 0


def cmd_lifecycle(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Retention rules, stale and sensitive finders, and deletion progress."""
    from .lifecycle import center

    data = center(fabric, stale_days=args.stale_days)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    rules = data["rules"]
    heading("Retention rules")
    print(f"  deprecated kept {rules['deprecated_grace_days']} days, quarantined "
          f"{rules['quarantine_grace_days']}, unreviewed candidates "
          f"{rules['unused_candidate_days']}; protected tags: {', '.join(rules['protected_tags'])}")
    print(f"  a sweep now would act on {len(rules['sweep_would'])} memory/ies "
          f"{C.DIM}(dry run){C.RESET}")

    def section(title: str, items: list[dict[str, Any]], label: str) -> None:
        print()
        heading(f"{title} ({len(items)})")
        for item in items[:args.limit]:
            print(f"  {item['memory_id']}  {item.get(label, '')}")
            print(f"  {C.DIM}{item['command']}{C.RESET}")
        if len(items) > args.limit:
            print(f"  {C.DIM}... {len(items) - args.limit} more (--json for all){C.RESET}")

    section(f"Not shown to anyone in {args.stale_days} days", data["stale"], "idle_days")
    section("Waiting too long for review", data["waiting_for_review"], "waiting_days")
    section("Secrets still readable", data["sensitive"]["readable_secrets"], "")
    section("Flagged by the current screens", data["sensitive"]["flagged_by_current_screens"],
            "finding")
    print()
    heading(f"Erased ({len(data['deletions']['erased'])})")
    for e in data["deletions"]["erased"][:args.limit]:
        print(f"  {e['memory_id']}  by {e['actor']}: {e['reason']}")
    props = data["deletions"]["propagation"]
    print()
    heading(f"Withdrawn memories other stores hold ({len(props)})")
    for p in props[:args.limit]:
        print(f"  {p['memory_id']}  confirmed {len(p['confirmed'])}/{len(p['stores'])}"
              + (f"; outstanding {', '.join(p['outstanding'])}" if p["outstanding"] else ""))
    return 0


def cmd_posture(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Which controls are on in this store, and the gaps no setting closes."""
    from .posture import posture

    data = posture(fabric)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    heading("Controls")
    colour = {"on": C.GREEN, "partial": C.YELLOW, "off": C.RED}
    for c in data["controls"]:
        print(f"  {colour[c['state']]}{c['state']:<8}{C.RESET}{c['name']}")
        print(f"  {'':<8}{C.DIM}{c['detail']}{C.RESET}")
    print()
    heading("Accepted gaps (docs/SECURITY_REVIEW.md)")
    for g in data["accepted_gaps"]:
        print(f"  {g['id']}  {g['gap']}" + (f"\n      {C.DIM}{g['mitigation']}{C.RESET}"
                                             if g["mitigation"] else ""))
    return 0


def cmd_receipt_verify(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Verify an action receipt's signature with a trusted public key. Needs no store."""
    import base64

    from .action_receipt import ReceiptInvalid, verify_receipt

    doc = json.loads(pathlib.Path(args.path).read_text(encoding="utf-8"))
    key = base64.b64decode(args.public_key) if args.public_key else None
    try:
        verify_receipt(doc, key)
    except ReceiptInvalid as exc:
        print(f"{C.RED}INVALID: {exc}{C.RESET}")
        return 5
    action, decision = doc["action"], doc["decision"]
    trust = "trusted key" if key else "embedded key only (integrity, not identity)"
    print(f"valid ({trust}): {action['agent_id']} -> {action['tool']}: "
          f"{'ALLOWED' if decision['allowed'] else 'REFUSED'} "
          f"({', '.join(decision['reason_codes'])}), {len(doc['evidence'])} evidence item(s), "
          f"log seq {doc['log']['seq']}")
    return 0


def cmd_access_log_verify(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Check the dashboard access log's hash chain. Exit 0 intact, 5 broken."""
    from .observability.server import verify_access_log

    ok, line, detail = verify_access_log(args.path)
    if args.json:
        print(json.dumps({"path": args.path, "intact": ok, "broken_at_line": line,
                          "detail": detail}))
    elif ok:
        print(f"{args.path}: {detail}")
    else:
        print(f"{args.path}: BROKEN at line {line}: {detail}")
    return 0 if ok else 5


def cmd_audit_export(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Write decisions, changes, access events and deletion receipts, without content."""
    from .posture import export_audit

    manifest = export_audit(fabric, args.out, kinds=args.kind or
                            ("decisions", "changes", "access", "deletions"),
                            since_seq=args.since_seq)
    print(f"wrote {manifest['events']} events to {args.out} "
          f"({', '.join(f'{k} {n}' for k, n in sorted(manifest['counts'].items())) or 'none'}); "
          f"content excluded; ends with a chain checkpoint")
    return 0


def cmd_import(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Import another store's export as reviewable candidates. See `migrate.py`."""
    from .migrate import import_records, read_records

    try:
        report = import_records(fabric, read_records(args.file), source=args.source,
                                default_agent=args.agent, tenant_id=args.tenant)
    except (OSError, ValueError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
        return 0
    print(f"imported {len(report.imported)} from {args.source} as candidates; "
          f"{len(report.quarantined)} quarantined by a screen, "
          f"{len(report.duplicates)} recognised as copies, {len(report.skipped)} skipped")
    for line in report.skipped[:20]:
        print(f"  {C.DIM}skipped {line}{C.RESET}")
    print(f"{C.DIM}Nothing imported is retrievable until reviewed: "
          f"memory-fabric --db {_shown(args.db)} review{C.RESET}")
    return 0


def cmd_import_docs(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Import a compiled document tree; withdraw sections a new version changed. See `docsource.py`."""
    from .docsource import import_document, read_document

    try:
        if args.format != "json":
            from . import knowledge_compiler as kc
            if not args.doc_id or not args.source_version:
                raise ValueError(f"{args.format} requires --doc-id and --source-version")
            ident = {"doc_id": args.doc_id, "version": args.source_version, "uri": args.source_uri or ""}
            if args.format == "docx":
                tree = kc.compile_docx(Path(args.file).read_bytes(), **ident)
            elif args.format == "csv":
                tree = kc.compile_csv(Path(args.file).read_text(encoding="utf-8"), key=args.key, **ident)
            else:
                compile_text = kc.compile_markdown if args.format == "markdown" else kc.compile_html
                tree = compile_text(Path(args.file).read_text(encoding="utf-8"), **ident)
        else:
            tree = read_document(args.file)
        report = import_document(fabric, tree, activate=args.activate,
                                 tenant_id=args.tenant)
    except (OSError, ValueError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
        return 0
    print(f"{report.doc_id} {report.version}: {len(report.added)} sections added, "
          f"{len(report.unchanged)} unchanged, {len(report.withdrawn)} withdrawn "
          f"(source document changed), {len(report.contested)} conclusions contested")
    return 0


def cmd_export_events(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Write the whole event log, with a verifying manifest. See `portable.py`."""
    from .portable import export_events

    manifest = export_events(fabric, args.out)
    print(json.dumps(manifest) if args.json else
          f"exported {manifest['events']} events to {args.out} (sha256 {manifest['sha256'][:16]}…); "
          "encrypted content stays encrypted: move its keys separately")
    return 0


def cmd_import_events(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Load an `export-events` file into an empty store and replay it."""
    from .portable import import_events

    try:
        result = import_events(fabric, args.file)
    except (OSError, ValueError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 4
    print(json.dumps(result) if args.json else
          f"imported {result['imported']} events from store {result['imported_from']}; replayed")
    return 0


def cmd_collection(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """List collections, or change one. Every change is an audited event."""
    from .fabric import PolicyViolation

    tenant = args.tenant
    try:
        if args.action == "list":
            data = fabric.collections(tenant_id=tenant)
            if args.json:
                print(json.dumps(data, indent=2))
                return 0
            heading(f"Collections ({len(data)})")
            for name, c in data.items():
                grants = "; ".join(f"{a}: {','.join(p)}" for a, p in c["grants"].items())
                print(f"  {name:<24} {len(c['members'])} memories   {grants or 'nobody attached'}")
            return 0
        if not args.name:
            print(f"{C.RED}name the collection{C.RESET}", file=sys.stderr)
            return 2
        if args.action in ("add", "remove"):
            if not args.memory:
                print(f"{C.RED}--memory is required{C.RESET}", file=sys.stderr)
                return 2
            (fabric.collection_add if args.action == "add" else fabric.collection_remove)(
                args.name, args.memory, actor=args.actor or "")
        elif args.action in ("attach", "grant"):
            perms = args.permission or ["read"]
            fabric.collection_grant(args.name, args.agent, perms, actor=args.actor or "",
                                    tenant_id=tenant or DEFAULT_TENANT)
        elif args.action in ("detach", "revoke"):
            fabric.collection_revoke(args.name, args.agent, actor=args.actor or "",
                                     permissions=args.permission or [],
                                     tenant_id=tenant or DEFAULT_TENANT)
    except (PolicyViolation, NotFound) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 4
    print(f"{args.action}: {args.name}")
    return 0


def cmd_correct(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Preview, apply, or follow the correction of one memory. See `correction.py`."""
    from . import correction

    if args.status:
        rows = correction.status(fabric, args.id)
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        heading(f"Retractions of {args.id}")
        if not rows:
            memory = fabric.state.memories.get(args.id)
            withdrawn = memory is not None and memory.lifecycle_state.value in (
                "quarantined", "deprecated", "deleted")
            print("  withdrawn here; no other store held it, so none was owed"
                  if withdrawn else "  none requested")
        for row in rows:
            print(f"  {row['store_id']:<30} {row['state']:<10} {row['detail']}")
        return 0
    if args.apply:
        if not args.reason:
            print(f"{C.RED}a correction needs --reason{C.RESET}", file=sys.stderr)
            return 2
        try:
            result = correction.apply(fabric, args.id, reason=args.reason,
                                      actor=args.actor or "", basis=args.basis,
                                      preview_digest=args.preview_digest)
        except correction.StalePreview as exc:
            print(f"{C.RED}{exc.code}: {exc}{C.RESET}", file=sys.stderr)
            return 5
        except (ValueError, KeyError) as exc:
            print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
            return 4
        owed = ", ".join(result["owed_to"]) or "no other store"
        print(f"withdrawn: {args.id}; retraction owed to {owed}")
        print(f"{C.DIM}Follow it: memory-fabric --db {_shown(args.db)} correct {args.id} --status{C.RESET}")
        return 0
    try:
        p = correction.preview(fabric, args.id)
    except KeyError:
        print(f"{C.RED}no memory {args.id}{C.RESET}", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(p.to_json(), indent=2))
        return 0
    heading(f"Withdrawing {args.id} would")
    print(f"  contest        {', '.join(p.would_contest) or 'nothing'}")
    print(f"  leave standing {', '.join(p.would_survive) or 'nothing'}"
          + (f"  {C.DIM}(independent support){C.RESET}" if p.would_survive else ""))
    print(f"  take copies    {', '.join(p.copies) or 'none'}")
    stores = ", ".join(s["store_id"] for s in p.stores)
    print(f"  owe stores     {stores or 'none'}")
    print(f"  preview        {p.digest[:16]}")
    print(f"\n{C.DIM}Apply: memory-fabric --db {_shown(args.db)} correct {args.id} --apply "
          f"--reason WHY --actor YOU --preview {p.digest[:16]}{C.RESET}")
    return 0


def _branch_error(exc: Exception) -> int:
    code = getattr(exc, "code", type(exc).__name__)
    print(f"{C.RED}{code}: {exc}{C.RESET}", file=sys.stderr)
    return 5 if code in ("STALE_PREVIEW", "HEAD_MOVED", "IDEMPOTENCY_CONFLICT") else 4


def cmd_branch(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Memory branches: list and inspect, or WRITES a one-change commit. See `branching.py`."""
    from .branching import BranchError, Branches

    b, tenant = Branches(fabric), args.tenant or DEFAULT_TENANT
    try:
        if args.action == "list":
            rows = [x.to_json() for x in b.list_branches(tenant_id=tenant)]
            if args.json:
                print(json.dumps(rows, indent=2))
                return 0
            heading(f"Branches ({len(rows)})")
            for r in rows:
                state = "closed" if r["closed"] else "open"
                print(f"  {r['name']:<24} {state:<7} {r['commits']} commits  owner {r['owner']}"
                      f"  base #{r['base_seq']}")
            return 0
        if not args.name:
            print(f"{C.RED}name the branch{C.RESET}", file=sys.stderr)
            return 2
        if args.action == "create":
            branch = b.create(args.name, owner=args.actor or "", tenant_id=tenant,
                              members=tuple(args.member or ()),
                              reviewers=tuple(args.reviewer or ()))
            print(json.dumps(branch.to_json(), indent=2) if args.json
                  else f"created {branch.name} at #{branch.base_seq}")
            return 0
        if args.action in ("show", "diff"):
            data = (b.history(args.name, tenant) if args.action == "show"
                    else b.diff(args.name, tenant))
            if args.json:
                print(json.dumps(data, indent=2))
                return 0
            heading(f"{args.name}: {args.action}")
            for row in data:
                if args.action == "show":
                    print(f"  {row['commit_id'][:14]}  {row['author']:<12} {row['message']}"
                          f"  ({len(row['changes'])} changes)")
                else:
                    print(f"  {row['op']:<9} {row.get('memory_id') or row.get('candidate_id')}"
                          f"  {row['commit_id'][:14]}")
            return 0
        if args.action == "close":
            n = b.close(args.name, actor=args.actor or "", tenant_id=tenant)
            print(f"closed {args.name}; {n} unmerged candidates deprecated")
            return 0
        message = args.message or args.action
        with b.commit(args.name, args.actor or "", message, tenant_id=tenant) as c:
            if args.action == "add":
                if not args.text:
                    raise BranchError("--text is required")
                c.add(args.text)
            elif args.action == "revise":
                if not (args.memory and args.text):
                    raise BranchError("--memory and --text are required")
                c.revise(args.memory, args.text)
            elif args.action == "withdraw":
                if not (args.memory and args.reason):
                    raise BranchError("--memory and --reason are required")
                c.withdraw(args.memory, args.reason)
        print(f"committed {b.get(args.name, tenant).head} on {args.name}")
        return 0
    except (BranchError, KeyError, ValueError) as exc:
        return _branch_error(exc)


def cmd_merge(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Preview a branch's merge into main; with --apply, WRITES what the preview allowed."""
    from .branching import BranchError, Branches

    b, tenant = Branches(fabric), args.tenant or DEFAULT_TENANT
    try:
        if args.action == "revert":
            out = b.revert(args.name, actor=args.actor or "", tenant_id=tenant)
            print(json.dumps(out, indent=2))
            return 0
        if args.action == "apply":
            if not (args.preview and args.key):
                print(f"{C.RED}--preview DIGEST and --key are required{C.RESET}", file=sys.stderr)
                return 2
            receipt = b.apply_merge(args.name, args.actor or "", args.preview, args.key,
                                    tenant_id=tenant)
            if args.json:
                print(json.dumps(receipt, indent=2))
                return 0
            print(f"merged {args.name}: {receipt['merge_id']}  "
                  + ", ".join(f"{k} {v}" for k, v in receipt["summary"].items() if v))
            return 0
        preview = b.preview_merge(args.name, args.actor or "", tenant_id=tenant)
        if args.json:
            print(json.dumps(preview.to_json(), indent=2))
            return 0
        heading(f"Merging {args.name} into main would")
        for ch in preview.changes:
            print(f"  {ch.decision:<18} {ch.op:<9} {ch.memory_id or ch.candidate_id}  "
                  f"{C.DIM}{ch.klass}: {ch.reason}{C.RESET}")
            for w in ch.warnings:
                print(f"  {'':<18} {C.YELLOW}{w}{C.RESET}")
        print(f"\n  preview {preview.digest[:16]}")
        print(f"{C.DIM}Apply: memory-fabric --db {_shown(args.db)} merge apply {args.name} "
              f"--actor YOU --preview {preview.digest} --key ONE-TIME-KEY{C.RESET}")
        return 0
    except (BranchError, KeyError, ValueError) as exc:
        return _branch_error(exc)


def _decay_command(fabric: MemoryFabric, args: argparse.Namespace, tenant: str) -> int:
    """The governed decay view (`decay.py`): wake, zoom, what needs a summary, submit one."""
    from .decay import DecayView, SummaryRejected

    if not args.agent:
        print(f"{C.RED}--agent is required{C.RESET}", file=sys.stderr)
        return 2
    view = DecayView(fabric, args.agent, tenant_id=tenant)
    try:
        if args.action == "pending":
            data: Any = view.pending(args.budget)
        elif args.action == "summarise":
            if not (args.node and args.text):
                print(f"{C.RED}--node LO-HI and --text are required{C.RESET}", file=sys.stderr)
                return 2
            lo, hi = map(int, args.node.split("-"))
            data = {"summary_id": view.submit(lo, hi, args.text)}
        else:
            if args.action == "zoom":
                if not args.node:
                    print(f"{C.RED}--node LO-HI is required{C.RESET}", file=sys.stderr)
                    return 2
                lo, hi = map(int, args.node.split("-"))
                pieces = view.zoom(lo, hi)
            else:
                pieces = view.wake(args.budget)
            if not args.json:
                print(view.render(pieces) or "(nothing readable)")
                return 0
            data = [p.to_json() for p in pieces]
    except SummaryRejected as exc:
        print(f"{C.RED}{exc.code}: {exc}{C.RESET}", file=sys.stderr)
        return 4
    except ValueError as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 2
    print(json.dumps(data, indent=2))
    return 0


def cmd_context(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Build a context bundle with its receipt (WRITES the receipt), or read receipts back."""
    from . import context_receipt as cr

    tenant = args.tenant or DEFAULT_TENANT
    if args.action in ("wake", "zoom", "pending", "summarise"):
        return _decay_command(fabric, args, tenant)
    if args.action == "build":
        if not (args.agent and args.query):
            print(f"{C.RED}--agent and --query are required{C.RESET}", file=sys.stderr)
            return 2
        bundle = cr.build_context(fabric, args.agent, args.query, budget=args.budget,
                                  mode=args.mode, tenant_id=tenant)
        if args.json:
            print(json.dumps({"text": bundle.text, "receipt": bundle.receipt}, indent=2))
            return 0
        print(bundle.text or "(nothing admissible to show)")
        r = bundle.receipt
        print(f"\n{C.DIM}receipt {r['receipt_id']}: {len(r['selected'])} selected, "
              f"{len(r['excluded'])} excluded, ~{r['tokens_estimated']}/{r['token_budget']} "
              f"tokens ({r['mode']}){C.RESET}")
        return 0
    if args.action == "receipts":
        rows = cr.receipts(fabric, tenant_id=tenant, agent_id=args.agent)
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        heading(f"Context receipts ({len(rows)})")
        for r in rows[-args.limit:]:
            print(f"  {r['receipt_id']}  {r['agent_id']:<12} {r['mode']:<14} "
                  f"{len(r['selected'])} selected  {len(r['excluded'])} excluded")
        return 0
    if not args.receipt:
        print(f"{C.RED}name the receipt{C.RESET}", file=sys.stderr)
        return 2
    try:
        data = cr.explain_receipt(fabric, args.receipt, tenant_id=tenant)
    except KeyError:
        print(f"{C.RED}no receipt {args.receipt} in {tenant}{C.RESET}", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    heading(f"Receipt {args.receipt}")
    for item in data["selected"]:
        state = "admissible now" if item["admissible_now"] else "; ".join(item["changes"])
        print(f"  {item['kind']:<8} {item['id']}  {state}")
    for item in data["excluded"]:
        print(f"  {C.DIM}excluded {item['id']}  {item['reason_code']}{C.RESET}")
    return 0


def cmd_suspicious(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """List memories that failed claim validation (`validation.py`). Read-only."""
    from .validation import SUSPICIOUS, review_queue, summary

    queue = review_queue(fabric)[: args.limit]
    if args.json:
        print(json.dumps([summary(a) for a in queue], indent=2))
        return 1 if queue else 0
    if not queue:
        print("No memory contradicts what the store knows.")
        return 0
    for a in queue:
        memory = fabric.get(a.memory_id)
        print(f"{C.YELLOW}{a.memory_id}{C.RESET}  {memory.lifecycle_state.value}  "
              f"by {memory.provenance.created_by}")
        print(f"  {memory.content[:160]}")
        for signal, evidence in a.signals.items():
            if signal in SUSPICIOUS:
                print(f"  {C.DIM}{signal}: {evidence}{C.RESET}")
    print()
    print(f"{len(queue)} to review. Approve one that is right with "
          f"`review <id> --approve --reason ...`; withdraw one that is wrong with "
          f"`correct <id> --apply --actor <you> --reason ...`.")
    return 1


def cmd_review(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """The review queue, or one decision on one memory. See `review.py`."""
    from .review import ReviewError, decide, queue

    decision = next((d for d in ("approve", "limit", "reject") if getattr(args, d)), None)
    if args.correct is not None:
        decision = "correct"
    if args.id is None:
        items = queue(fabric, tenant=args.tenant)
        if args.json:
            print(json.dumps([i.to_json() for i in items], indent=2))
            return 0
        heading(f"Waiting for review ({len(items)})")
        if not items:
            print("  nothing waiting")
            return 0
        table(["ID", "KIND", "AUTHOR", "CONTENT"],
              [[i.memory_id[:10], i.kind, i.author, i.content] for i in items])
        print(f"\n{C.DIM}Decide with: memory-fabric --db {_shown(args.db)} review <id> --actor <you> "
              f"--approve | --limit | --correct TEXT | --reject --reason WHY{C.RESET}")
        return 0
    if decision is None:
        print(f"{C.RED}choose --approve, --limit, --correct or --reject{C.RESET}", file=sys.stderr)
        return 2
    try:
        result = decide(fabric, args.id, decision, reviewer=args.actor or "",
                        reason=args.reason, correction=args.correct,
                        override_screen=args.override_screen)
    except ReviewError as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 4
    print(f"{decision}: {args.id} is now {result['state']}, scope {result['scope']}")
    if "note" in result:
        print(f"{C.YELLOW}{result['note']}{C.RESET}")
    return 0


def cmd_share(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Widen who may read memories, through the firewall, with every decision logged.

    Scope is enforced on reads: a private memory is visible only to the agent
    that wrote it. `--all-private-active` is the upgrade path for a store
    written before that, where every active memory was readable by the whole
    tenant: it shares each one to the given scope through the same firewall,
    so a restricted memory is still refused, and prints what it refused.
    """
    from .model import LifecycleState, Scope

    if args.all_private_active:
        targets = [m.id for m in fabric.state.memories.values()
                   if m.scope is Scope.PRIVATE and m.lifecycle_state is LifecycleState.ACTIVE]
    elif args.id:
        targets = [args.id]
    else:
        print(f"{C.RED}name a memory id, or pass --all-private-active{C.RESET}", file=sys.stderr)
        return 2
    shared = refused = 0
    for memory_id in targets:
        ruling = fabric.share(memory_id, args.scope, actor=args.actor)
        if ruling.permits_sharing:
            shared += 1
        else:
            refused += 1
            print(f"{C.YELLOW}refused{C.RESET} {memory_id}: {'; '.join(ruling.reasons)}")
    print(f"shared {shared} to {args.scope}; refused {refused}")
    return 0 if refused == 0 or args.all_private_active else 4


def cmd_agent_api_revoke(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Revoke one leaked credential, or every credential an agent holds.

    Revocations are rows in the store, so a running `agent-api` server on the
    same store refuses the credential on its next request; nothing restarts.
    A token is read from stdin when given as `-`, so it does not land in
    shell history.
    """
    from .agent_api import ConfigurationError, decode_credential
    from .identity import IdentityError

    try:
        service = _agent_service(fabric, args.agents_file)
        if not service.revocations_are_durable:  # pragma: no cover - default is durable
            print(f"{C.RED}revocations here would not survive a restart; refusing{C.RESET}",
                  file=sys.stderr)
            return 5
        if args.agent:
            service.revoke_agent(args.agent)
            print(f"revoked every credential of {args.agent}")
            return 0
        token = sys.stdin.read().strip() if args.token == "-" else args.token
        credential = decode_credential(token)
        service.revoke(credential)
        print(f"revoked credential {credential.credential_id} of {credential.agent_id}")
        return 0
    except (ConfigurationError, IdentityError, OSError, ValueError) as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 5


def cmd_migrate_keys(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Move this store's content keys out of the database into a directory.

    Copy, then prove a full replay with only the directory reads every memory,
    then clear the material from the database. If the proof fails nothing is
    cleared, so the store is never left unreadable.
    """
    from .governance.erasure import (
        DirectoryKeyProvider, SqliteKeyProvider, clear_database_keys,
        copy_keys_to_directory,
    )

    if args.db == ":memory:":
        print(f"{C.RED}an in-memory store has no file to protect{C.RESET}", file=sys.stderr)
        return 2
    if not isinstance(fabric.vault.keys, SqliteKeyProvider):
        print(f"{C.RED}this store was opened with external keys already; "
              f"run without --keys / MEMORY_FABRIC_KEYS to migrate it{C.RESET}",
              file=sys.stderr)
        return 2
    try:
        copied = copy_keys_to_directory(fabric.log._conn, args.directory)
    except ValueError as exc:
        print(f"{C.RED}{exc}{C.RESET}", file=sys.stderr)
        return 4
    events, memories = len(fabric.log), len(fabric.state.memories)
    fabric.close()

    try:
        proof = MemoryFabric(args.db, key_provider=DirectoryKeyProvider(args.directory))
    except Exception as exc:  # noqa: BLE001 - any failure means do not clear
        print(f"{C.RED}verification failed, database keys left in place: {exc}{C.RESET}",
              file=sys.stderr)
        return 5
    try:
        if len(proof.log) != events or len(proof.state.memories) != memories:
            print(f"{C.RED}verification replay disagreed with the source; "
                  f"database keys left in place{C.RESET}", file=sys.stderr)
            return 5
        cleared = clear_database_keys(proof.log._conn)
    finally:
        proof.close()

    print(f"copied {len(copied)} key(s) to {args.directory}; replay with the "
          f"directory alone read all {memories} memories")
    print(f"cleared {cleared} key(s) from the database. From now on open this "
          f"store with --keys {args.directory} (or MEMORY_FABRIC_KEYS), and back "
          f"the key directory up separately from the database.")
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

    if getattr(fabric.log, "dialect", "sqlite") == "postgresql":
        print(f"{C.RED}A PostgreSQL store is backed up with the database's own "
              f"tools, which are consistent and incremental where this copy is "
              f"not:\n  pg_dump --format=custom --file=<out> <database>{C.RESET}",
              file=sys.stderr)
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

    # The replay needs the same keys as the source, or every sealed memory
    # reads as missing. The in-database provider is bound to the source's
    # connection, so the copy must use its own; any external provider is
    # shared as-is. Without this, backup crashed on every store whose keys are
    # outside the database -- the custody recommended for production.
    from .governance.erasure import SqliteKeyProvider

    external = not isinstance(fabric.vault.keys, SqliteKeyProvider)
    try:
        verifier = MemoryFabric(
            str(target), key_provider=fabric.vault.keys if external else None)
    except KeyUnavailable as exc:
        print(f"{C.RED}The copy could not be read back: {exc}. "
              f"Do not keep this backup.{C.RESET}", file=sys.stderr)
        return 5
    try:
        copied = len(verifier.log)
        memories = len(verifier.state.memories)
    finally:
        verifier.close()

    print(f"{fabric.log.path} -> {target}")
    print(f"  {copied} events, {memories} memories, replayed from the copy")
    if external:
        print(f"  {C.YELLOW}This store's content keys are outside the database, "
              f"so this backup holds none of them. Back up the key directory "
              f"too, separately -- without it the backup's content cannot be "
              f"read.{C.RESET}")
    if copied != source_events:
        print(f"{C.RED}Source had {source_events} events; the copy has {copied}. "
              f"Do not keep this backup.{C.RESET}", file=sys.stderr)
        return 5
    size = target.stat().st_size
    print(f"  {size / 1_000_000:.1f} MB")
    _backup_custody(fabric, args, target, copied)
    return 0


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_custody(fabric: MemoryFabric, args: argparse.Namespace, target: Path,
                    events: int) -> None:
    """Keys and config beside the copy, and a manifest of every file's hash.

    The manifest is what `restore` checks first: a backup whose files do not
    match it is refused, so a truncated or edited copy is found at restore
    time rather than after an operator relies on it.
    """
    import shutil

    files: dict[str, str] = {target.name: _sha256(target)}
    if getattr(args, "with_keys", False):
        if not args.keys:
            print(f"{C.YELLOW}--with-keys needs --keys DIR (the key directory); "
                  f"none was given, so no keys were copied.{C.RESET}", file=sys.stderr)
        else:
            keys = target.with_name(target.name + ".keys")
            shutil.copytree(args.keys, keys, dirs_exist_ok=bool(args.force))
            for f in sorted(keys.rglob("*")):
                if f.is_file():
                    files[str(f.relative_to(target.parent)).replace("\\", "/")] = _sha256(f)
            print(f"  keys copied to {keys}")
    for include in getattr(args, "include", []) or []:
        source = Path(include)
        config = target.with_name(target.name + ".config")
        config.mkdir(exist_ok=True)
        dest = config / source.name
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(source, dest)
        for f in sorted([dest] if dest.is_file() else dest.rglob("*")):
            if f.is_file():
                files[str(f.relative_to(target.parent)).replace("\\", "/")] = _sha256(f)
    head_seq, head = fabric.log.chain.head()
    manifest = {"format": "memory-fabric-backup-v1", "store_id": fabric.store_id,
                "events": events, "chain_head": {"seq": head_seq, "digest": head},
                "schema_version": SCHEMA_VERSION, "files": files}
    target.with_name(target.name + ".manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  manifest {target.name}.manifest.json ({len(files)} file(s))")


def cmd_restore(fabric: MemoryFabric | None, args: argparse.Namespace) -> int:
    """Restore a backup into a new directory, refusing one that does not match its manifest."""
    import shutil

    backup = Path(args.backup)
    manifest_path = backup.with_name(backup.name + ".manifest.json")
    if not manifest_path.exists():
        print(f"{C.RED}no manifest at {manifest_path}; back up again with this "
              f"version to get one{C.RESET}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bad = [name for name, digest in manifest["files"].items()
           if not (backup.parent / name).is_file()
           or _sha256(backup.parent / name) != digest]
    if bad:
        print(f"{C.RED}the backup does not match its manifest: {', '.join(bad[:5])}. "
              f"Do not restore it.{C.RESET}", file=sys.stderr)
        return 5
    dest = Path(args.dest)
    if dest.exists():
        print(f"{C.RED}{dest} exists; restore into a new directory{C.RESET}", file=sys.stderr)
        return 4
    dest.mkdir(parents=True)
    shutil.copy2(backup, dest / "store.db")
    keys_src = backup.with_name(backup.name + ".keys")
    keys = dest / "keys" if keys_src.is_dir() else None
    if keys is not None:
        shutil.copytree(keys_src, keys)
    config_src = backup.with_name(backup.name + ".config")
    if config_src.is_dir():
        shutil.copytree(config_src, dest / "config")
    restored = MemoryFabric(str(dest / "store.db"),
                            key_provider=DirectoryKeyProvider(str(keys)) if keys else None)
    try:
        events = len(restored.log)
        head = list(restored.log.chain.head())
        memories = len(restored.state.memories)
        verification = restored.log.chain.verify(restored.log.read())
    finally:
        restored.close()
    if events != manifest["events"] or head != [manifest["chain_head"]["seq"],
                                                manifest["chain_head"]["digest"]]:
        print(f"{C.RED}restored {events} events, head {head}; the manifest says "
              f"{manifest['events']} and {manifest['chain_head']}{C.RESET}", file=sys.stderr)
        return 5
    ok = getattr(verification, "ok", True)
    print(f"restored {events} events, {memories} memories into {dest}; chain head matches"
          f"{'' if ok else '; CHAIN DOES NOT VERIFY'}")
    if keys is None:
        print(f"  {C.YELLOW}no keys in this backup: if the store's keys were external, "
              f"its content cannot be read until they are restored.{C.RESET}")
    return 0 if ok else 5


def cmd_pilot_report(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """A shareable pilot report (`pilot.py`): counts and durations, never content."""
    from .pilot import readiness, report

    rep = report(fabric, names=args.names)
    if not args.check:
        print(json.dumps(rep, indent=2))
        return 0
    heading("Is this pilot ready to send?")
    checks = readiness(rep)
    for ok, line in checks:
        mark = f"{C.GREEN}ok{C.RESET}  " if ok else f"{C.YELLOW}not yet{C.RESET}"
        print(f"  {mark}  {line}")
    ready = all(ok for ok, _ in checks)
    print(f"\n  {'Ready: run pilot-report > pilot-report.json and send that file.' if ready else 'Keep going; the report is still valid, just thin.'}")
    return 0 if ready else 1


def cmd_connect(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """The setup for one agent tool (`connect.py`), printed or written."""
    from .connect import TARGETS, snippet, write

    if args.list or not args.tool:
        heading("Connect an agent")
        table(["tool", "what"], [[t.name, t.title] for t in TARGETS.values()])
        print("\n  memory-fabric --db <store> connect <tool> --agent <id> [--write]")
        return 0
    if args.tool not in TARGETS:
        print(f"unknown tool {args.tool!r}; one of: {', '.join(TARGETS)}", file=sys.stderr)
        return 2
    agent = args.agent or args.tool
    keys = getattr(args, "keys", None)
    if args.write:
        try:
            path = write(args.tool, args.db, agent, keys, args.trusted_local)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"{TARGETS[args.tool].title}: added memory-fabric to {path} (agent {agent}). "
              "Restart the tool to load it.")
        return 0
    s = snippet(args.tool, args.db, agent, keys, args.trusted_local)
    where = f" in {s['path']}" if s["path"] else ""
    print(f"# {s['title']}: agent id {agent!r}{where}")
    if s["note"]:
        print(f"# {s['note']}")
    print(s["text"])
    return 0


def cmd_models(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """Bring your own model (`models.py`): what is ready, and a one-call test."""
    import os

    from .models import ENV_MODEL, ModelClient, ModelError, configured

    if args.test:
        try:
            done = ModelClient(args.test).complete("Reply with the single word: ready",
                                                   max_tokens=8)
        except (ModelError, ValueError) as exc:
            print(f"{args.test}: not working: {exc}")
            return 1
        cost = "unknown cost" if done.cost_usd is None else f"${done.cost_usd:.6f}"
        print(f"{args.test}: ok in {done.seconds:.1f}s, {done.input_tokens} in / "
              f"{done.output_tokens} out tokens, {cost}: {done.text.strip()[:40]!r}")
        return 0
    if args.json:
        print(json.dumps({"default": os.environ.get(ENV_MODEL), "providers": configured()},
                         indent=2))
        return 0
    heading("Models")
    print(f"  default ({ENV_MODEL}): {os.environ.get(ENV_MODEL) or 'not set'}\n")
    table(["provider", "ready", "needs"],
          [[r["provider"], "yes" if r["ready"] else "-", r["needs"]] for r in configured()])
    print("\n  Pick one: export MEMORY_FABRIC_MODEL=anthropic:claude-opus-5-5  "
          "(or openai:..., ollama:..., compat:<model>@<url>)")
    print("  Check it: memory-fabric models --test anthropic:claude-opus-5-5")
    return 0


def cmd_tour(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """One fact, four agents, one correction, told in the terminal (`tour.py`)."""
    from .tour import run

    run(pause=0.0 if args.fast else 0.8)
    return 0


def cmd_sandbox(fabric: MemoryFabric, args: argparse.Namespace) -> int:
    """A throwaway store full of deliberately wrong memories, opened in the dashboard.

    Nothing touches `--db`: the store is created in a temporary directory, seeded
    (`demo.seed_sandbox`: a poisoning and its retraction, a disagreement, a
    leaked secret, a held contradicting claim, and gated actions, one of which
    rested on evidence withdrawn afterwards), and served on localhost.
    """
    import tempfile

    from .demo import seed_sandbox

    folder = pathlib.Path(args.dir) if args.dir else pathlib.Path(tempfile.mkdtemp(prefix="mf-sandbox-"))
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "sandbox.db"
    store = MemoryFabric(str(db), auto_activate=True)
    try:
        seed_sandbox(store)
    finally:
        store.close()
    print(f"sandbox store: {db}  (delete the folder when done)")
    if args.no_serve:
        return 0
    return main(["--db", str(db), "serve", "--port", str(args.port), "--no-maintain"])


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
        return Finding("warn", "schema version", "the log is empty, so nothing to compare",
                       "Nothing to fix: write a memory, or run `demo` to see a populated store.")
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
    row = fabric.log._conn.execute(
        "SELECT count(*) FROM outbox WHERE state = ?",
        (PropagationState.FAILED.value,),
    ).fetchone()
    failed = row[0] if row is not None else 0
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
    available, reason = aead_status()
    if not available and reason != "not installed":
        sealed_gcm = counts.get("v3", 0)
        if sealed_gcm:
            return Finding(
                "fail", "content cipher",
                f"{sealed_gcm} content version(s) are AES-GCM but `cryptography` "
                f"is {reason}; they cannot be read on this host",
                "Repair or reinstall `cryptography` for this interpreter.",
            )
        return Finding(
            "warn", "content cipher",
            f"`cryptography` is {reason}; new content is sealed with "
            f"{default_suite().name} instead of AES-GCM; {summary or 'no content yet'}; "
            f"keys {where}",
            "Repair or reinstall `cryptography` for this interpreter.",
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
    from .governance.cipher import profile as crypto_profile

    if crypto_profile() == "production":
        older = counts.get("v1", 0) + counts.get("v2", 0)
        if older:
            return Finding(
                "warn", "content cipher",
                f"production profile: new content is AES-GCM, but {older} older content "
                f"version(s) were sealed with the in-house suites; {summary}; keys {where}",
                "Revising a memory re-seals it with AES-GCM; there is no bulk rewrite of the log.",
            )
    return Finding(
        "ok", "content cipher",
        f"authenticated ({default_suite().name}, {crypto_profile()} profile); {summary}; "
        f"keys {where}",
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


def _check_manager(fabric: MemoryFabric) -> Finding:
    """Is the background manager running? Silent stores are not governed between visits."""
    from .manager import last_run

    run = last_run(fabric)
    if run is None:
        return Finding("ok", "background manager",
                       "never run on this store: maintenance is manual. `serve`, `agent-api` and "
                       "`mcp` start it; so does `memory-fabric maintain`")
    age_s = max(0.0, (fabric.now() - int(run["ts"])) / 1000)
    failed = [t for t, r in (run.get("tasks") or {}).items() if isinstance(r, dict) and "error" in r]
    if age_s > 3600:
        return Finding("warn", "background manager",
                       f"last cycle {age_s / 60:.0f} min ago by {run.get('holder')}: it has stopped",
                       "start `memory-fabric maintain`, or a server, for this store")
    if failed:
        return Finding("warn", "background manager", f"last cycle failed: {', '.join(failed)}",
                       "see `memory-fabric maintain --status`")
    return Finding("ok", "background manager", f"last cycle {age_s:.0f} s ago by {run.get('holder')}")


DOCTOR_CHECKS = (
    _check_manager,
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


def _doctor_alert(fabric: MemoryFabric, args: argparse.Namespace,
                  failures: list[Finding], warnings: list[Finding]) -> None:
    """POST the non-ok findings to `--webhook` when they warrant it.

    The store had no alerting: `doctor` exiting non-zero was the whole signal,
    and wiring it to a pager was left to every operator. This sends one JSON
    document (store, sound, failing and warning checks) to any endpoint that
    takes a POST, such as a chat webhook or an incident tool's events URL. A
    delivery that fails is reported on stderr and never hidden.
    """
    import urllib.error
    import urllib.request

    due = failures or (args.webhook_on == "warn" and warnings)
    if not due:
        return
    body = json.dumps({
        "source": "memory-fabric doctor",
        "store": str(fabric.log.path),
        "store_id": fabric.store_id,
        "sound": not failures,
        "severity": "fail" if failures else "warn",
        "findings": [f.to_json() for f in failures + warnings],
        "text": (f"memory-fabric: store {fabric.store_id} is "
                 + (f"NOT SOUND ({len(failures)} failing)" if failures
                    else f"sound with {len(warnings)} warning(s)")
                 + ": " + ", ".join(f.name for f in failures + warnings)),
    }).encode()
    request = urllib.request.Request(args.webhook, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"doctor: alert to the webhook was not delivered: {exc}", file=sys.stderr)


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
                        f"this check could not run: {exc!r}",
                        "The store may be sound; this check could not tell. Re-run with the "
                        "store's key directory (--keys) if content is sealed externally, and "
                        "report the error if it persists.")
            )

    failures = [f for f in findings if f.status == "fail"]
    warnings = [f for f in findings if f.status == "warn"]
    if getattr(args, "webhook", None):
        _doctor_alert(fabric, args, failures, warnings)

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
        "--version", action="version",
        version=f"memory-fabric {__import__('memory_fabric').__version__} "
                f"(schema {SCHEMA_VERSION})")
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
        "--share-policy", choices=("value", "reviewed"),
        default=os.environ.get("MEMORY_FABRIC_SHARE_POLICY") or "value",
        help="when a memory may leave this store: value (needs value evidence from verified "
        "outcomes; the default) or reviewed (once validated and active). Restricted memories "
        "never leave either way (default: $MEMORY_FABRIC_SHARE_POLICY or value)")
    parser.add_argument(
        "--log-format", choices=("text", "json"),
        default=os.environ.get("MEMORY_FABRIC_LOG_FORMAT") or "text",
        help="diagnostic log format on stderr; json is one object per line "
        "(default: $MEMORY_FABRIC_LOG_FORMAT or text)")
    parser.add_argument(
        "--log-level", default=os.environ.get("MEMORY_FABRIC_LOG_LEVEL") or "WARNING",
        help="diagnostic log level (default: $MEMORY_FABRIC_LOG_LEVEL or WARNING)")
    parser.add_argument(
        "--keys",
        metavar="DIR",
        default=os.environ.get("MEMORY_FABRIC_KEYS") or None,
        help="directory holding this store's content keys, when they are kept "
        "outside the database (default: $MEMORY_FABRIC_KEYS). Without it a "
        "store whose keys are external cannot be opened at all — which is the "
        "correct refusal, not a bug. `migrate-keys` moves an existing store's "
        "keys out.",
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
    p = add("anchor", cmd_anchor,
            "Anchor the integrity checkpoint off the store (dir:, git:, https://), or verify anchors")
    p.add_argument("--to", action="append", metavar="TARGET",
                   help="dir:PATH, git:REPO or an http(s) URL; repeat for several")
    p.add_argument("--verify", metavar="PATH",
                   help="an anchors file or dir: directory to check this store against")
    p = add("checkpoint", cmd_checkpoint,
            "Print an integrity checkpoint, or verify against a saved one")
    p.add_argument("--verify", metavar="FILE",
                   help="a checkpoint JSON file saved earlier, elsewhere")
    p = add("doctor", cmd_doctor,
            "Whether this installation's answers can be believed (exit 0/1/5)")
    p.add_argument("--webhook", metavar="URL",
                   help="POST a JSON alert here when the store is not sound")
    p.add_argument("--webhook-on", choices=["fail", "warn"], default="fail",
                   help="alert on failures only (default), or on warnings too")

    p = add("attention", cmd_attention, "Triage list: what needs a human, worst first")
    p.add_argument("--severity", choices=["high", "medium", "low"])

    p = add("list", cmd_list, "List memories")
    p.add_argument("--state")
    p.add_argument("--scope")
    p.add_argument("--tenant", help="only memories belonging to this tenant")
    p.add_argument("--agent", help="only memories this agent wrote (from provenance)")
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
            "- that policy makes an agent much worse.")
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

    p = add("maintain", cmd_maintain,
            "Run the background memory manager (also started by serve, mcp and agent-api)")
    p.add_argument("--once", action="store_true", help="one cycle, then exit")
    p.add_argument("--status", action="store_true",
                   help="the last cycle, and what it found that needs a person")
    p.add_argument("--no-maintain", action="store_true",
                   help="do not run the background memory manager in this process")
    p.add_argument("--maintain-interval", type=float, default=60.0, metavar="SECONDS")
    p.add_argument("--peers", help=f"JSON peer list for retraction delivery (or ${ENV_PEERS})")
    p.add_argument("--checkpoint-dir",
                   help=f"write integrity checkpoints here, off the store's disk (or ${ENV_CHECKPOINT_DIR})")
    p.add_argument("--retention-delete", action="store_true",
                   help="let the manager apply retention deletions (terminal); off by default")
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
    p.add_argument(
        "--operators-file",
        metavar="FILE",
        help="one 'name:token' per line, so each operator has their own token "
        "and every request is attributable. Tokens are never printed.",
    )
    p.add_argument(
        "--access-log",
        metavar="FILE",
        help="append who looked at what, one JSON line per request (default with "
        "--operators-file: <db>.access.jsonl; '-' turns it off)",
    )

    p.add_argument("--no-maintain", action="store_true",
                   help="do not run the background memory manager in this process")
    p.add_argument("--maintain-interval", type=float, default=60.0, metavar="SECONDS")
    p.add_argument("--peers", help=f"JSON peer list for retraction delivery (or ${ENV_PEERS})")
    p.add_argument("--checkpoint-dir",
                   help=f"write integrity checkpoints here, off the store's disk (or ${ENV_CHECKPOINT_DIR})")
    p.add_argument("--retention-delete", action="store_true",
                   help="let the manager apply retention deletions (terminal); off by default")
    p = add("mcp", cmd_mcp,
            "WRITES: serve this store to one agent over MCP (stdio). The agent "
            "can recall, fetch, verify and remember; it cannot record outcomes "
            "or see withdrawn memories")
    p.add_argument("--agent", required=True, help="the agent id every call is attributed to")
    p.add_argument("--tenant", default=DEFAULT_TENANT, help=f"tenant (default {DEFAULT_TENANT})")
    p.add_argument(
        "--trusted-local",
        action="store_true",
        help="the agent's clean writes become active without review (marked "
        "in provenance). For one person's local assistant only.",
    )
    p.add_argument("--extended-tools", action="store_true",
                   help="also offer build_context, explain_context, trace_provenance, "
                   "preview_correction, branch_create, branch_propose and merge_preview. "
                   "None applies a merge or a correction.")

    p.add_argument("--no-maintain", action="store_true",
                   help="do not run the background memory manager in this process")
    p.add_argument("--maintain-interval", type=float, default=60.0, metavar="SECONDS")
    p.add_argument("--peers", help=f"JSON peer list for retraction delivery (or ${ENV_PEERS})")
    p.add_argument("--checkpoint-dir",
                   help=f"write integrity checkpoints here, off the store's disk (or ${ENV_CHECKPOINT_DIR})")
    p.add_argument("--retention-delete", action="store_true",
                   help="let the manager apply retention deletions (terminal); off by default")
    p = add("erase", cmd_erase,
            "WRITES: crypto-erase one memory's content (provenance and audit "
            "stay), then report what the erasure reached and what it could not")
    p.add_argument("id")
    p.add_argument("--reason", required=True, help="recorded with the erasure, e.g. a ticket id")
    p.add_argument("--actor", default="operator")

    p = add("erasure-scope", cmd_erasure_scope,
            "What an erasure of one memory reached, kept, and could not reach")
    p.add_argument("id")

    p = add("agent-api", cmd_agent_api,
            "WRITES: serve agents over authenticated HTTP (recall, fetch, verify, "
            "remember), each request verified from a signed, expiring credential")
    p.add_argument("--agents-file", required=True,
                   help="agent_id:tenant_id:hex_key per line; secret, server-only")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--behind-tls", action="store_true",
                   help="allow a non-loopback bind because TLS terminates in front")
    p.add_argument("--rate-limit", type=float, default=20.0,
                   help="requests a second per agent, on average (0 turns it off)")
    p.add_argument("--burst", type=int, default=40, help="requests per agent at once")

    p.add_argument("--no-maintain", action="store_true",
                   help="do not run the background memory manager in this process")
    p.add_argument("--maintain-interval", type=float, default=60.0, metavar="SECONDS")
    p.add_argument("--peers", help=f"JSON peer list for retraction delivery (or ${ENV_PEERS})")
    p.add_argument("--checkpoint-dir",
                   help=f"write integrity checkpoints here, off the store's disk (or ${ENV_CHECKPOINT_DIR})")
    p.add_argument("--retention-delete", action="store_true",
                   help="let the manager apply retention deletions (terminal); off by default")
    p = add("offer", cmd_offer,
            "WRITES: offer one memory to a peer store over HTTP. It lands there as a "
            "candidate, recorded as from this store; a correction here follows it")
    p.add_argument("id", help="the memory to offer")
    p.add_argument("--to", required=True, help="the peer's store id, as in the peers file")
    p.add_argument("--peers", help=f"JSON peer list (or ${ENV_PEERS})")
    p.add_argument("--actor", default="operator", help="who is sharing it; recorded here")

    p = add("federate", cmd_federate,
            "WRITES: receive signed retractions and notices from peers over HTTP, and "
            "deliver this store's to them (the background manager)")
    p.add_argument("--peers", help=f"JSON peer list: who this store talks to (or ${ENV_PEERS})")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--behind-tls", action="store_true",
                   help="allow a non-loopback bind because TLS terminates in front")
    p.add_argument("--allow-plain-http", action="store_true",
                   help="allow a non-loopback bind over plain HTTP on a private network; "
                   "messages are signed, not encrypted")
    p.add_argument("--no-maintain", action="store_true",
                   help="receive only; do not deliver this store's retractions")
    p.add_argument("--maintain-interval", type=float, default=60.0, metavar="SECONDS")
    p.add_argument("--checkpoint-dir",
                   help=f"write integrity checkpoints here, off the store's disk (or ${ENV_CHECKPOINT_DIR})")
    p.add_argument("--retention-delete", action="store_true",
                   help="let the manager apply retention deletions (terminal); off by default")
    p = add("agent-api-issue", cmd_agent_api_issue,
            "Print a signed, expiring credential for one agent")
    p.add_argument("--agents-file", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds")

    p = sub.add_parser("init", help="WRITES: set up a store, external keys and an agent "
                       "in one step, then run doctor", description=cmd_init.__doc__)
    p.add_argument("dir", help="directory to create the store in")
    p.add_argument("--agent", default="my-assistant")
    p.add_argument("--tenant", default="tn_default")
    p.add_argument("--mode", choices=("personal", "team", "regulated"), default="team",
                   help="personal: one user, writes active at once; team: review before "
                        "sharing (default); regulated: two independent sources and fresh "
                        "evidence for protected tools")

    p = add("incident", cmd_incident,
            "Guided incident response: list candidates, assess one, --contain it "
            "(WRITES), --record FILE a reviewable record")
    p.add_argument("id", nargs="?")
    step = p.add_mutually_exclusive_group()
    step.add_argument("--contain", action="store_true")
    step.add_argument("--record", metavar="FILE", help=".md (default) or .json")
    step.add_argument("--verify", action="store_true",
                      help="check containment from the store's state: exit 0 contained, "
                           "1 contained with actions to review, 3 unresolved")
    p.add_argument("--reason", default="")
    p.add_argument("--actor")

    p = add("lifecycle", cmd_lifecycle,
            "Retention rules, stale and sensitive memories, and erasure and retraction "
            "progress across stores. Read-only")
    p.add_argument("--stale-days", type=int, default=90)
    p.add_argument("--limit", type=int, default=20)

    add("posture", cmd_posture,
        "Which security controls are on in this store, and the accepted gaps")
    p = add("receipt-verify", cmd_receipt_verify,
            "Verify a signed action receipt (exit 0 valid, 5 invalid); needs no store")
    p.add_argument("path", help="the receipt JSON file")
    p.add_argument("--public-key", help="the signer's Ed25519 public key, base64, obtained independently")

    p = add("access-log-verify", cmd_access_log_verify,
            "Check the dashboard access log's hash chain (exit 0 intact, 5 broken)")
    p.add_argument("path", help="the access log file (JSON lines)")

    p = add("audit-export", cmd_audit_export,
            "Export decisions, changes, access events and deletion receipts as JSONL, "
            "without memory content, ending with a hash-chain checkpoint")
    p.add_argument("--out", required=True)
    p.add_argument("--kind", action="append", choices=["decisions", "changes", "access", "deletions"])
    p.add_argument("--since-seq", type=int, default=0)

    p = add("import", cmd_import,
            "WRITES: import another store's export (JSON list or JSONL: Mem0, LangChain "
            "documents, plain content) as private candidates waiting for review")
    p.add_argument("file")
    p.add_argument("--source", required=True, help="where it came from, recorded on each memory")
    p.add_argument("--agent", default="importer",
                   help="author for records that do not name one")
    p.add_argument("--tenant")

    p = add("import-docs", cmd_import_docs,
            "WRITES: import a compiled document (JSON: doc_id, version, sections with path and "
            "text); re-importing withdraws sections the new version changed or removed")
    p.add_argument("file")
    p.add_argument("--format", choices=["json", "markdown", "html", "csv", "docx"], default="json",
                   help="source format: a compiled JSON tree, or a local Markdown, HTML, CSV or .docx file")
    p.add_argument("--key", help="CSV only: the column that identifies a row across versions")
    p.add_argument("--doc-id", help="stable document identity (all formats but json)")
    p.add_argument("--source-version", help="explicit source revision (all formats but json)")
    p.add_argument("--source-uri", help="optional source citation URI; never fetched")
    p.add_argument("--activate", action="store_true",
                   help="sections are active at once (the document is the authority)")
    p.add_argument("--tenant")

    p = add("export-events", cmd_export_events,
            "Write every event, withdrawals and erasures included, to a portable file "
            "with a verifying manifest (move a store between machines or backends)")
    p.add_argument("--out", required=True)

    p = add("import-events", cmd_import_events,
            "WRITES: load an export-events file into an empty store and replay it")
    p.add_argument("file")

    p = add("collection", cmd_collection,
            "Collections: named sets of memories agents can be attached to. list, or WRITES: "
            "add/remove a memory, attach/detach an agent, grant/revoke permissions")
    p.add_argument("action", choices=["list", "add", "remove", "attach", "detach", "grant", "revoke"])
    p.add_argument("name", nargs="?")
    p.add_argument("--memory")
    p.add_argument("--agent")
    p.add_argument("--permission", action="append", choices=["read", "write", "approve", "retract"],
                   help="repeatable; attach means read")
    p.add_argument("--actor", help="who is changing this; required for a change")
    p.add_argument("--tenant")

    p = add("branch", cmd_branch,
            "Memory branches: list, show, diff, or WRITES: create, add, revise, withdraw "
            "(each a one-change commit), close")
    p.add_argument("action", choices=["list", "create", "show", "diff", "add", "revise",
                                      "withdraw", "close"])
    p.add_argument("name", nargs="?")
    p.add_argument("--actor")
    p.add_argument("--text")
    p.add_argument("--memory")
    p.add_argument("--reason")
    p.add_argument("--message")
    p.add_argument("--member", action="append")
    p.add_argument("--reviewer", action="append")
    p.add_argument("--tenant")

    p = add("merge", cmd_merge,
            "Preview merging a branch into main; WRITES with apply (needs the preview's "
            "digest and an idempotency key), or revert a merge")
    p.add_argument("action", choices=["preview", "apply", "revert"])
    p.add_argument("name", help="the branch (or, for revert, the merge id)")
    p.add_argument("--actor")
    p.add_argument("--preview")
    p.add_argument("--key")
    p.add_argument("--tenant")

    p = add("context", cmd_context,
            "Build an agent's context bundle under a token budget and record its receipt "
            "(WRITES the receipt), list receipts, or explain one")
    p.add_argument("action", choices=["build", "receipts", "explain", "wake", "zoom",
                                      "pending", "summarise"])
    p.add_argument("receipt", nargs="?")
    p.add_argument("--agent")
    p.add_argument("--query")
    p.add_argument("--budget", type=int, default=2000)
    p.add_argument("--mode", default="auto",
                   choices=["auto", "compact", "balanced", "evidence-first", "exact"])
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--node")
    p.add_argument("--text")
    p.add_argument("--tenant")

    p = add("correct", cmd_correct,
            "Preview what withdrawing a memory would touch; with --apply, WRITES it and "
            "owes the retraction to every store that received it")
    p.add_argument("id")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--status", action="store_true", help="what each store acknowledged")
    p.add_argument("--reason", default="")
    p.add_argument("--actor", help="who is correcting this; required with --apply")
    p.add_argument("--basis", default="contradicted",
                   choices=["contradicted", "sensitive_data", "contrastive_harm"])
    p.add_argument("--preview", dest="preview_digest",
                   help="the digest the preview printed; --apply refuses if the store changed")

    p = add("suspicious", cmd_suspicious,
            "Memories whose claim contradicts what the store knows: a corrected value "
            "restated, a value far out of range, or a contradiction of an established fact")
    p.add_argument("--limit", type=int, default=50)

    p = add("review", cmd_review,
            "The review queue. With an id and a decision, WRITES it: approve (usable by "
            "the team), limit (usable by its author only), correct, or reject")
    p.add_argument("id", nargs="?")
    choice = p.add_mutually_exclusive_group()
    choice.add_argument("--approve", action="store_true")
    choice.add_argument("--limit", action="store_true")
    choice.add_argument("--reject", action="store_true")
    choice.add_argument("--correct", metavar="TEXT")
    p.add_argument("--reason", default="")
    p.add_argument("--actor", help="the reviewer; required for a decision")
    p.add_argument("--override-screen", action="store_true",
                   help="approve a memory an ingest screen quarantined")
    p.add_argument("--tenant", help="only this tenant's queue")

    p = add("share", cmd_share,
            "WRITES: widen who may read a memory (private -> team -> federated), "
            "through the firewall, logged")
    p.add_argument("id", nargs="?", help="the memory to share")
    p.add_argument("--scope", choices=["team", "federated"], default="team")
    p.add_argument("--actor", default="operator", help="who is deciding this")
    p.add_argument("--all-private-active", action="store_true",
                   help="share every active private memory: the upgrade path for stores "
                        "written before scope was enforced on reads")

    p = add("agent-api-revoke", cmd_agent_api_revoke,
            "WRITES: revoke a leaked credential, or all of one agent's; a running "
            "agent-api on this store refuses it on the next request")
    p.add_argument("--agents-file", required=True)
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--agent", help="revoke every credential this agent holds")
    who.add_argument("--token", help="the leaked credential, or - to read it from stdin")

    p = add("migrate-keys", cmd_migrate_keys,
            "WRITES: move content keys out of the database into a directory, "
            "verified by replay before anything is removed")
    p.add_argument("directory", help="where the keys will live from now on")

    p = add("backup", cmd_backup,
            "Consistent snapshot of the event log, verified by replaying it")
    p.add_argument("path", help="where to write the copy")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.add_argument("--with-keys", action="store_true",
                   help="also copy the key directory named by --keys, beside the copy "
                   "(<path>.keys/). Keep that copy as protected as the original")
    p.add_argument("--include", action="append", default=[], metavar="PATH",
                   help="a config file or directory to keep with the backup "
                   "(<path>.config/): agents.txt, a peers file, a checkpoint directory. "
                   "Repeatable")

    p = add("restore", cmd_restore,
            "WRITES: restore a backup made with `backup`, after checking its manifest")
    p.add_argument("backup", help="the backup file (its .manifest.json must be beside it)")
    p.add_argument("dest", help="directory to restore into; must not exist")

    add("demo", cmd_demo, "WRITES: seed a demonstration store")
    p = add("sandbox", cmd_sandbox,
            "A throwaway store with deliberately wrong memories, opened in the dashboard")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--dir", help="where to create it (default: a new temporary folder)")
    p.add_argument("--no-serve", action="store_true", help="seed only; print the path")
    p = add("pilot-report", cmd_pilot_report,
            "Outcome numbers for a pilot, from the log: no content, agents pseudonymised")
    p.add_argument("--names", action="store_true", help="keep agent names instead of hashes")
    p.add_argument("--check", action="store_true",
                   help="say in plain words whether the pilot has produced enough to send")
    p = add("connect", cmd_connect,
            "Set up an agent tool: connect <tool> --agent <id> [--write]; connect --list")
    p.add_argument("tool", nargs="?", help="claude-code, claude-desktop, cursor, windsurf, vscode, "
                   "cline, gemini-cli, zed, codex, continue, http, python")
    p.add_argument("--agent", help="the id this tool's memories are recorded under")
    p.add_argument("--write", action="store_true",
                   help="merge into the tool's config file (keeps a .bak)")
    p.add_argument("--trusted-local", action="store_true",
                   help="single-user machine: the agent's clean writes skip review")
    p.add_argument("--list", action="store_true", help="list the tools this knows")
    p = add("models", cmd_models,
            "Which model providers are ready here, and test one: models [--test provider:model]")
    p.add_argument("--test", metavar="SPEC", help="send one short request, e.g. ollama:qwen2.5:7b")
    p = add("tour", cmd_tour,
            "The whole idea in sixty seconds: one fact, four agents, one correction")
    p.add_argument("--fast", action="store_true", help="print it at once, without pauses")
    _fill_help(sub)
    return parser


ID_HELP = "the memory id"
ACTOR_HELP = "who is making this change; recorded in the audit trail"
REASON_HELP = "why, recorded with the change"
HELP: dict[tuple[str | None, str], str] = {
    (None, "id"): ID_HELP, (None, "--actor"): ACTOR_HELP, (None, "--reason"): REASON_HELP,
    (None, "--limit"): "show at most this many",
    (None, "--maintain-interval"): "seconds between background maintenance cycles",
    (None, "--port"): "TCP port to listen on", (None, "--host"): "address to bind (default loopback)",
    (None, "--tenant"): "tenant id to act within",
    (None, "--agents-file"): "agent_id:tenant_id:hex_key per line; secret, server-only",
    ("attention", "--severity"): "show only items at or above this severity",
    ("list", "--state"): "filter by lifecycle state (candidate, active, contested, ...)",
    ("list", "--scope"): "filter by scope (private, team, federated)",
    ("list", "--type"): "filter by memory type (semantic, episodic, procedural, ...)",
    ("list", "--sort"): "sort order",
    ("lineage", "--direction"): "ancestors (what it came from), descendants (what came from it), or both",
    ("lineage", "--depth"): "how many generations to follow",
    ("search", "query"): "text to search for", ("episodes", "--limit"): "show at most this many episodes",
    ("agent-api-issue", "--agent"): "the agent to issue a credential for",
    ("init", "--agent"): "the first agent to register", ("init", "--tenant"): "its tenant id",
    ("incident", "id"): "the memory at the centre of the incident; omit to list candidates",
    ("incident", "--contain"): "withdraw it, contest what rests on it, and owe retractions to peers",
    ("lifecycle", "--stale-days"): "memories unused for this many days count as stale",
    ("audit-export", "--out"): "file to write (JSON lines, content-free)",
    ("audit-export", "--kind"): "which records to include; repeatable (default: all)",
    ("audit-export", "--since-seq"): "only events after this log sequence",
    ("import", "file"): "a text, Markdown or JSONL file to import as memories",
    ("import-docs", "file"): "the document tree as JSON",
    ("export-events", "--out"): "file to write (JSON lines plus a manifest line)",
    ("import-events", "file"): "a file written by export-events",
    ("collection", "action"): "what to do with the collection",
    ("collection", "name"): "the collection's name", ("collection", "--memory"): "memory id to add or remove",
    ("collection", "--agent"): "agent to grant or revoke",
    ("correct", "--apply"): "withdraw it and owe retractions (without this, only preview)",
    ("branch", "action"): "list, show (history), diff; or create, add, revise, withdraw, close",
    ("merge", "action"): "preview, apply (needs --preview and --key) or revert (a merge id)",
    ("context", "action"): "build a bundle and its receipt, list receipts, explain one; "
                           "wake/zoom the decay view, list nodes pending a summary, summarise one",
    ("branch", "--actor"): "who is acting; the owner for create and close",
    ("branch", "--text"): "the memory text to add or the revised text",
    ("branch", "--memory"): "the main memory to revise or withdraw",
    ("branch", "--reason"): "why it is withdrawn",
    ("branch", "--message"): "the commit message",
    ("branch", "--member"): "repeatable: an agent who may write to the branch",
    ("branch", "--reviewer"): "repeatable: an agent who may merge it into main",
    ("branch", "name"): "the branch",
    ("merge", "--actor"): "who is merging (the owner or a reviewer); audited",
    ("merge", "--preview"): "the full digest the preview printed",
    ("merge", "--key"): "an idempotency key: a retry with it replays, never applies twice",
    ("context", "receipt"): "a receipt id, for explain",
    ("context", "--node"): "a decay-view node LO-HI, for zoom and summarise",
    ("context", "--text"): "the summary to store for --node (summarise)",
    ("context", "--agent"): "the agent the context is for",
    ("context", "--query"): "what the agent is working on (stored only as a digest)",
    ("context", "--budget"): "token budget (estimated as characters / 4)",
    ("context", "--mode"): "auto picks exact for numbers, ids and dates, else balanced",
    ("context", "--limit"): "how many receipts to list",
    ("correct", "--preview"): "the preview's digest: refuse to apply if anything it showed changed",
    ("correct", "--basis"): "the evidence for withdrawing it (contradicted, sensitive_data, ...)",
    ("review", "id"): "the candidate to decide on; omit to list the queue",
    ("review", "--approve"): "make it active", ("review", "--reject"): "quarantine it",
    ("review", "--correct"): "replace its content with a corrected version",
    ("share", "--scope"): "how far it may travel: team or federated",
    ("erasure-scope", "id"): "the memory whose erasure you are scoping",
}


def _fill_help(sub: argparse._SubParsersAction) -> None:
    """Give every option a help line, from HELP: (command, flag) first, then (None, flag)."""
    for name, command in sub.choices.items():
        for action in command._actions:
            if action.help or action.dest == "help":
                continue
            flag = action.option_strings[-1] if action.option_strings else action.dest
            action.help = HELP.get((name, flag)) or HELP.get((None, flag))


CREATING_COMMANDS = frozenset({"demo"})


def cmd_init(args: argparse.Namespace) -> int:
    """Set up a store the way production should run it, in one step.

    A directory with the store, its content keys kept *outside* the database
    (the production default: a copy of the `.db` alone reads nothing), and an
    agents file with one agent and a fresh signing key, owner-only. Prints the
    MCP client configuration and the next commands, then runs `doctor`. It
    never overwrites: an existing store is an error, not a reset.
    """
    import secrets

    from .governance.erasure import DirectoryKeyProvider

    root = Path(args.dir)
    db, keys, agents = root / "store.db", root / "keys", root / "agents.txt"
    if db.exists() or agents.exists():
        print(f"{C.RED}{root} already holds a store; init never overwrites one{C.RESET}",
              file=sys.stderr)
        return 2
    keys.mkdir(parents=True, exist_ok=True)
    fabric = MemoryFabric(str(db), key_provider=DirectoryKeyProvider(str(keys)))
    store_id = fabric.store_id
    fabric.close()
    agents.write_text(
        "# agent_id:tenant_id:hex_key -- server-only, owner-readable. Add a line per agent.\n"
        f"{args.agent}:{args.tenant}:{secrets.token_hex(32)}\n", encoding="utf-8")
    try:
        os.chmod(agents, 0o600)
        os.chmod(keys, 0o700)
    except OSError:  # pragma: no cover - permissions are advisory on some filesystems
        pass
    db_s, keys_s = str(db), str(keys)
    print(f"{C.GREEN}created{C.RESET} store {store_id}")
    print(f"  store       {db_s}")
    print(f"  keys        {keys_s}   {C.DIM}(outside the database; back it up separately){C.RESET}")
    print(f"  agents      {agents}   {C.DIM}(holds a signing key; keep it on the server){C.RESET}")
    from .presets import mcp_flags

    (root / "mode").write_text(args.mode + "\n", encoding="utf-8")
    print(f"  mode        {args.mode}   {C.DIM}(memory_fabric.presets: open_store(path, {args.mode!r})){C.RESET}")
    print("\nConnect an MCP client (Claude Code, Claude Desktop, an IDE) with:")
    print(json.dumps({"mcpServers": {"memory-fabric": {
        "command": "memory-fabric",
        "args": ["--db", db_s, "--keys", keys_s, "mcp", "--agent", args.agent,
                 *mcp_flags(args.mode)]}}}, indent=2))
    print("\nNext:")
    print(f"  memory-fabric --db {db_s} --keys {keys_s} review      # what agents wrote, waiting for you")
    print(f"  memory-fabric --db {db_s} --keys {keys_s} serve       # the dashboard")
    print(f"  memory-fabric --db {db_s} --keys {keys_s} connect --list   # set up another agent tool")
    print(f"  memory-fabric --db {db_s} --keys {keys_s} agent-api --agents-file {agents}")
    print()
    return main(["--db", db_s, "--keys", keys_s, "doctor"])


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    from .observability.logs import configure as configure_logs

    configure_logs(args.log_format, args.log_level)
    if args.command == "init":  # creates its own layout; opens no --db
        return cmd_init(args)
    if args.command == "restore":  # writes a new directory; opens no --db
        return cmd_restore(None, args)  # type: ignore[arg-type]
    if args.command == "connect":  # writes a tool's config, not the store
        return cmd_connect(None, args)  # type: ignore[arg-type]
    if args.command == "models":  # environment only; opens no --db
        return cmd_models(None, args)  # type: ignore[arg-type]
    if args.command == "tour":  # in memory; opens no --db
        return cmd_tour(None, args)  # type: ignore[arg-type]
    if args.command == "sandbox":  # creates its own store; opens no --db
        return cmd_sandbox(None, args)  # type: ignore[arg-type]
    if args.command == "receipt-verify":  # reads a file; opens no --db
        return cmd_receipt_verify(None, args)  # type: ignore[arg-type]
    if args.command == "access-log-verify":  # reads a file; opens no --db
        return cmd_access_log_verify(None, args)  # type: ignore[arg-type]

    # Opening a store creates it, so a typo in --db would otherwise produce an
    # empty store and a confident report of nothing wrong. For an inspection
    # tool that is the worst possible failure: it looks like an answer.
    if (
        args.db != ":memory:"
        and not args.db.startswith(("postgresql://", "postgres://"))
        and args.command not in CREATING_COMMANDS
        and not args.create
        and not os.path.exists(args.db)
    ):
        print(
            f"{C.RED}no store at {_shown(args.db)}{C.RESET}\n"
            f"{C.DIM}Check the path, or pass --create to start an empty one. "
            f"To populate a demo store: memory-fabric --db {_shown(args.db)} demo{C.RESET}",
            file=sys.stderr,
        )
        return 2

    key_provider = None
    if args.keys:
        key_provider = DirectoryKeyProvider(args.keys)

    try:
        from .governance.firewall import SHARE_POLICIES, Firewall

        retrieval: dict[str, Any] = {}
        if os.environ.get("MEMORY_FABRIC_EMBEDDER") or os.environ.get("MEMORY_FABRIC_RERANKER"):
            # The retriever the operator chose (RETRIEVAL.md). Only when asked:
            # opening a store must not download a model by surprise.
            from .retrievers import from_environment

            retrieval = from_environment()
        mode_file = Path(str(args.db)).parent / "mode"
        if "://" not in str(args.db) and mode_file.is_file():
            # The mode `init --mode` recorded beside the store (presets.py).
            from .presets import MODES, store_settings

            mode = mode_file.read_text(encoding="utf-8").strip()
            if mode in MODES:
                retrieval = {**store_settings(mode), **retrieval}
        fabric = MemoryFabric(
            args.db, estimator=args.estimator, key_provider=key_provider,
            firewall=Firewall(rules=SHARE_POLICIES[args.share_policy]), **retrieval,
        )
    except KeyUnavailable as exc:
        # Distinguished from any other open failure, because the remedy is
        # specific and the default message would send someone looking at the
        # database instead of at the key store they did not mount.
        print(
            f"{C.RED}could not open {_shown(args.db)}: {exc}{C.RESET}\n"
            f"{C.DIM}If this store's content keys are kept outside the "
            f"database, point at them with --keys <dir>.{C.RESET}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"{C.RED}could not open {_shown(args.db)}: {exc}{C.RESET}", file=sys.stderr)
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
