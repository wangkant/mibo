"""A scratch home for the AgentDojo run (tools/scratchhome.py): the first character, the model's local address,
one suite's tools added as an MCP server the way a person adds a connector (mcp_tools.write_servers, which writes
mcp.json), and the person's computer an empty folder beside the home, so nothing of the computer the run happens on
reaches the model. The last line printed is the environment the app runs with, as JSON; it holds no key. Run with
the app's Python from the repo root.

    python tools/bench/agentdojo/home.py <home> <server name> <python for the server> <bridge address> <model address>
        <model> <page port>
"""
import json
import sys
from pathlib import Path

# The checkout's own mibo, not whichever one the Python has installed.
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[3])]

import scratchhome  # noqa: E402

from mibo import mcp_tools, setup_wizard  # noqa: E402

home, name, python, bridge, model_url, model, port = Path(sys.argv[1]), *sys.argv[2:8]
env = scratchhome.make(home, LLM_BASE_URL=model_url, LLM_MODEL=model, PAGE_PORT=port, AGENT_LANG="en")
setup_wizard.write_persona(home, setup_wizard.CHARACTERS[0].key, name="Mibo", lang="en")
server = str(Path(__file__).resolve().with_name("mcp_server.py"))
# One suite at a time: the other suite's server, if an earlier run added it, goes.
for other in mcp_tools.load_config(home)["mcpServers"]:
    if other != name:
        mcp_tools.remove_server(home, other)
mcp_tools.write_servers(home, {name: {"command": python, "args": ["-I", server, bridge]}}, lambda values: None,
                        replace=True)
print(f"{home}: character written, MCP server {name!r} added")
print(json.dumps(env))
