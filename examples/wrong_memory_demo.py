"""The wrong-memory story, end to end: correct a policy, see what changes, branch an alternative.

    python examples/wrong_memory_demo.py

A small product-support domain, with nothing outside this process:

1. Source A states a refund policy; an agent stores it and derives a rule.
2. The agent's context comes with a receipt naming exactly what it used.
3. A corrected source arrives. The operator previews the impact, then
   applies it with the preview's digest, so a stale preview cannot apply.
4. The derived rule is contested, and the next context leaves it out; the old
   receipt shows what is no longer admissible.
5. A researcher proposes an alternative on a branch. Main never sees it, and
   the merge preview keeps the disagreement for review instead of picking a
   winner.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.branching import Branches  # noqa: E402
from memory_fabric.context_receipt import build_context, explain_receipt  # noqa: E402
from memory_fabric.correction import apply, preview  # noqa: E402


def show(title: str) -> None:
    print(f"\n== {title}")


def main() -> None:
    f = MemoryFabric(":memory:", auto_activate=True)

    show("1. A source states a policy; an agent derives a rule from it")
    policy = f.remember("source-a", "Refund window R1 is 30 days from delivery.", scope="team")
    rule = f.derive("support-bot", "Ticket rule R1: approve refunds up to day 30.",
                    parents=[policy], scope="team")
    print(f"policy {policy}\nrule   {rule}")

    show("2. The agent's context, with its receipt")
    first = build_context(f, "support-bot", "refund window r1", mode="evidence-first")
    print(first.text)
    print(f"receipt {first.receipt['receipt_id']}: "
          f"{[s['id'] + '@v' + str(s['version']) for s in first.receipt['selected']]}")

    show("3. A corrected source: preview the impact, then apply that preview")
    p = preview(f, policy)
    print(f"withdrawing the policy would contest {p.would_contest}; preview {p.digest[:16]}")
    result = apply(f, policy, reason="source A corrected: 14 days", actor="ops-lead",
                   preview_digest=p.digest[:16])
    corrected = f.remember("source-a", "Refund window R1 is 14 days from delivery.",
                           scope="team")
    print(f"applied (preview checked: {result['preview_checked']}); new policy {corrected}")

    show("4. The next context leaves the stale rule out; the old receipt says why")
    second = build_context(f, "support-bot", "refund window r1", mode="evidence-first")
    print(second.text)
    for item in explain_receipt(f, first.receipt["receipt_id"])["selected"]:
        print(f"  earlier receipt: {item['id']}  "
              + ("still admissible" if item["admissible_now"] else "; ".join(item["changes"])))

    show("5. A researcher branches an alternative reading")
    b = Branches(f)
    b.create("vendor-reading", owner="researcher", reviewers=("ops-lead",))
    with b.commit("vendor-reading", "researcher", "vendor contract says 21 days") as c:
        c.add("Refund window R1 is 21 days from delivery.")
    seen = [m.content for m in f.retrieve("support-bot", "refund window r1").exposed]
    print(f"main still serves: {seen}")
    merge = b.preview_merge("vendor-reading", "ops-lead")
    for change in merge.changes:
        print(f"  merge would: {change.decision} ({change.klass}: {change.reason})")
    f.close()


if __name__ == "__main__":
    main()
