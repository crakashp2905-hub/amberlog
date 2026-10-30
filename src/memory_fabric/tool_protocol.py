"""Protocol-neutral discovery plus governed MCP/UTCP/Code Mode execution.

Discovery describes tools; it never grants them.  Every consequential call is
bound to exact arguments, authorized by ``ActionGate``, and protected by an
execution idempotency key.  Generated code can compose registered tools but
cannot import modules, access files, open sockets, or invoke arbitrary Python.
"""

from __future__ import annotations

__stability__ = "experimental"

import ast
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .actions import ActionGate, ActionRequest


class ToolProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    consequential: bool = True
    protocol: str = "native"
    transport: Mapping[str, Any] = field(default_factory=dict)


def discover_utcp(document: Mapping[str, Any]) -> tuple[ToolDescriptor, ...]:
    """Parse the pinned UTCP discovery subset without performing network I/O."""

    version = str(document.get("utcp_version", ""))
    manual_version = document.get("manual_version")
    if not version.startswith("1.0.") or not isinstance(manual_version, str):
        raise ToolProtocolError(f"unsupported UTCP version: {version or 'missing'}")
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise ToolProtocolError("UTCP document must contain a tools list")
    result: list[ToolDescriptor] = []
    names: set[str] = set()
    for raw in tools:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise ToolProtocolError("every UTCP tool needs a string name")
        name = raw["name"]
        if name in names:
            raise ToolProtocolError(f"duplicate tool: {name}")
        names.add(name)
        result.append(ToolDescriptor(
            name=name,
            description=str(raw.get("description", "")),
            input_schema=raw.get("inputs", {}),
            consequential=bool(raw.get("consequential", True)),
            protocol=f"utcp-{version}",
            transport=raw.get("tool_call_template", raw.get("tool_transport", {})),
        ))
    return tuple(result)


@dataclass(frozen=True)
class GovernedToolCall:
    tool: str
    arguments: Mapping[str, Any]
    idempotency_key: str


class GovernedToolRuntime:
    """Registry whose calls are individually authorized at execution time."""

    def __init__(self, gate: ActionGate, handlers: Mapping[str, Callable[..., Any]]) -> None:
        self.gate = gate
        self.handlers = dict(handlers)

    def execute(self, call: GovernedToolCall, *, agent_id: str,
                certificate: Any = None, approval: Any = None,
                tenant_id: str | None = None, grant: Any = None,
                retry: bool = False) -> Any:
        handler = self.handlers.get(call.tool)
        if handler is None:
            raise ToolProtocolError(f"no registered handler for {call.tool}")
        request = ActionRequest(target=call.tool, parameters=dict(call.arguments))
        return self.gate.execute(
            call.tool,
            agent_id,
            lambda _key: handler(**dict(call.arguments)),
            key=call.idempotency_key,
            certificate=certificate,
            approval=approval,
            tenant_id=tenant_id,
            request=request,
            grant=grant,
            retry=retry,
        )


class CodeModePlan:
    """Validated sequence of literal tool calls; not an arbitrary code evaluator."""

    def __init__(self, calls: Sequence[GovernedToolCall]) -> None:
        self.calls = tuple(calls)

    @classmethod
    def parse(cls, source: str) -> "CodeModePlan":
        """Accept only ``tool_name(key=value, ...)`` expression statements."""

        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise ToolProtocolError(f"invalid code-mode plan: {exc.msg}") from exc
        calls: list[GovernedToolCall] = []
        for index, statement in enumerate(tree.body):
            if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                raise ToolProtocolError("code mode permits tool-call expressions only")
            node = statement.value
            if not isinstance(node.func, ast.Name) or node.args:
                raise ToolProtocolError("tools require a simple name and keyword arguments")
            arguments: dict[str, Any] = {}
            for keyword in node.keywords:
                if keyword.arg is None:
                    raise ToolProtocolError("expanded arguments are forbidden")
                if keyword.arg in arguments:
                    raise ToolProtocolError(f"duplicate argument: {keyword.arg}")
                try:
                    arguments[keyword.arg] = ast.literal_eval(keyword.value)
                except (ValueError, TypeError) as exc:
                    raise ToolProtocolError("generated arguments must be literals") from exc
            binding = json.dumps({"tool": node.func.id, "arguments": arguments},
                                 sort_keys=True, separators=(",", ":"), default=str)
            digest = hashlib.sha256(binding.encode()).hexdigest()[:20]
            calls.append(GovernedToolCall(node.func.id, arguments,
                                           f"code-mode:{index}:{digest}"))
        return cls(calls)

    def execute(self, runtime: GovernedToolRuntime, **authorization: Any) -> tuple[Any, ...]:
        return tuple(runtime.execute(call, **authorization) for call in self.calls)
