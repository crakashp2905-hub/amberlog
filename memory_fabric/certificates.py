"""Evidence certificates and their deterministic verifier (plan R1, Task 3).

An `ExposureToken` binds one decision about one memory. A consequential action
usually rests on several memories, and on what *they* were derived from, so the
question at action time is about a set: is every piece of evidence still
current, still authorised for this caller, and is the support still independent
enough? An `EvidenceCertificate` records that set — evidence ids and versions,
their recorded premises, their source roots, the policy and the log position —
and `CertificateVerifier` re-answers the question against the store.

**What a certificate is not.**

- It is *not proof that a claim is true.* It is a record that declared checks
  passed against a specific log state and policy.
- It is *not a capability.* It carries no authority and no signature: the
  verifier recomputes every check from authoritative state and never reads a
  "passed" field from the certificate, so a forged or LLM-written certificate
  can only *name* evidence, which is then checked. A certificate that names
  current, authorised evidence verifies whoever wrote it — which is correct,
  because it is the evidence that is being checked, not the certificate.
- It does *not authorise a tool.* That is `actions.ActionGate`, which requires a
  separate tool grant before it looks at evidence at all.

**Selective versus blanket reassessment.** When a recorded premise has been
withdrawn, `blanket` mode refuses outright. `selective` mode (the default)
defers to the truth-maintenance recomputation that already ran when the premise
was withdrawn (`justification.py`): if the evidence memory is still usable, its
support survived — an independent premise carried it — and the action may
proceed; if not, the evidence check refuses it. Task 5 measures the difference
rather than asserting one.

**Failure is closed.** An unknown certificate version, a malformed field, an
oversized certificate, or an exception while reading authoritative state each
produce a refusal with a stable reason code. The residual race — a retraction
committed after `verify` returns and before the tool runs — is documented in
docs/SAFETY_AND_SECURITY.md (S14), not solved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .enforcement import RiskLevel, Verdict
from .model import BLOCKED_STATES

CERTIFICATE_VERSION = 1
SUPPORTED_VERSIONS = frozenset({1})

MAX_EVIDENCE = 64
"""Bounds the work one verification can demand (S9)."""

MAX_DEPENDENCIES = 512
MAX_DEPENDENCY_DEPTH = 8
MAX_ID_LENGTH = 128

ROLES = frozenset({"supports", "context"})
MODES = frozenset({"selective", "blanket"})

# Checks a certificate may require. `evidence_current`, `authorized_for_caller`
# and `policy_current` always run; the others run when required.
CHECK_EVIDENCE_CURRENT = "evidence_current"
CHECK_DEPENDENCIES_CURRENT = "dependencies_current"
CHECK_INDEPENDENT_SUPPORT = "independent_support"
CHECK_AUTHORIZED = "authorized_for_caller"
CHECK_POLICY = "policy_current"
KNOWN_CHECKS = frozenset({
    CHECK_EVIDENCE_CURRENT, CHECK_DEPENDENCIES_CURRENT, CHECK_INDEPENDENT_SUPPORT,
    CHECK_AUTHORIZED, CHECK_POLICY,
})
ALWAYS = (CHECK_AUTHORIZED, CHECK_POLICY, CHECK_EVIDENCE_CURRENT)

# Reason codes. Stable strings: an operator filters on them.
OK = "ok"
MALFORMED = "malformed_certificate"
UNKNOWN_VERSION = "unknown_certificate_version"
TOO_LARGE = "certificate_too_large"
UNKNOWN_CHECK = "unknown_required_check"
WRONG_STORE = "wrong_store"
WRONG_AGENT = "wrong_agent"
WRONG_TENANT = "wrong_tenant"
EXPIRED = "certificate_expired"
POLICY_CHANGED = "policy_changed"
NO_SUPPORTING_EVIDENCE = "no_supporting_evidence"
EVIDENCE_NOT_FOUND = "evidence_not_found"
EVIDENCE_WITHDRAWN = "evidence_withdrawn"
EVIDENCE_VERSION_MOVED = "evidence_version_moved"
EVIDENCE_NOT_USABLE = "evidence_not_usable"
DEPENDENCY_WITHDRAWN = "dependency_withdrawn"
DEPENDENCY_VERSION_MOVED = "dependency_version_moved"
DEPENDENCY_NOT_FOUND = "dependency_not_found"
INSUFFICIENT_INDEPENDENT_SUPPORT = "insufficient_independent_support"
STATE_UNAVAILABLE = "state_unavailable"


class CertificateError(ValueError):
    """A certificate that cannot be parsed. Carries a reason code."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class EvidenceRef:
    memory_id: str
    version: int
    role: str = "supports"

    def to_json(self) -> dict[str, Any]:
        return {"memory_id": self.memory_id, "version": self.version, "role": self.role}


