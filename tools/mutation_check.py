"""Mutation testing for the security-critical checks: every guard must have a test that notices it gone.

    python tools/mutation_check.py           # all mutants
    python tools/mutation_check.py --list    # what they are

Each mutant deletes or inverts one guard: a tenant check, a visibility
check, a signature check, a grant's expiry. The tool applies it, runs the
tests named for it, and restores the file. A mutant **survives** when those
tests still pass: that guard is untested, and the run fails. Each mutant's
original text must occur exactly once in its file, so a refactor that moves
the guard fails loudly here instead of turning the mutant into a no-op.

Dependency-free, curated rather than generated: a generated mutant of a log
message or a comment teaches nothing, and every mutant here is a check whose
removal is a security bug.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str
    original: str
    mutated: str
    tests: tuple[str, ...]


MUTANTS = [
    Mutant("action-time check ignores visibility (F15)", "amberlog/enforcement.py",
           "        decision = self.check(token.memory_id, risk=risk, tenant_id=token.tenant_id,\n"
           "                              agent_id=agent_id)",
           "        decision = self.check(token.memory_id, risk=risk, tenant_id=token.tenant_id)",
           ("tests.test_visibility_at_action", "tests.test_access_matrix")),
    Mutant("a token works for any agent", "amberlog/enforcement.py",
           "        if token.agent_id != agent_id:", "        if False:",
           ("tests.test_enforcement",)),
    Mutant("an expired token is accepted", "amberlog/enforcement.py",
           "        if token.expired(self.fabric.now()):", "        if False:",
           ("tests.test_enforcement",)),
    Mutant("the enforced read ignores the tenant", "amberlog/enforcement.py",
           "        if tenant_id is not None and memory.tenant_id != tenant_id:\n",
           "        if False:\n",
           ("tests.test_access_matrix", "tests.test_identity")),
    Mutant("private memories visible to everyone", "amberlog/model.py",
           "    if memory.provenance.created_by == agent_id:", "    if True:",
           ("tests.test_scope_visibility", "tests.test_access_matrix")),
    Mutant("an ungranted agent may call a protected tool", "amberlog/actions.py",
           "        if tool not in self.policy.grants.get(agent_id, frozenset()):\n"
           "            # Before any memory is consulted.",
           "        if False:\n            # Before any memory is consulted.",
           ("tests.test_action_fence", "tests.test_authority")),
    Mutant("an expired grant is accepted", "amberlog/actions.py",
           '        if self.fabric.now() >= int(issued["expires_ms"]):',
           "        if False:", ("tests.test_authority",)),
    Mutant("a used grant can be replayed", "amberlog/actions.py",
           "                return GRANT_REPLAYED", "                pass", ("tests.test_authority",)),
    Mutant("a grant covers a different action", "amberlog/actions.py",
           "            return GRANT_MISMATCH", "            pass", ("tests.test_authority",)),
    Mutant("a crash mid-action is treated as never attempted", "amberlog/actions.py",
           '                last = {"outcome": UNCERTAIN}', "                last = None",
           ("tests.test_action_crash",)),
    Mutant("a forwarded retraction is verified with the origin's key (F16)",
           "amberlog/transport.py",
           "            sender = retraction.forwarded_by or retraction.origin_store_id\n"
           "            key = registry.key_for(sender,",
           "            sender = retraction.origin_store_id\n"
           "            key = registry.key_for(sender,", ("tests.test_multihop_http",)),
    Mutant("a retraction's signature is not checked", "amberlog/transport.py",
           "            if key is None or not retraction.verify(signature, key):",
           "            if key is None:", ("tests.test_federation_transport",)),
    Mutant("copies may outrun their retraction (no hop limit)", "amberlog/federation.py",
           "    if len(chain) >= MAX_HOPS:", "    if False:", ("tests.test_federation_reach",)),
    Mutant("a corrected value restated is not flagged", "amberlog/validation.py",
           '            signals.setdefault("reasserts_corrected", oid)', "            pass",
           ("tests.test_validation",)),
    Mutant("authority is not inherited from sources", "amberlog/authority.py",
           "        stack.extend(parents)", "        pass", ("tests.test_authority",)),
    Mutant("an author may elevate its own memory", "amberlog/_fabric/lifecycle.py",
           "            if approver == memory.provenance.created_by or approver in current.origins:",
           "            if False:", ("tests.test_authority",)),
    Mutant("no payload limit", "amberlog/limits.py",
           "        if size > self.limits.max_content_bytes:", "        if False:",
           ("tests.test_limits",)),
    Mutant("permissions are not enforced", "amberlog/identity.py",
           "    def require_permission(self, permission: str) -> None:\n"
           "        if not self.can(permission):",
           "    def require_permission(self, permission: str) -> None:\n        if False:",
           ("tests.test_permissions",)),
    Mutant("a summary may drop recorded values", "amberlog/compaction.py",
           "    if missing:\n        raise CompactionRefused", "    if False:\n        raise CompactionRefused",
           ("tests.test_compaction",)),
    Mutant("a hostile source is not withheld", "amberlog/_fabric/retrieval.py",
           "        if not self.withhold_hostile_sources:\n            return eligible",
           "        return eligible", ("tests.test_source_notice",)),
]


def tests_pass(modules: tuple[str, ...]) -> bool:
    done = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=ROOT,
                          capture_output=True, text=True, timeout=900)
    return done.returncode == 0


def run(mutant: Mutant) -> tuple[bool, float]:
    path = ROOT / mutant.path
    raw = path.read_bytes()  # restored byte for byte, line endings included
    # Match on LF text; the file is written back with its own line endings.
    crlf = b"\r\n" in raw
    original = raw.decode("utf-8").replace("\r\n", "\n")
    count = original.count(mutant.original)
    mutated_text = original.replace(mutant.original, mutant.mutated, 1)
    if crlf:
        mutated_text = mutated_text.replace("\n", "\r\n")
    if count != 1:
        raise SystemExit(f"mutant {mutant.name!r}: its original text occurs {count} times in "
                         f"{mutant.path}; update the mutant to match the code")
    path.write_bytes(mutated_text.encode("utf-8"))
    started = time.perf_counter()
    try:
        killed = not tests_pass(mutant.tests)
    finally:
        path.write_bytes(raw)
    return killed, time.perf_counter() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        for m in MUTANTS:
            print(f"- {m.name}  ({m.path}; killed by {', '.join(m.tests)})")
        return 0
    # A mutant only counts as killed by tests that pass without it: a missing
    # or already-failing test module would otherwise "kill" every mutant.
    for modules in sorted({m.tests for m in MUTANTS}):
        if not tests_pass(modules):
            raise SystemExit(f"baseline failed: {' '.join(modules)} does not pass unmutated")
    survivors = []
    for m in MUTANTS:
        killed, seconds = run(m)
        print(f"{'killed  ' if killed else 'SURVIVED'} {m.name}  ({seconds:.1f}s)", flush=True)
        if not killed:
            survivors.append(m.name)
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} mutants killed")
    if survivors:
        print("untested guards: " + "; ".join(survivors))
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
