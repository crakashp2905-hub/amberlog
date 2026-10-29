"""The 10-minute quickstart, as one runnable file (docs/QUICKSTART.md walks through it).

    python examples/quickstart.py [store.db]

Store, retrieve, inspect the evidence, correct a wrong memory, and verify
that the correction took. `tests/test_quickstart.py` runs this file, so the
quickstart cannot silently stop working.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amberlog import Amberlog, correction, influence  # noqa: E402
from amberlog.response import verify_recovery  # noqa: E402


def main(path: str) -> dict[str, object]:
    fabric = Amberlog(path, auto_activate=True)
    try:
        # 1. Store. Each memory records who wrote it and how.
        wrong = fabric.remember("field-tech", "Pump P1 purge time is 10 seconds.", scope="team")
        right_source = fabric.remember("plant-manual", "Pump P1 requires a 30 second purge.",
                                       scope="team")
        plan = fabric.derive("planner", "Schedule P1 restarts with a 10 s purge.",
                             parents=[wrong], scope="team")

        # 2. Retrieve. What an agent asking about the purge is shown.
        shown = [m.content for m in fabric.retrieve("assistant", "P1 purge time", k=3).exposed]
        print("shown before the correction:", *shown, sep="\n  ")

        # 3. Inspect the evidence: why it is remembered, and where it came from.
        print("\nwhy is the plan remembered?\n ", fabric.explain(plan).narrative())
        print("authority of the plan:", fabric.authority(plan).trust,
              "| sources:", fabric.authority(plan).origins)

        # 4. Correct. Preview what withdrawing the wrong memory touches, then apply.
        preview = correction.preview(fabric, wrong)
        print("\ncorrecting it would contest:", preview.would_contest)
        correction.apply(fabric, wrong, reason="manual says 30 s", actor="shift-lead")

        # 5. Verify the correction took, from the store's own state.
        after = [m.id for m in fabric.retrieve("assistant", "P1 purge time", k=3).exposed]
        check = verify_recovery(fabric, wrong)
        impact = influence.impact(fabric, wrong)
        print("\nshown after:", [fabric.get(m).content for m in after])
        print("recovery:", check["status"], "/", check["recovery_state"])
        print("downstream of the wrong memory:", impact["potentially_contaminated"]["memories"])
        assert wrong not in after and plan not in after and right_source in after
        assert check["status"] == "contained", check
        return {"shown_after": after, "status": check["status"], "right": right_source}
    finally:
        fabric.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(tempfile.mkdtemp()) / "quickstart.db")
    main(target)
    print(f"\nquickstart complete; the store is at {target}")
