# Decision models, System 1, UTCP, and governed Code Mode

Status: experimental. These components propose and transport actions; they do
not grant authority.

## Deterministic boundary

`memory_fabric.decision_models` defines typed options, probability-bearing
proposals, explicit abstention, calibration scoring, and risk-sensitive
System 1 to System 2 escalation. Every proposal is validated: probabilities
must be finite, cover exactly the declared options, and sum to one. Ties in the
dependency-free baseline abstain.

This API deliberately has no execution method. A selected option that names an
action must still be converted into an `ActionRequest` and authorized by
`ActionGate`. Model probability cannot add a grant, approve evidence, mint a
credential, or weaken a tool rule.

## Pinned UTCP subset

The adapter targets UTCP `1.0.x` manuals and requires both `utcp_version` and
`manual_version`. It reads tool `inputs` and either the current
`tool_call_template` form or the RFC's `tool_transport` spelling. Discovery is
pure parsing: it performs no call and grants no tool.

The pinned primary sources are:

- UTCP RFC 1.0.0: <https://www.utcp.io/about/RFC>
- UTCP 1.0 implementation guide: <https://www.utcp.io/next/implementation>
- Official specification repository: <https://github.com/universal-tool-calling-protocol/utcp-specification>

The specification was checked on 2026-10-31. UTCP remains a draft and its
manual vocabulary has changed before, so unsupported versions fail closed.

## Governed Code Mode

`CodeModePlan` is intentionally smaller than the upstream TypeScript sandbox.
It accepts a sequence of calls with literal keyword arguments. Imports,
attribute access, positional or expanded arguments, loops, expressions, file
access, network access, and arbitrary Python execution are rejected.

Each call is executed separately by `GovernedToolRuntime`. Its exact arguments
are bound into `ActionRequest`, authorization is rechecked immediately before
execution, and an idempotency key flows through `ActionGate.execute`. A loop or
retry can therefore never inherit authorization from an earlier effect.

## Research status

The API and security invariants are implemented and locally testable. Claims
about Laya, Jev, encoder models, model-family robustness, latency, token cost,
or comparative MCP/UTCP/Code Mode efficiency require registered datasets and
runs. They remain research gates rather than being inferred from this API.
