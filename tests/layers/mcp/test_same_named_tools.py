"""A server's tool is named with its server (mcp__server__tool, as Claude Code names them), so a server tool that
shares a name with one of the app's own (read_file) is never run as the app's: find_tools gives the qualified name,
use_tool with it reaches the server, and the bare name with no server is answered with both names, not run."""
from __future__ import annotations

import json
import sys
import textwrap
import time

from harness.model import call, say

SERVER = textwrap.dedent('''
    import json, sys
    TOOLS, LOG = json.loads(sys.argv[1]), sys.argv[2]
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        method = m.get("method")
        if method == "initialize":
            r = {"protocolVersion": m["params"].get("protocolVersion"), "capabilities": {"tools": {}},
                 "serverInfo": {"name": "bank", "version": "1"}}
        elif method == "tools/list":
            r = {"tools": TOOLS}
        elif method == "tools/call":
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(m["params"]["name"] + "\\n")
            r = {"content": [{"type": "text", "text": "Rent due: 1100"}], "isError": False}
        else:
            r = {}
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
''')
TOOLS = [{"name": "read_file", "description": "Reads the contents of the file at the given path.",
          "inputSchema": {"type": "object", "properties": {"file_path": {"type": "string"}}},
          "annotations": {"readOnlyHint": True}}]


def test_a_server_tool_named_like_an_app_tool_is_reached_by_its_qualified_name_only(app, turn, tmp_path):
    script, log = tmp_path / "bank_server.py", tmp_path / "bank.log"
    script.write_text(SERVER, encoding="utf-8")
    snippet = {"bank": {"command": sys.executable, "args": [str(script), json.dumps(TOOLS), str(log)]}}
    assert app.post("/api/mcp", {"add": json.dumps(snippet)}).status_code == 200
    assert app.post("/api/mcp", {"start": "bank", "answer": "always"}, own_page=True).status_code == 200
    deadline = time.monotonic() + 30
    while next(r["state"] for r in app.get("/api/mcp").json()["servers"]) != "connected":
        assert time.monotonic() < deadline
        time.sleep(0.1)
    found = call("find_tools", query="read file", server="bank")
    bare = call("use_tool", tool="read_file", arguments={"file_path": "bill.txt"})
    named = call("use_tool", tool="mcp__bank__read_file", arguments={"file_path": "bill.txt"})
    done = turn("What does bill.txt on my bank say?", found, bare, named, say("Rent due: 1100."),  # copy: voice
                cards="no")
    first, second, third = done.calls()
    assert '"mcp__bank__read_file"' in done.result_of(first["id"])
    refused = done.result_of(second["id"])
    assert refused.startswith("Error:") and "mcp__bank__read_file" in refused
    assert "Rent due" in done.result_of(third["id"])
    assert log.read_text(encoding="utf-8").splitlines() == ["read_file"]
    # The app's own read_file never ran on the person's folders.
    assert [step["tool"] for step in done.trace if step.get("tool") in ("shell", "mcp")] == ["mcp"]
    assert done.cards == []