@dataclass(frozen=True)
class Dependency:
    """A recorded premise: (memory, version) some evidence was derived from."""

    memory_id: str
    version: int

    def to_json(self) -> dict[str, Any]:
        return {"memory_id": self.memory_id, "version": self.version}


@dataclass(frozen=True)
class EvidenceCertificate:
    claim_id: str
    agent_id: str
    store_id: str
    evidence: tuple[EvidenceRef, ...]
    policy_id: str
    snapshot_watermark: int
    issued_at_ms: int
    tenant_id: str | None = None
    dependencies: tuple[Dependency, ...] = ()
    source_roots: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ALWAYS
    min_independent_sources: int = 1
    expires_at_ms: int | None = None
    certificate_version: int = CERTIFICATE_VERSION

    @property
    def supporting(self) -> tuple[EvidenceRef, ...]:
        return tuple(e for e in self.evidence if e.role == "supports")

    def to_json(self) -> dict[str, Any]:
        return {
            "certificate_version": self.certificate_version,
            "claim_id": self.claim_id,
            "agent_id": self.agent_id,
            "store_id": self.store_id,
            "tenant_id": self.tenant_id,
            "evidence": [e.to_json() for e in self.evidence],
            "dependencies": [d.to_json() for d in self.dependencies],
            "source_roots": list(self.source_roots),
            "policy_id": self.policy_id,
            "snapshot_watermark": self.snapshot_watermark,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "required_checks": list(self.required_checks),
            "min_independent_sources": self.min_independent_sources,
        }

    def digest(self) -> str:
        """A stable content hash, for audit records to refer to."""
        canonical = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def from_json(cls, data: Any) -> "EvidenceCertificate":
        """Strict parse. Unknown fields are refused, not ignored: a field such
        as `"checks_passed": true` is exactly what the verifier must never be
        seen to read, so a certificate carrying one is malformed."""
        return _parse(data)


_FIELDS = frozenset({
    "certificate_version", "claim_id", "agent_id", "store_id", "tenant_id",
    "evidence", "dependencies", "source_roots", "policy_id",
    "snapshot_watermark", "issued_at_ms", "expires_at_ms", "required_checks",
    "min_independent_sources",
})
_REQUIRED = frozenset({
    "certificate_version", "claim_id", "agent_id", "store_id", "evidence",
    "policy_id", "snapshot_watermark", "issued_at_ms",
})


