"""The everyday bench's MCP stand-in 'tiny' (tools/everyday.py): two tools over stdio, `add` (marked read-only) and
`note` (unmarked). Each call is appended to the log file given as the first argument, for the bench to read.

    python tiny_server.py <log file>
"""
import json
import sys

TOOLS = [
    {"name": "add", "description": "Add two numbers.", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "note", "description": "Keep a short note.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
]

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": message["params"].get("protocolVersion"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "tiny", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = message["params"]["name"], message["params"].get("arguments") or {}
        with open(sys.argv[1], "a", encoding="utf-8") as log:
            log.write(json.dumps({"tool": name, "args": args}) + "\n")
        text = str(args.get("a", 0) + args.get("b", 0)) if name == "add" else "kept"
        result = {"content": [{"type": "text", "text": text}], "isError": False}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
