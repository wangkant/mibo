"""Measures adding MCP servers against a running app: python tools/mcp_market_check.py <home> [--import]

Reads the app's address from <home>/runtime/desktop/welcome.json and prints JSON: the market's size, a search
of the official registry, how long installing a remote and a local entry takes to answer and to connect, a
pasted address and command, a pinned version and its update, and with --import what the configs of other
apps offer and what importing them adds. Starting a local program is the press its start card asks for;
this script gives that press for the servers it adds, and removes everything it added at the end.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

home = Path(sys.argv[1])
address = urlsplit(json.loads((home / "runtime/desktop/welcome.json").read_text(encoding="utf-8"))["url"])
token = address.fragment.partition("token=")[2]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path: str, body=None):
    """(status, answer, seconds) of one request to the app."""
    request = urllib.request.Request(
        f"http://{address.netloc}/api/{path}", data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json", "X-Personagent-Setup-Token": token})
    start = time.perf_counter()
    try:
        with opener.open(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"{}"), round(time.perf_counter() - start, 2)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}"), round(time.perf_counter() - start, 2)


def rows() -> dict:
    return {row["name"]: row for row in call("mcp")[1]["servers"]}


def until(name: str, *states: str, seconds: float = 180) -> tuple[dict, float]:
    """The server's row once it is in one of `states`, and the seconds that took."""
    start = time.perf_counter()
    while True:
        row = rows()[name]
        if row["state"] in states or time.perf_counter() - start > seconds:
            return row, round(time.perf_counter() - start, 1)
        time.sleep(0.25)


def started(name: str) -> dict:
    """Gives a waiting local program its start, then waits for it to connect."""
    row, _ = until(name, "waiting", "connected", "failed", "signin", seconds=20)
    if row["state"] == "waiting":
        call("mcp", {"start": name, "answer": "once"})
    row, took = until(name, "connected", "failed", "signin")
    return {"state": row["state"], "error": row.get("error", ""), "tools": len(row["tools"]), "seconds_to_state": took}


before = set(rows())
out: dict = {}

status, market, took = call("mcp/market")
out["market"] = {"status": status, "entries": len(market["servers"]), "seconds": took,
                 "remote": sum(any(w["kind"] == "remote" for w in e["ways"]) for e in market["servers"]),
                 "local": sum(any(w["kind"] != "remote" for w in e["ways"]) for e in market["servers"]),
                 "categories": sorted({e["category"] for e in market["servers"]})}
by_name = {e["name"]: e for e in market["servers"]}

status, found, took = call("mcp/market/search?q=github")
out["registry_search_github"] = {"status": status, "entries": len(found.get("servers", [])), "seconds": took}

for name, way_kind, values in (("deepwiki", "remote", {}), ("time", "pypi", {}),
                               ("filesystem", "npm", {"arg:0": str(home)})):
    one = by_name[name]
    way = next(i for i, w in enumerate(one["ways"]) if w["kind"] == way_kind)
    status, answer, took = call("mcp/market", {"install": one["id"], "way": way, "values": values})
    added = answer.get("added", [""])[0] if status == 200 else ""
    out[f"install_{name}"] = {"status": status, "answer_seconds": took, "server": added,
                              **(started(added) if added else {"error": answer})}

status, answer, took = call("mcp", {"add": "https://mcp.deepwiki.com/mcp", "name": "pasted-url"})
out["paste_address"] = {"status": status, "seconds": took, **({"error": answer["error"]} if status != 200 else {})}
status, answer, took = call("mcp", {"add": "uvx mcp-server-time==2026.8.18", "name": "pasted-old"})
out["paste_command"] = {"status": status, "seconds": took, **({"error": answer["error"]} if status != 200 else {})}

# The pinned version, and the newer one PyPI names, asked in the background once the list is read.
start = time.perf_counter()
row = rows().get("pasted-old", {})
while row and not row.get("latest") and time.perf_counter() - start < 30:
    time.sleep(0.5)
    row = rows()["pasted-old"]
out["version"] = {"pinned": row.get("version"), "latest_shown": row.get("latest"),
                  "seconds_to_show": round(time.perf_counter() - start, 1)}
if row.get("latest"):
    status, answer, took = call("mcp/market", {"update": "pasted-old"})
    after = rows()["pasted-old"]
    out["update"] = {"status": status, "seconds": took, "version_after": after["version"],
                     "latest_after": after["latest"], "state_after": after["state"]}

if "--import" in sys.argv:
    status, answer, took = call("mcp/market", {"apps": True})
    found = answer.get("found", [])
    out["other_apps"] = {"status": status, "seconds": took, "rows": [
        {k: r.get(k) for k in ("app", "original", "kind", "where", "values", "have", "taken", "off", "problem")}
        for r in found]}
    keys = [r["key"] for r in found if r["key"] and not r["problem"] and not r["have"]]
    status, answer, took = call("mcp/market", {"import": keys})
    now = rows()
    out["import"] = {"status": status, "seconds": took, "asked": len(keys), "added": answer.get("added", []),
                     "states": {n: {"state": now[n]["state"], "values": now[n]["values"]}
                                for n in answer.get("added", [])}}

for name in set(rows()) - before:
    call("mcp", {"remove": name})
out["left_after_cleanup"] = sorted(set(rows()) - before)
print(json.dumps(out, ensure_ascii=False, indent=1))
