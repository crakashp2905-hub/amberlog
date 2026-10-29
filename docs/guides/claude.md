# Claude Code and Claude Desktop

Amberlog is an MCP server. Claude gets four tools (`recall`, `fetch`,
`verify`, `remember`), a one-line trust summary beside every memory it
recalls, and a plain sentence whenever something is refused.

## 1. Create a store

```bash
pip install .
amberlog init ./memory          # store, keys outside it, one agent, MCP config
```

`init` prints the exact configuration for your paths. Keep the keys folder
out of the store folder and out of version control.

## 2. Connect Claude Code

```bash
claude mcp add amberlog -- \
  amberlog --db ./memory/store.db --keys ./memory/keys mcp --agent claude-code
```

## 3. Or Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "amberlog": {
      "command": "amberlog",
      "args": ["--db", "/abs/path/memory/store.db", "--keys", "/abs/path/memory/keys",
               "mcp", "--agent", "claude-desktop"]
    }
  }
}
```

## What Claude sees

```json
{"memories": [{"memory_id": "01M5…", "version": 1, "type": "semantic",
  "content": "Pump P-14 relief valve is set to 10 bar.",
  "trust": "from inspector · 2 independent sources · 3 days old"}]}
```

and, when a memory it relied on has been withdrawn:

```json
{"usable": false, "reason": "blocked_lifecycle",
 "explanation": "Not usable: this memory has been withdrawn or retired."}
```

New memories Claude writes start as candidates and are not shown to other
agents until someone reviews them (`amberlog review`), unless you
launch with `--trusted-local` for a single-user machine.

## Watch it

```bash
amberlog --db ./memory/store.db serve     # the Memory Control Center
```

Open **Replay** to see what Claude recorded and recalled, and any memory to
see its story.
