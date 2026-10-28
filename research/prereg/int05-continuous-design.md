# INT-05 continuous 50-task world: design freeze, no improvement threshold

Status: preregistration of protocol; baseline/headroom pilot and implementation
remain pending. No PASS result or numeric superiority threshold is registered.
Do not run hosted models under this protocol without explicit spending approval.

Each episode contains 50 ordered tasks with persistent stores, five scripted
roles (observer, planner, reviewer, executor, auditor), limited context and a
hidden independent simulator oracle. Facts change at predetermined task indices;
source corruption, partitions, contradictory observations and rare prohibitions
are injected by the simulator. Agents never see the hidden solution table.
Procedure proposals remain candidates unless reviewed and tested externally.

Development seeds: 201, 211, 223, 227, 229. Holdout seeds: 307, 311, 313, 317, 331.
Holdout should use independently authored scenario templates and domain-neutral
skins, not a cosmetic renaming of development. Freeze generator version, split,
task order, budgets and SHA-256 before tuning any memory mechanism.

Arms: no memory, ungoverned shared lexical/vector store, local summary/static
procedure analogue, governed Memory Fabric, oracle. The analogue is labelled a
local design, not a TencentDB reproduction. Match model, context and content-read
budgets, tools, task order, permissions and retry rules. The oracle gets the same
mechanisms and budgets, differing only in hidden knowledge.

Primary metric: safe successful tasks per fixed-budget episode. Report ordinary
success separately, unsafe effects, false withdrawals, useful minority survival,
recovery delay, propagation steps, per-agent and worst-agent outcomes, duplicate
work, retained facts, all input/output/cache tokens, ingestion/maintenance work
and cost per safe success including failed calls. Use paired seed-cluster
intervals, fixed family slices and traces of every failure.

Run every baseline and oracle on development before choosing a threshold. If a
simple baseline saturates the primary metric, stop and publish INCONCLUSIVE;
do not modify the held-out split. Otherwise commit a separate measured-headroom
registration before running candidate treatments on holdout. No arm may beat
the oracle; such a result invalidates the ceiling. Zero privilege/erasure/action
fence regressions are a separate mandatory gate, never averaged against success.
