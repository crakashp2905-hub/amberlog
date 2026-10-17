"""The stdio transport, and the `memory-fabric mcp` entry point.

## The transport rules, and why each one matters here

* **One JSON-RPC message per line, UTF-8, no embedded newlines.** `json.dumps`
  without `indent` never emits a raw newline -- newlines inside strings are
  escaped -- so a compact dump is always one line.
* **stdout carries the protocol and nothing else.** A stray `print` corrupts
  the stream for the host, which typically shows the user an opaque parse
  failure and drops the server. Everything human-readable goes to stderr.
  `serve()` swaps `sys.stdout` for stderr while it runs so that a print buried
  in a dependency cannot do this either, and writes protocol output through the
  real stdout handle it kept aside.
* **Flush after every message.** A host waiting on a response it is not given
  will time out, and a buffered response is not given.
* **A malformed line is answered, not fatal.** A Parse error goes back with a
  `null` id, as JSON-RPC requires, and the loop continues: one bad line from a
  host must not take down a server another conversation depends on.
* **EOF is a clean shutdown**, and so is SIGINT. The fabric is closed either
  way, because an SQLite store left with an open WAL is recoverable but slower
  to open next time.

## Why stdio and not Streamable HTTP

Every MCP host can launch a local process; not every deployment wants a
listening port. stdio also gets process isolation for free: one server process
is bound to one agent and one store, so there is no per-request
authentication to get wrong. A Streamable HTTP transport can be added over the
same `Server.handle()`, and would need the `Mcp-Method` / `Mcp-Name` headers and
the authorization rules that 2026-07-28 specifies.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import IO, Any, Sequence

from .protocol import PARSE_ERROR, McpError, Server


def serve(server: Server, stdin: IO[str] | None = None,
          stdout: IO[str] | None = None) -> int:
    """Run the newline-delimited JSON-RPC loop until EOF."""
    reader = stdin if stdin is not None else sys.stdin
    writer = stdout if stdout is not None else sys.stdout
    guard = stdout is None
    if guard:
        # Anything that prints during serving lands on stderr.
        sys.stdout = sys.stderr

    try:
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError as error:
                response: Any = {
                    "jsonrpc": "2.0", "id": None,
                    "error": McpError(PARSE_ERROR,
                                      f"parse error: {error}").to_error(),
                }
            else:
                response = server.handle(message)
            if response is None:
                continue
            writer.write(json.dumps(response, separators=(",", ":"),
                                    ensure_ascii=False, default=str) + "\n")
            writer.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if guard:
            sys.stdout = writer
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="memory-fabric mcp",
        description="Serve a Memory Fabric store over the Model Context "
                    "Protocol on stdio.")
    parser.add_argument("--db", required=True,
                        help="path to the store (created if --create)")
    parser.add_argument("--agent-id", required=True,
                        help="the agent this server acts as; fixed for its "
                             "lifetime and not settable per call")
    parser.add_argument("--tenant", help="restrict to one tenant")
    parser.add_argument("--create", action="store_true",
                        help="create the store if it does not exist")
    parser.add_argument(
        "--require-validation", action="store_true",
        help="hold new memories as candidates until an operator validates "
             "them. Off by default: see the module docstring")
    parser.add_argument(
        "--context", default="compact", choices=["compact", "full"],
        help="how recalled memories are rendered for the model. compact keeps "
             "the prompt-injection preamble and drops per-memory evidence "
             "labels, which X5 measured as costing 7 points of task success")
    parser.add_argument("--retrieval", default="lexical",
                        choices=["lexical", "vector", "hybrid"],
                        help="lexical by default: it is the measured winner "
                             "on external corpora and needs no model")
    args = parser.parse_args(argv)


    from .. import MemoryFabric
    from ..storage import display, store_exists
    from .tools import build_server

    if not args.create and not store_exists(args.db):
        print(f"memory-fabric mcp: no store at {display(args.db)} "
              f"(pass --create to make one)", file=sys.stderr)
        return 2

    # Written to stderr so a host's log shows what the server is bound to --
    # the most useful single line when diagnosing "why does it not see my
    # memories".
    print(f"memory-fabric mcp: store={display(args.db)} agent={args.agent_id} "
          f"tenant={args.tenant or 'all'} retrieval={args.retrieval} "
          f"validation={'required' if args.require_validation else 'on write'}",
          file=sys.stderr)

    # New memories are activated on write unless --require-validation.
    #
    # The library defaults the other way: a memory starts as a candidate and
    # an operator promotes it. Through MCP that default makes the server
    # useless for its primary job -- an agent recalling what it learned -- and
    # the first subprocess test of this server recalled nothing for exactly
    # that reason. What activation does NOT weaken is federation: memories
    # are still written at private scope, and an unvalidated memory is never
    # shared (principle 7). The sensitive-data scan still quarantines on
    # write, and quarantined memories are never recalled, activated or not.
    fabric = MemoryFabric(args.db, retrieval=args.retrieval,
                          auto_activate=not args.require_validation)
    try:
        server = build_server(fabric, args.agent_id, args.tenant,
                              rendering=args.context)
        return serve(server)
    finally:
        fabric.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