def _ident(value: Any, name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CertificateError(MALFORMED, f"{name} must be a string")
    if (not value and not allow_empty) or len(value) > MAX_ID_LENGTH:
        raise CertificateError(MALFORMED, f"{name} has an invalid length")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    # bool is an int subclass; `true` is not a version number.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CertificateError(MALFORMED, f"{name} must be an integer >= {minimum}")
    return value


def _list(value: Any, name: str, limit: int) -> list[Any]:
    if not isinstance(value, list):
        raise CertificateError(MALFORMED, f"{name} must be a list")
    if len(value) > limit:
        raise CertificateError(TOO_LARGE, f"{name} has more than {limit} entries")
    return value


def _parse(data: Any) -> EvidenceCertificate:
    if not isinstance(data, Mapping):
        raise CertificateError(MALFORMED, "a certificate is a JSON object")
    # Version first, so a future certificate is reported as unknown rather than
    # as malformed because of fields this version does not know.
    if "certificate_version" not in data:
        raise CertificateError(MALFORMED, "certificate_version is missing")
    version = data["certificate_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise CertificateError(MALFORMED, "certificate_version must be an integer")
    if version not in SUPPORTED_VERSIONS:
        raise CertificateError(UNKNOWN_VERSION, f"version {version} is not supported")
    unknown = set(data) - _FIELDS
    if unknown:
        raise CertificateError(MALFORMED, f"unknown fields: {sorted(unknown)[:5]}")
    missing = _REQUIRED - set(data)
    if missing:
        raise CertificateError(MALFORMED, f"missing fields: {sorted(missing)}")

    evidence = []
    for i, item in enumerate(_list(data["evidence"], "evidence", MAX_EVIDENCE)):
        if not isinstance(item, Mapping) or set(item) - {"memory_id", "version", "role"}:
            raise CertificateError(MALFORMED, f"evidence[{i}] is not an evidence reference")
        role = item.get("role", "supports")
        if role not in ROLES:
            raise CertificateError(MALFORMED, f"evidence[{i}].role is not one of {sorted(ROLES)}")
        evidence.append(EvidenceRef(
            _ident(item.get("memory_id"), f"evidence[{i}].memory_id"),
            _int(item.get("version"), f"evidence[{i}].version", 1), role))

    dependencies = []
    for i, item in enumerate(_list(data.get("dependencies", []), "dependencies",
                                   MAX_DEPENDENCIES)):
        if not isinstance(item, Mapping) or set(item) - {"memory_id", "version"}:
            raise CertificateError(MALFORMED, f"dependencies[{i}] is not a dependency")
        dependencies.append(Dependency(
            _ident(item.get("memory_id"), f"dependencies[{i}].memory_id"),
            _int(item.get("version"), f"dependencies[{i}].version", 1)))

    roots = tuple(_ident(r, "source_roots[]") for r in
                  _list(data.get("source_roots", []), "source_roots", MAX_DEPENDENCIES))
    checks = tuple(_ident(c, "required_checks[]") for c in
                   _list(data.get("required_checks", list(ALWAYS)), "required_checks", 16))
    unknown_checks = set(checks) - KNOWN_CHECKS
    if unknown_checks:
        # A check this verifier cannot run is a check that did not pass.
        raise CertificateError(UNKNOWN_CHECK, f"cannot run {sorted(unknown_checks)}")

    tenant = data.get("tenant_id")
    expires = data.get("expires_at_ms")
    return EvidenceCertificate(
        certificate_version=version,
        claim_id=_ident(data["claim_id"], "claim_id"),
        agent_id=_ident(data["agent_id"], "agent_id"),
        store_id=_ident(data["store_id"], "store_id"),
        tenant_id=None if tenant is None else _ident(tenant, "tenant_id"),
        evidence=tuple(evidence),
        dependencies=tuple(dependencies),
        source_roots=roots,
        policy_id=_ident(data["policy_id"], "policy_id", allow_empty=True),
        snapshot_watermark=_int(data["snapshot_watermark"], "snapshot_watermark"),
        issued_at_ms=_int(data["issued_at_ms"], "issued_at_ms"),
        expires_at_ms=None if expires is None else _int(expires, "expires_at_ms"),
        required_checks=checks,
        min_independent_sources=_int(data.get("min_independent_sources", 1),
                                     "min_independent_sources", 0),
    )


@dataclass(frozen=True)
class EvidenceFinding:
    memory_id: str
    version: int
    reason_code: str
    detail: str = ""


@dataclass(frozen=True)
class CertificateVerification:
    """The verifier's answer. **Never carries memory content.**"""

    ok: bool
    reason_codes: tuple[str, ...]
    checks: Mapping[str, bool]
    findings: tuple[EvidenceFinding, ...] = ()
    verified_at_watermark: int | None = None
    certificate_digest: str = ""
    independent_sources: int = 0
    mode: str = "selective"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else OK

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_codes": list(self.reason_codes),
            "checks": dict(self.checks),
            "findings": [f.__dict__ for f in self.findings],
            "verified_at_watermark": self.verified_at_watermark,
            "certificate_digest": self.certificate_digest,
            "independent_sources": self.independent_sources,
            "mode": self.mode,
            "notes": list(self.notes),
        }


def refused(reason_code: str, detail: str = "", digest: str = "") -> CertificateVerification:
    return CertificateVerification(
        ok=False, reason_codes=(reason_code,), checks={},
        findings=(EvidenceFinding("", 0, reason_code, detail),) if detail else (),
        certificate_digest=digest,
    )


def _premises(fabric: Any, memory_id: str) -> list[tuple[str, int]]:
    """Recorded premises of one memory, transitively, bounded."""
    out: list[tuple[str, int]] = []
    seen: set[str] = {memory_id}
    frontier = [memory_id]
    for _ in range(MAX_DEPENDENCY_DEPTH):
        nxt: list[str] = []
        for mid in frontier:
            memory = fabric.state.memories.get(mid)
            if memory is None:
                continue
            for pid, pver in memory.provenance.parents:
                if pid in seen:
                    continue
                seen.add(pid)
                out.append((pid, int(pver)))
                nxt.append(pid)
                if len(out) >= MAX_DEPENDENCIES:
                    return out
        frontier = nxt
        if not frontier:
            break
    return out


class CertificateVerifier:
    """Recomputes every check from the store. Deterministic for a given log."""

    def __init__(self, fabric: Any, mode: str = "selective") -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")
        self.fabric = fabric
        self.mode = mode

    # --- issuing ---------------------------------------------------------

    def issue(
        self,
        claim_id: str,
        evidence: Iterable[str | tuple[str, str]],
        agent_id: str,
        tenant_id: str | None = None,
        required_checks: Sequence[str] = ALWAYS,
        min_independent_sources: int = 1,
        ttl_ms: int | None = 300_000,
    ) -> EvidenceCertificate:
        """Record the evidence as it stands now. Does not check it: issuing an
        unusable certificate is allowed, and `verify` is where it is refused."""
        fabric = self.fabric
        refs: list[EvidenceRef] = []
        visible: set[str] = set()
        for item in evidence:
            memory_id, role = (item, "supports") if isinstance(item, str) else item
            memory = fabric.state.memories.get(memory_id)
            if memory is not None and tenant_id is not None and memory.tenant_id != tenant_id:
                # Recorded exactly as a missing memory is, so issuing cannot be
                # used to learn whether another tenant's id exists, its
                # version, its premises or its roots.
                memory = None
            if memory is not None:
                visible.add(memory_id)
            refs.append(EvidenceRef(memory_id, memory.version if memory else 1, role))
        deps: dict[str, int] = {}
        roots: set[str] = set()
        for ref in refs:
            if ref.memory_id not in visible:
                continue
            for pid, pver in _premises(fabric, ref.memory_id):
                deps.setdefault(pid, pver)
            if ref.role == "supports":
                roots.add(fabric.source_root(ref.memory_id))
        checks = tuple(dict.fromkeys([*ALWAYS, *required_checks]))
        now = fabric.now()
        return EvidenceCertificate(
            claim_id=claim_id,
            agent_id=agent_id,
            store_id=fabric.store_id,
            tenant_id=tenant_id,
            evidence=tuple(refs),
            dependencies=tuple(Dependency(k, v) for k, v in sorted(deps.items())),
            source_roots=tuple(sorted(roots)),
            policy_id=getattr(fabric.policy, "id", ""),
            snapshot_watermark=fabric.log.head_seq,
            issued_at_ms=now,
            expires_at_ms=None if ttl_ms is None else now + ttl_ms,
            required_checks=checks,
            min_independent_sources=min_independent_sources,
        )

    # --- verifying -------------------------------------------------------

    def verify(
        self,
        certificate: EvidenceCertificate | Mapping[str, Any],
        agent_id: str,
        tenant_id: str | None = None,
        risk: RiskLevel = RiskLevel.HIGH,
    ) -> CertificateVerification:
        if not isinstance(certificate, EvidenceCertificate):
            try:
                certificate = EvidenceCertificate.from_json(certificate)
            except CertificateError as exc:
                return refused(exc.reason_code, exc.detail)
        digest = certificate.digest()
        try:
            return self._verify(certificate, agent_id, tenant_id, risk, digest)
        except Exception as exc:  # fail closed: unknown state is a refusal
            return refused(STATE_UNAVAILABLE, type(exc).__name__, digest)

    def _verify(
        self,
        cert: EvidenceCertificate,
        agent_id: str,
        tenant_id: str | None,
        risk: RiskLevel,
        digest: str,
    ) -> CertificateVerification:
        fabric = self.fabric
        watermark = fabric.log.head_seq
        reasons: list[str] = []
        findings: list[EvidenceFinding] = []
        notes: list[str] = []
        checks: dict[str, bool] = {}

        # Authorisation of the caller to rely on this certificate. Checked
        # before evidence so a refusal for the wrong caller reveals nothing
        # about the evidence.
        bound = True
        if cert.store_id != fabric.store_id:
            reasons.append(WRONG_STORE)
            bound = False
        if cert.agent_id != agent_id:
            reasons.append(WRONG_AGENT)
            bound = False
        if cert.tenant_id != tenant_id:
            reasons.append(WRONG_TENANT)
            bound = False
        if cert.expires_at_ms is not None and fabric.now() >= cert.expires_at_ms:
            reasons.append(EXPIRED)
            bound = False
        checks[CHECK_AUTHORIZED] = bound
        if not bound:
            return CertificateVerification(
                ok=False, reason_codes=tuple(reasons), checks=checks,
                verified_at_watermark=watermark, certificate_digest=digest, mode=self.mode)

        policy_ok = cert.policy_id == getattr(fabric.policy, "id", "")
        checks[CHECK_POLICY] = policy_ok
        if not policy_ok:
            reasons.append(POLICY_CHANGED)

        # Evidence: each supporting memory is re-checked through the enforcer,
        # the same layer every other read uses, scoped to the same tenant.
        supporting = cert.supporting
        evidence_ok = bool(supporting)
        if not supporting:
            reasons.append(NO_SUPPORTING_EVIDENCE)
        usable_ids: list[str] = []
        for ref in supporting:
            decision = fabric.enforcer.check(ref.memory_id, risk=risk, tenant_id=tenant_id)
            code = ""
            if decision.reason_code == "not_found":
                code = EVIDENCE_NOT_FOUND
            elif decision.reason_code == "wrong_tenant":
                code = WRONG_TENANT
            elif decision.version != ref.version:
                code = EVIDENCE_VERSION_MOVED
            elif decision.verdict is not Verdict.USABLE:
                state = fabric.state.memories[ref.memory_id].lifecycle_state
                code = EVIDENCE_WITHDRAWN if state in BLOCKED_STATES else EVIDENCE_NOT_USABLE
            if code:
                evidence_ok = False
                findings.append(EvidenceFinding(
                    ref.memory_id, ref.version, code,
                    "" if code == WRONG_TENANT else decision.reason_code))
                if code not in reasons:
                    reasons.append(code)
            else:
                usable_ids.append(ref.memory_id)
        checks[CHECK_EVIDENCE_CURRENT] = evidence_ok

        if CHECK_DEPENDENCIES_CURRENT in cert.required_checks or self.mode == "blanket":
            deps_ok = True
            for dep in cert.dependencies:
                memory = fabric.state.memories.get(dep.memory_id)
                code = ""
                if memory is None:
                    code = DEPENDENCY_NOT_FOUND
                elif memory.lifecycle_state in BLOCKED_STATES:
                    code = DEPENDENCY_WITHDRAWN
                elif memory.version != dep.version:
                    code = DEPENDENCY_VERSION_MOVED
                if not code:
                    continue
                if self.mode == "selective" and evidence_ok:
                    # Truth maintenance already reassessed everything this
                    # premise supported when it changed. Evidence that is still
                    # usable kept its support from somewhere independent.
                    notes.append(f"{code}:{dep.memory_id}:support_survived")
                    continue
                deps_ok = False
                findings.append(EvidenceFinding(dep.memory_id, dep.version, code))
                if code not in reasons:
                    reasons.append(code)
            checks[CHECK_DEPENDENCIES_CURRENT] = deps_ok

        roots = {fabric.source_root(mid) for mid in usable_ids}
        if CHECK_INDEPENDENT_SUPPORT in cert.required_checks:
            independent_ok = len(roots) >= cert.min_independent_sources
            checks[CHECK_INDEPENDENT_SUPPORT] = independent_ok
            if not independent_ok:
                reasons.append(INSUFFICIENT_INDEPENDENT_SUPPORT)

        if watermark != cert.snapshot_watermark:
            notes.append(f"log moved from {cert.snapshot_watermark} to {watermark}; rechecked")

        return CertificateVerification(
            ok=not reasons,
            reason_codes=tuple(reasons) or (OK,),
            checks=checks,
            findings=tuple(findings),
            verified_at_watermark=watermark,
            certificate_digest=digest,
            independent_sources=len(roots),
            mode=self.mode,
            notes=tuple(notes),
        )
