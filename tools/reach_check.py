"""What Settings › 能力 gets on a network that blocks GitHub, or GitHub and the vendors' own registries, measured.

    python tools/reach_check.py --home F:/scratch/reach --scenario github|strict|offline [--block dns|hang]
                                [--steps catalog,refresh,install,preview,mark,registry,latest,node,uv,npx,uvx]

Nothing on this computer's network settings changes. The hosts are made unreachable inside this process by a
stand-in for the connection layer (`--block hang`: a connection that never answers until its timeout, as a dropped
packet does; `--block dns`: the name resolves to 127.0.0.1, as a poisoned resolver answers), and for the npx and
uvx child processes by a local proxy given to them in HTTPS_PROXY that does the same. Scenarios:

- open: nothing blocked, for comparison.
- github: GitHub's hosts (github.com, raw.githubusercontent.com, codeload, api, objects and release assets,
  avatars).
- strict: those, plus nodejs.org, registry.npmjs.org, pypi.org, files.pythonhosted.org and the MCP Registry.
- offline: every host.

Each step prints one JSON line: what it reached, how long it took, and the line the page would show. Downloads go
under --home only; the home is the place to delete afterwards.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GITHUB = {"github.com", "raw.githubusercontent.com", "codeload.github.com", "api.github.com",
          "objects.githubusercontent.com", "release-assets.githubusercontent.com", "avatars.githubusercontent.com"}
VENDORS = {"nodejs.org", "registry.npmjs.org", "pypi.org", "files.pythonhosted.org",
           "registry.modelcontextprotocol.io"}
SCENARIOS = {"open": set(), "github": GITHUB, "strict": GITHUB | VENDORS, "offline": None}
STEPS = ("catalog", "refresh", "install", "preview", "mark", "registry", "latest", "node", "uv", "npx", "uvx")
# A step that has not finished by then is reported as still waiting.
STEP_LIMIT_S = 420


def blocked(host: str, hosts) -> bool:
    host = (host or "").lower().rstrip(".")
    if host in ("127.0.0.1", "localhost", "::1"):
        return False
    return hosts is None or host in hosts


def stand_in(hosts, mode: str) -> None:
    """Makes `hosts` unreachable for every connection this process opens."""
    import httpcore
    from httpcore._backends.auto import AutoBackend

    from mibo import ingestion

    if mode == "dns":
        real = socket.getaddrinfo

        def poisoned(host, port, *a, **k):
            if isinstance(host, str) and blocked(host, hosts):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 443))]
            return real(host, port, *a, **k)

        socket.getaddrinfo = poisoned
        return

    async def never(timeout):
        await asyncio.sleep(timeout or 3600)
        raise httpcore.ConnectTimeout("stand-in: no answer")

    pinned = ingestion._PinnedNetworkBackend.connect_tcp
    auto = AutoBackend.connect_tcp

    async def pinned_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if blocked(self.hostname, hosts):
            await never(timeout)
        return await pinned(self, host, port, timeout, local_address, socket_options)

    async def auto_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if blocked(str(host), hosts):
            await never(timeout)
        return await auto(self, host, port, timeout, local_address, socket_options)

    ingestion._PinnedNetworkBackend.connect_tcp = pinned_tcp
    AutoBackend.connect_tcp = auto_tcp


async def proxy(hosts, mode: str, port: int) -> asyncio.base_events.Server:
    """A CONNECT proxy for child processes: blocked hosts never answer (or are refused), others are tunnelled."""
    async def pipe(reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def one(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            writer.close()
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1").split()
        if len(line) < 2 or line[0] != "CONNECT":
            writer.close()
            return
        host, _, target = line[1].rpartition(":")
        if blocked(host, hosts):
            if mode == "hang":
                await asyncio.sleep(3600)
            writer.close()
            return
        try:
            up_r, up_w = await asyncio.open_connection(host, int(target))
        except OSError:
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))

    return await asyncio.start_server(one, "127.0.0.1", port)


def report(step: str, began: float, **facts) -> None:
    print(json.dumps({"step": step, "s": round(time.monotonic() - began, 1), **facts}, ensure_ascii=False),
          flush=True)


async def timed(step: str, work):
    began = time.monotonic()
    try:
        facts = await asyncio.wait_for(work(), STEP_LIMIT_S)
    except asyncio.TimeoutError:
        facts = {"ok": False, "line": f"still waiting after {STEP_LIMIT_S} s"}
    except Exception as e:
        facts = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    report(step, began, **facts)


def line_of(code: str, ns: str) -> str:
    from mibo import i18n
    words = i18n.catalog("zh").get(ns, {}).get("errors", {})
    return words.get(code, code)


async def server_start(home: Path, command: str, args: list, proxy_port: int, fresh: bool) -> dict:
    """Starts one local MCP server as the app would, its downloads going through the stand-in proxy."""
    from mibo import mcp_client, runtimes
    cache = home / "runtime" / "cache"
    if fresh:
        shutil.rmtree(cache, ignore_errors=True)
    env = runtimes.env(home, {})
    if hasattr(runtimes, "reach_env"):
        env = {**await runtimes.reach_env(home, command), **env}
    env.update({"HTTPS_PROXY": f"http://127.0.0.1:{proxy_port}", "HTTP_PROXY": f"http://127.0.0.1:{proxy_port}",
                "NO_PROXY": "127.0.0.1,localhost"})
    if command == "uvx":
        # Make uv fetch its own Python, as it does on a computer that has none.
        env["UV_PYTHON_PREFERENCE"] = "only-managed"
    folder = home / "servers" / command
    folder.mkdir(parents=True, exist_ok=True)
    conn = mcp_client.Connection({"command": command, "args": args, "env": env}, folder=folder)
    try:
        await conn.open(STEP_LIMIT_S - 20)
        tools = await conn.list_tools(60, 100)
        return {"ok": True, "tools": len(tools), "registry": env.get("npm_config_registry") or
                env.get("UV_DEFAULT_INDEX") or "vendor", "python": env.get("UV_PYTHON_INSTALL_MIRROR", "vendor")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "stderr": conn.stderr_tail()[-300:]}
    finally:
        await conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="github")
    parser.add_argument("--block", choices=("hang", "dns"), default="hang")
    parser.add_argument("--steps", default=",".join(STEPS))
    parser.add_argument("--proxy-port", type=int, default=59759)
    parser.add_argument("--skill", default="anthropics/frontend-design")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    home = args.home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    os.environ["AGENT_HOME"] = str(home)
    hosts = SCENARIOS[args.scenario]
    stand_in(hosts, args.block)
    steps = [s for s in args.steps.split(",") if s]
    from mibo import mcp_market, mcp_tools, runtimes
    from mibo.skills import market
    print(json.dumps({"scenario": args.scenario, "block": args.block, "home": str(home)}), flush=True)

    async def catalog():
        data, came = market.catalog(home)
        view = market.view(home)
        return {"ok": bool(data["skills"]), "entries": len(data["skills"]), "from": came,
                "categories": len(view["categories"])}

    async def refresh():
        ok = await market.refresh(home, force=True)
        return {"ok": ok, "from": market.catalog(home)[1]}

    async def install():
        shutil.rmtree(home / "skills", ignore_errors=True)
        try:
            folder = await market.install(home, args.skill)
        except ValueError as e:
            return {"ok": False, "code": str(e), "line": line_of(str(e), "setup_skills")}
        return {"ok": True, "folder": folder}

    async def preview():
        one = market.by_id(home, args.skill)
        text, moved = await asyncio.gather(market.preview(home, one), market.changed(home, one))
        return {"ok": text is not None, "changed": moved}

    async def mark():
        place = market._cache_path(home).parent / "marks"
        shutil.rmtree(place, ignore_errors=True)
        got = await market.mark(home, "anthropics")
        return {"ok": got is not None, "bytes": len(got or b"")}

    async def registry():
        try:
            rows = await mcp_market.search(home, "github")
        except mcp_tools.ToolsError as e:
            return {"ok": False, "code": str(e)}
        return {"ok": True, "rows": len(rows)}

    async def latest():
        config = {"mcpServers": {"memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory@2.2.1"]},
                                 "time": {"command": "uvx", "args": ["mcp-server-time==2026.11.18"]}}}
        mcp_tools.config_path(home).parent.mkdir(parents=True, exist_ok=True)
        mcp_tools.config_path(home).write_text(json.dumps(config), encoding="utf-8")
        await mcp_market.refresh_latest(home, force=True)
        known = mcp_market._latest(home)
        return {"ok": all(v.get("version") for v in known.values()),
                "versions": {k: v.get("version") for k, v in known.items()}}

    def runtime(name):
        async def work():
            shutil.rmtree(runtimes.folder(home, name), ignore_errors=True)
            try:
                await runtimes.install(home, name)
            except ValueError as e:
                return {"ok": False, "code": str(e)}
            return {"ok": runtimes.ready(home, name)}
        return work

    def start(command, args_):
        async def work():
            need = runtimes.COMMANDS[command]
            if not runtimes.ready(home, need):
                return {"ok": False, "line": f"{need} is not in the home; run the {need} step in a scenario that reaches it"}
            return await server_start(home, command, args_, parser_args.proxy_port, fresh=True)
        return work

    parser_args = args
    server = await proxy(hosts, args.block, args.proxy_port) if {"npx", "uvx"} & set(steps) else None
    plan = {"catalog": catalog, "refresh": refresh, "install": install, "preview": preview, "mark": mark,
            "registry": registry, "latest": latest, "node": runtime("node"), "uv": runtime("uv"),
            "npx": start("npx", ["-y", "@modelcontextprotocol/server-memory@2.2.1"]),
            "uvx": start("uvx", ["mcp-server-time==2026.11.18"])}
    for step in steps:
        await timed(step, plan[step])
    if server is not None:
        server.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
