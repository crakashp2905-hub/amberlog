"""memeval -- an evaluation harness for agent memory that refuses common errors.

Independent of Memory Fabric: nothing in this package imports it, and it has
no dependencies beyond the standard library. It was extracted from Memory
Fabric's experiments, where every check in it caught a number that had
already been published wrong.

    from memeval import Registration
    reg = Registration(hypothesis="...", metric="success",
                       mechanism="mine", baselines=["vector_store"],
                       ceiling="oracle")
    reg.check_before_run(n_pairs=120, expected_discordance=0.2)
    verdict = reg.evaluate(arms, seeds=5, n_pairs=120, discordance=0.18)

See `memeval/README.md`.
"""

from . import checks, power, stats  # noqa: F401
from .contract import Outcome, Registration, Verdict  # noqa: F401

__version__ = "0.1.0"
