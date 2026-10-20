"""Memory branches: isolated changes, immutable commits, and a governance-aware three-way merge.

A branch is a line of work on top of the store's main state, never a second
store and never a way around its rules
(docs/architecture/ADR-001-branch-commit-model.md):

- A branch's changes are **ordinary memories**, written through `remember`
  (so screened, sealed and erasable) as **candidates** tagged with the
  branch. Candidates are not exposable, so nothing on a branch reaches main
  retrieval, any other branch, or an action until it is merged.
- A **commit** is immutable and content-addressed: SHA-256 over the branch,
  tenant, parents, base and its changes (ids and digests, never content).
  Its only parent is the branch head it was made on.
- The **head moves by compare-and-swap** inside the store's write
  transaction, which holds the write lock and catches up with other
  processes first. A commit made on a head that moved is refused
  (`HeadMoved`), so two writers cannot lose each other's work.
- A **merge** compares three states for every change: main at the branch's
  base, the branch, and main now. Each change gets a class (`identical`,
  `compatible`, `content_conflict`, `evidence_conflict`,
  `governance_conflict`, `dependency_conflict`, `unknown`) and a
  **policy** turns the class into a decision (`allow`, `allow_with_warning`,
  `preserve_conflict`, `require_review`, `reject`, `cannot_determine`).
  Tenant and lifecycle checks are classes, decided before any policy and
  rejected whatever the policy says.
- **Preview, then apply.** A preview has a digest of the branch head and
  every main record it touches. Apply recomputes it under the write lock and
  refuses (`StalePreview`) if anything moved. An idempotency key replays the
  first result for the same preview and is refused for a different one.
- Applying uses the store's own operations: an addition is validated, a
  revision is `revise`, a withdrawal is `quarantine` (which propagates to
  descendants and peers as any withdrawal does).
- **Revert** is compensating: additions are deprecated and revisions are
  revised back to the content they replaced. Withdrawals are not undone;
  releasing a quarantined memory is a review decision.
- **History is not permission.** `snapshot` reports what a commit recorded
  and, separately, whether each memory is admissible now. A withdrawn
  memory can never return to retrieval through a merge: a change that would
  revise or re-add it is a governance conflict.

Not supported yet: a branch of a branch, and merging into anything but main.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator, Protocol

from . import events as ev
from .conflicts import find_conflicts
from .events import EventType
from .identity import DEFAULT_TENANT
from .ids import new_ulid
from .model import EXPOSABLE_STATES, LifecycleState

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .model import Memory

BRANCH_KEY = "branch"
POLICY_VERSION = "default-merge-v1"
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

CLASSES = ("identical", "compatible", "content_conflict", "evidence_conflict",
           "governance_conflict", "dependency_conflict", "unknown")
DECISIONS = ("allow", "allow_with_warning", "preserve_conflict", "require_review",
             "reject", "cannot_determine")
APPLIED = frozenset({"allow", "allow_with_warning"})


class BranchError(Exception):
    code = "BRANCH_ERROR"


class HeadMoved(BranchError):
    """The branch head changed after it was read. Re-read it; nothing was written."""

    code = "HEAD_MOVED"


class StalePreview(BranchError):
    """The branch or a main record changed after the preview. Preview again."""

    code = "STALE_PREVIEW"


class IdempotencyConflict(BranchError):
    """The key was used for a different merge."""

    code = "IDEMPOTENCY_CONFLICT"


class BranchPermission(BranchError):
    code = "BRANCH_NOT_PERMITTED"


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _content_digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


@dataclass
class Branch:
    name: str
    tenant_id: str
    owner: str
    base_seq: int
    head: str | None = None
    members: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()
    closed: bool = False
    commits: list[dict[str, Any]] = field(default_factory=list)

    def may_write(self, agent: str) -> bool:
        return not self.closed and (agent == self.owner or agent in self.members)

    def may_read(self, agent: str) -> bool:
        return agent == self.owner or agent in self.members or agent in self.reviewers

    def may_merge(self, agent: str) -> bool:
        """Owner or a named reviewer. Members can write but not merge into main."""
        return agent == self.owner or agent in self.reviewers

    @property
    def changes(self) -> list[dict[str, Any]]:
        return [c for commit in self.commits for c in commit["changes"]]

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "tenant_id": self.tenant_id, "owner": self.owner,
                "members": list(self.members), "reviewers": list(self.reviewers),
                "base_seq": self.base_seq, "head": self.head,
                "closed": self.closed, "commits": len(self.commits)}


@dataclass
class Change:
    index: int
    op: str
    memory_id: str | None
    candidate_id: str | None
    klass: str = "unknown"
    decision: str = "cannot_determine"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"index": self.index, "op": self.op, "memory_id": self.memory_id,
                "candidate_id": self.candidate_id, "class": self.klass,
                "decision": self.decision, "reason": self.reason, "warnings": self.warnings}


@dataclass
class MergePreview:
    branch: str
    branch_head: str | None
    base_seq: int
    changes: list[Change]
    digest: str
    policy_version: str

    def to_json(self) -> dict[str, Any]:
        return {"branch": self.branch, "branch_head": self.branch_head,
                "base_seq": self.base_seq, "digest": self.digest,
                "policy_version": self.policy_version,
                "changes": [c.to_json() for c in self.changes],
                "summary": {k: sum(1 for c in self.changes if c.decision == k)
                            for k in DECISIONS}}


class MergePolicy(Protocol):
    version: str

    def decide(self, change: Change) -> tuple[str, str]:
        """(decision, reason) for a change whose class is set. Never sees tenant refusals."""


class DefaultMergePolicy:
    """Never picks a winner between disagreeing claims; fails closed on anything unknown."""

    version = POLICY_VERSION
    _MAP = {"identical": ("allow", "already in main; nothing to apply"),
            "compatible": ("allow", "main has not changed this since the branch's base"),
            "dependency_conflict": ("allow_with_warning",
                                    "applies, and memories derived from it are re-examined"),
            "evidence_conflict": ("preserve_conflict",
                                  "disagrees with main; both claims kept for review"),
            "content_conflict": ("require_review",
                                 "main changed this since the branch's base"),
            "governance_conflict": ("reject", "not admissible now"),
            "unknown": ("cannot_determine", "unrecognised change; refused")}

    def decide(self, change: Change) -> tuple[str, str]:
        return self._MAP.get(change.klass, self._MAP["unknown"])


class _Staged:
    """The changes of one commit, written when the `with` block exits."""

    def __init__(self, branches: "Branches", branch: Branch, actor: str) -> None:
        self._b, self._branch, self._actor = branches, branch, actor
        self.changes: list[dict[str, Any]] = []

    def _candidate(self, content: str, extra: dict[str, Any], **kwargs: Any) -> str:
        context = dict(kwargs.pop("context", None) or {})
        context[BRANCH_KEY] = {"name": self._branch.name, **extra}
        return self._b.fabric.remember(self._actor, content, context=context,
                                       auto_activate=False, tenant_id=self._branch.tenant_id,
                                       scope=kwargs.pop("scope", "team"), **kwargs)

    def add(self, content: str, **kwargs: Any) -> str:
        cid = self._candidate(content, {"op": "add"}, **kwargs)
        self.changes.append({"op": "add", "candidate_id": cid,
                             "digest": _content_digest(content)})
        return cid

    def revise(self, memory_id: str, content: str) -> str:
        target = self._b.fabric.get(memory_id)
        self._b._same_tenant(self._branch, target)
        cid = self._candidate(content, {"op": "revise", "revises": memory_id,
                                        "base_version": target.version})
        self.changes.append({"op": "revise", "memory_id": memory_id,
                             "base_version": target.version, "candidate_id": cid,
                             "digest": _content_digest(content)})
        return cid

    def withdraw(self, memory_id: str, reason: str) -> None:
        target = self._b.fabric.get(memory_id)
        self._b._same_tenant(self._branch, target)
        self.changes.append({"op": "withdraw", "memory_id": memory_id,
                             "base_version": target.version,
                             "digest": _content_digest(reason), "reason": reason})


class Branches:
    """Branch operations on one fabric. State is folded from the log on every call."""

    def __init__(self, fabric: "MemoryFabric", policy: MergePolicy | None = None) -> None:
        self.fabric = fabric
        self.policy: MergePolicy = policy or DefaultMergePolicy()

    # --- state ----------------------------------------------------------

    def _fold(self) -> dict[tuple[str, str], Branch]:
        self.fabric.refresh()
        out: dict[tuple[str, str], Branch] = {}
        for e in self.fabric.log.read_types([EventType.BRANCH_CREATED, EventType.BRANCH_COMMITTED,
                                             EventType.BRANCH_HEAD_MOVED,
                                             EventType.BRANCH_CLOSED]):
            p = e.payload
            key = (p["tenant_id"], p["branch"])
            if e.type == EventType.BRANCH_CREATED:
                out[key] = Branch(p["branch"], p["tenant_id"], p["owner"], int(p["base_seq"]),
                                  members=tuple(p.get("members") or ()),
                                  reviewers=tuple(p.get("reviewers") or ()))
            elif key not in out:
                continue
            elif e.type == EventType.BRANCH_COMMITTED:
                out[key].commits.append(dict(p["commit"]))
            elif e.type == EventType.BRANCH_HEAD_MOVED:
                out[key].head = p["to"]
            elif e.type == EventType.BRANCH_CLOSED:
                out[key].closed = True
        return out

    def get(self, name: str, tenant_id: str = DEFAULT_TENANT) -> Branch:
        branch = self._fold().get((tenant_id, name))
        if branch is None:
            raise KeyError(name)
        return branch

    def list_branches(self, tenant_id: str = DEFAULT_TENANT, agent: str | None = None
                      ) -> list[Branch]:
        return [b for (t, _), b in sorted(self._fold().items())
                if t == tenant_id and (agent is None or b.may_read(agent))]

    def _same_tenant(self, branch: Branch, memory: "Memory") -> None:
        if memory.tenant_id != branch.tenant_id:
            raise BranchPermission(f"{memory.id} is not in tenant {branch.tenant_id}")

    # --- operations -----------------------------------------------------

    def create(self, name: str, owner: str, tenant_id: str = DEFAULT_TENANT,
               members: tuple[str, ...] = (), reviewers: tuple[str, ...] = (),
               from_seq: int | None = None) -> Branch:
        if not _NAME.match(name) or name == "main":
            raise BranchError(f"invalid branch name {name!r}")
        with self.fabric._transaction():
            if (tenant_id, name) in self._fold():
                raise BranchError(f"branch {name} exists")
            head = self.fabric.log.head_seq
            base = head if from_seq is None else int(from_seq)
            if not 0 <= base <= head:
                raise BranchError(f"base {base} is outside the log (0..{head})")
            self.fabric._emit(ev.branch_event(EventType.BRANCH_CREATED, self.fabric.now(), owner, {
                "branch": name, "tenant_id": tenant_id, "owner": owner,
                "members": list(members), "reviewers": list(reviewers), "base_seq": base}))
        return self.get(name, tenant_id)

    @contextmanager
    def commit(self, name: str, actor: str, message: str, tenant_id: str = DEFAULT_TENANT,
               expected_head: str | None | object = ...) -> Iterator[_Staged]:
        """Stage changes in the block; on exit, write them, the commit and the head move atomically.

        `expected_head` defaults to the head when the block was entered. If
        another writer committed in between, nothing is written (`HeadMoved`).
        """
        branch = self.get(name, tenant_id)
        if not branch.may_write(actor):
            raise BranchPermission(f"{actor} may not write to {name}")
        expected = branch.head if expected_head is ... else expected_head
        with self.fabric._transaction():
            staged = _Staged(self, branch, actor)
            yield staged
            current = self.get(name, tenant_id)
            if current.head != expected:
                raise HeadMoved(f"{name} moved from {expected} to {current.head}")
            if not staged.changes:
                raise BranchError("a commit needs at least one change")
            body = {"branch": name, "tenant_id": tenant_id,
                    "parents": [expected] if expected else [], "base_seq": branch.base_seq,
                    "changes": staged.changes, "author": actor, "message": message}
            commit = {**body, "commit_id": "c_" + _digest(body)[:40],
                      "created_at": self.fabric.now(), "schema_version": 1}
            now = self.fabric.now()
            self.fabric._emit(
                ev.branch_event(EventType.BRANCH_COMMITTED, now, actor,
                                {"branch": name, "tenant_id": tenant_id, "commit": commit}),
                ev.branch_event(EventType.BRANCH_HEAD_MOVED, now, actor,
                                {"branch": name, "tenant_id": tenant_id, "from": expected,
                                 "to": commit["commit_id"]}))

    def history(self, name: str, tenant_id: str = DEFAULT_TENANT) -> list[dict[str, Any]]:
        return list(reversed(self.get(name, tenant_id).commits))

    def merge_base(self, name: str, tenant_id: str = DEFAULT_TENANT) -> int:
        return self.get(name, tenant_id).base_seq

    def close(self, name: str, actor: str, tenant_id: str = DEFAULT_TENANT) -> int:
        """Close the branch and deprecate its unmerged candidates. History stays."""
        branch = self.get(name, tenant_id)
        if actor != branch.owner:
            raise BranchPermission("only the owner closes a branch")
        n = 0
        with self.fabric._transaction():
            for c in branch.changes:
                cid = c.get("candidate_id")
                if cid and self.fabric.get(cid).lifecycle_state is LifecycleState.CANDIDATE:
                    self.fabric.forget(cid, reason=f"branch {name} closed", actor=actor)
                    n += 1
            self.fabric._emit(ev.branch_event(EventType.BRANCH_CLOSED, self.fabric.now(), actor,
                                              {"branch": name, "tenant_id": tenant_id}))
        return n

    # --- reading a branch ---------------------------------------------

    def view(self, name: str, agent: str, tenant_id: str = DEFAULT_TENANT) -> list["Memory"]:
        """Main as `agent` may read it now, with the branch's changes laid over it."""
        branch = self.get(name, tenant_id)
        if not branch.may_read(agent):
            raise BranchPermission(f"{agent} may not read {name}")
        f = self.fabric
        visible = {m.id: m for m in f.state.memories.values()
                   if m.tenant_id == tenant_id and f.use(m.id, agent_id=agent, tenant_id=tenant_id,
                                                         audit=False).usable}
        for c in branch.changes:
            if c["op"] == "withdraw":
                visible.pop(c["memory_id"], None)
                continue
            cand = f.state.memories.get(c["candidate_id"])
            if cand is None or cand.lifecycle_state is not LifecycleState.CANDIDATE:
                continue  # quarantined by a screen, or merged/closed
            if c["op"] == "revise":
                if c["memory_id"] not in visible:
                    continue  # the target is not readable now; the revision cannot be either
                visible.pop(c["memory_id"], None)
            visible[cand.id] = cand
        return sorted(visible.values(), key=lambda m: (m.created_at, m.id))

    def diff(self, name: str, tenant_id: str = DEFAULT_TENANT) -> list[dict[str, Any]]:
        """Deterministic, machine-readable: one row per change, ids and digests only."""
        rows = []
        for commit in self.get(name, tenant_id).commits:
            for c in commit["changes"]:
                rows.append({"commit_id": commit["commit_id"], "op": c["op"],
                             "memory_id": c.get("memory_id"),
                             "base_version": c.get("base_version"),
                             "candidate_id": c.get("candidate_id"), "digest": c["digest"]})
        return rows

    def snapshot(self, name: str, commit_id: str, tenant_id: str = DEFAULT_TENANT
                 ) -> dict[str, Any]:
        """What a commit recorded, and separately what may be used now."""
        branch = self.get(name, tenant_id)
        idx = next((i for i, c in enumerate(branch.commits) if c["commit_id"] == commit_id), None)
        if idx is None:
            raise KeyError(commit_id)
        recorded = [c for commit in branch.commits[: idx + 1] for c in commit["changes"]]
        state = self.fabric.state.memories
        rows = []
        for c in recorded:
            ids = [i for i in (c.get("memory_id"), c.get("candidate_id")) if i]
            rows.append({**{k: c.get(k) for k in ("op", "memory_id", "candidate_id",
                                                  "base_version")},
                         "admissible_now": {i: (i in state and state[i].lifecycle_state
                                                in EXPOSABLE_STATES) for i in ids}})
        return {"branch": name, "commit_id": commit_id, "base_seq": branch.base_seq,
                "recorded": rows,
                "note": "recorded history; admissible_now is today's governance, not the "
                        "commit's"}

    # --- merging --------------------------------------------------------

    def _descendants_active(self, memory_id: str) -> list[str]:
        state = self.fabric.state
        seen: set[str] = set()
        frontier = [memory_id]
        while frontier:
            for child in state.children.get(frontier.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return sorted(m for m in seen if state.memories[m].lifecycle_state in EXPOSABLE_STATES)

    def _classify(self, branch: Branch, i: int, c: dict[str, Any]) -> Change:
        state = self.fabric.state.memories
        change = Change(i, c.get("op", "?"), c.get("memory_id"), c.get("candidate_id"))
        cand = state.get(change.candidate_id) if change.candidate_id else None
        target = state.get(change.memory_id) if change.memory_id else None

        def cls(k: str, reason: str) -> Change:
            change.klass, change.reason = k, reason
            return change

        if change.op not in ("add", "revise", "withdraw"):
            return cls("unknown", f"unknown op {change.op!r}")
        if change.op in ("add", "revise"):
            if cand is None or cand.tenant_id != branch.tenant_id:
                return cls("governance_conflict", "the branch's memory is not in this tenant")
            if cand.lifecycle_state is not LifecycleState.CANDIDATE:
                return cls("governance_conflict",
                           f"the branch's memory is {cand.lifecycle_state.value}")
        if change.op in ("revise", "withdraw"):
            if target is None or target.tenant_id != branch.tenant_id:
                return cls("governance_conflict", "target is not in this tenant")
        if change.op == "add":
            assert cand is not None
            peers = [m for m in state.values() if m.tenant_id == branch.tenant_id
                     and m.lifecycle_state in EXPOSABLE_STATES and m.id != cand.id]
            digest = _content_digest(cand.content)
            if any(_content_digest(m.content) == digest for m in peers):
                return cls("identical", "main already holds this")
            if any(cand in g for g in find_conflicts([cand, *peers])):
                return cls("evidence_conflict", "gives a different value from a main memory")
            return cls("compatible", "new")
        assert target is not None
        if change.op == "revise":
            assert cand is not None
            if target.lifecycle_state not in EXPOSABLE_STATES:
                return cls("governance_conflict",
                           f"target is {target.lifecycle_state.value}; a merge never "
                           "brings a withdrawn memory back")
            if _content_digest(target.content) == _content_digest(cand.content):
                return cls("identical", "main already says this")
            if target.version != c.get("base_version"):
                return cls("content_conflict",
                           f"main revised it since the base (v{c.get('base_version')} -> "
                           f"v{target.version})")
            below = self._descendants_active(target.id)
            if below:
                change.warnings.append(f"{len(below)} derived memories will be re-examined")
                return cls("dependency_conflict", "has active derived memories")
            return cls("compatible", "unchanged in main since the base")
        # withdraw
        if target.lifecycle_state not in EXPOSABLE_STATES:
            return cls("identical", f"already {target.lifecycle_state.value}")
        if target.version != c.get("base_version"):
            return cls("content_conflict", "main revised it since the base")
        below = self._descendants_active(target.id)
        if below:
            change.warnings.append(f"{len(below)} derived memories lose this support")
            return cls("dependency_conflict", "has active derived memories")
        return cls("compatible", "unchanged in main since the base")

    def preview_merge(self, name: str, actor: str, tenant_id: str = DEFAULT_TENANT
                      ) -> MergePreview:
        branch = self.get(name, tenant_id)
        if not branch.may_merge(actor):
            raise BranchPermission(f"{actor} may not merge {name}")
        if branch.closed:
            raise BranchError(f"{name} is closed")
        merged = self._merged_changes(branch)
        changes = []
        for i, c in enumerate(branch.changes):
            if i in merged:
                continue
            change = self._classify(branch, i, c)
            if change.klass == "governance_conflict":
                change.decision = "reject"  # before any policy: policies cannot override
            else:
                decision, reason = self.policy.decide(change)
                change.decision = decision if decision in DECISIONS else "cannot_determine"
                change.reason = f"{change.reason}; {reason}"
            changes.append(change)
        state = self.fabric.state.memories
        touched = sorted({x for ch in changes for x in (ch.memory_id, ch.candidate_id) if x}
                         | {d for ch in changes if ch.memory_id
                            for d in self._descendants_active(ch.memory_id)})
        basis = {"head": branch.head, "policy": self.policy.version,
                 "records": [[m, state[m].version, state[m].lifecycle_state.value]
                             for m in touched if m in state],
                 "changes": [ch.to_json() for ch in changes]}
        return MergePreview(name, branch.head, branch.base_seq, changes, _digest(basis),
                            self.policy.version)

    def _merges(self, branch: Branch) -> list[dict[str, Any]]:
        return [dict(e.payload) for e in self.fabric.log.read_types([EventType.MERGE_APPLIED])
                if e.payload.get("branch") == branch.name
                and e.payload.get("tenant_id") == branch.tenant_id]

    def _merged_changes(self, branch: Branch) -> set[int]:
        done: set[int] = set()
        for m in self._merges(branch):
            done |= {r["index"] for r in m["results"] if r["decision"] in APPLIED}
        return done

    def apply_merge(self, name: str, actor: str, preview_digest: str,
                    idempotency_key: str, tenant_id: str = DEFAULT_TENANT) -> dict[str, Any]:
        """Apply what the preview allowed, if the preview is still current."""
        if not actor or actor == "operator":
            raise BranchPermission("name who is merging: the decision is audited")
        with self.fabric._transaction():
            branch = self.get(name, tenant_id)
            for prior in self._merges(branch):
                if prior.get("idempotency_key") == idempotency_key:
                    if prior["preview_digest"] != preview_digest:
                        raise IdempotencyConflict(f"key {idempotency_key} was used for "
                                                  "another merge")
                    return {**prior, "replayed": True}
            preview = self.preview_merge(name, actor, tenant_id)
            if preview.digest != preview_digest:
                raise StalePreview(f"{name} or a record it touches changed since the preview")
            f = self.fabric
            results = []
            for ch in preview.changes:
                applied: str | None = None
                if ch.decision in APPLIED and ch.klass != "identical":
                    if ch.op == "add":
                        assert ch.candidate_id
                        applied = f.validate(ch.candidate_id, actor=actor,
                                             reason=f"merged from {name}").id
                    elif ch.op == "revise":
                        assert ch.memory_id and ch.candidate_id
                        cand = f.get(ch.candidate_id)
                        before = f.get(ch.memory_id).version
                        f.revise(ch.memory_id, cand.content, agent_id=cand.provenance.created_by,
                                 reason=f"merged from {name} by {actor}")
                        f.forget(ch.candidate_id, reason=f"merged into {ch.memory_id}",
                                 actor=actor)
                        applied = f"{ch.memory_id}@v{before + 1}"
                    elif ch.op == "withdraw":
                        assert ch.memory_id
                        f.quarantine(ch.memory_id, reason=f"withdrawn by merge of {name}",
                                     actor=actor)
                        applied = ch.memory_id
                results.append({**ch.to_json(), "applied": applied})
            receipt = {"merge_id": "m_" + new_ulid(), "branch": name, "tenant_id": tenant_id,
                       "branch_head": preview.branch_head, "preview_digest": preview_digest,
                       "idempotency_key": idempotency_key, "actor": actor,
                       "policy_version": preview.policy_version, "results": results,
                       "summary": {k: sum(1 for r in results if r["decision"] == k)
                                   for k in DECISIONS}}
            f._emit(ev.branch_event(EventType.MERGE_APPLIED, f.now(), actor, receipt))
        return receipt

    def revert(self, merge_id: str, actor: str, tenant_id: str = DEFAULT_TENANT
               ) -> dict[str, Any]:
        """Compensate a merge. Withdrawals are listed as not reverted."""
        merge = next((dict(e.payload) for e in self.fabric.log.read_types(
            [EventType.MERGE_APPLIED]) if e.payload.get("merge_id") == merge_id
            and e.payload.get("tenant_id") == tenant_id), None)
        if merge is None or merge.get("reverts"):
            raise KeyError(merge_id)
        if any(e.payload.get("reverts") == merge_id
               for e in self.fabric.log.read_types([EventType.MERGE_APPLIED])):
            raise BranchError(f"{merge_id} was already reverted")
        f = self.fabric
        out: dict[str, list[str]] = {"deprecated": [], "revised_back": [], "not_reverted": []}
        with f._transaction():
            for r in merge["results"]:
                if not r.get("applied"):
                    continue
                if r["op"] == "add":
                    f.forget(r["applied"], reason=f"revert of {merge_id}", actor=actor)
                    out["deprecated"].append(r["applied"])
                elif r["op"] == "revise":
                    memory_id, version = r["applied"].split("@v")
                    prior = next(m for m in f.history(memory_id) if m.version == int(version) - 1)
                    f.revise(memory_id, prior.content, agent_id=actor,
                             reason=f"revert of {merge_id}")
                    out["revised_back"].append(memory_id)
                else:
                    out["not_reverted"].append(r["applied"])
            f._emit(ev.branch_event(EventType.MERGE_APPLIED, f.now(), actor, {
                "merge_id": "m_" + new_ulid(), "branch": merge["branch"],
                "tenant_id": tenant_id, "reverts": merge_id, "actor": actor, "results": [],
                "preview_digest": "", "idempotency_key": f"revert:{merge_id}",
                "summary": {}, "reverted": out}))
        return out
