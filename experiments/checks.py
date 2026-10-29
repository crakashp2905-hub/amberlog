"""Re-export of `memeval.checks`, where these checks now live.

Kept so every harness that imports `experiments.checks` keeps working. The
checks moved into `memeval` because they are not specific to Amberlog --
each one catches a mistake any evaluation of agent memory can make -- and a
package that evaluates other systems cannot live inside one of them.
"""

from memeval.checks import (  # noqa: F401
    auc, baseline_max, ceiling, class_collapse, collapsed_to_prior,
    direction, fixture_independence, verify,
)
