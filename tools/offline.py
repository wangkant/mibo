"""The app of a benchmark whose world is simulated, kept to this computer: `on()` makes every connection and
every name lookup of the process it is called in fail unless it is to loopback, as it would on a computer with no
network, the keyless web search finds nothing, and the app finds no installed browser (a browser is a process of
its own and would still reach out). The
model's address, the benchmark's own servers and the page are on 127.0.0.1 and are not affected.

A benchmark's addresses are made up, and some of them are real sites: without this the app's own page reading
fetched the real informations.com for an AgentDojo task about a fictional one, and an injected instruction could
send the task's text to whatever real address it names.

    START.format(port=...)    what a runner gives `python -c` in place of starting the app directly"""
from __future__ import annotations

import ipaddress
import os
import socket
from asyncio import proactor_events

START = ("import sys; sys.path.insert(0, 'tools'); import offline; offline.on(); from mibo import welcome; "
         "sys.exit(welcome.main(['--no-browser', '--port', '{port}']))")


def _loopback(host) -> bool:
    name = host.decode() if isinstance(host, bytes) else str(host)
    try:
        return ipaddress.ip_address(name.split("%")[0]).is_loopback
    except ValueError:
        return name.lower() == "localhost"


def _is_ip(host) -> bool:
    try:
        ipaddress.ip_address((host.decode() if isinstance(host, bytes) else str(host)).split("%")[0])
        return True
    except ValueError:
        return False


async def _nothing(self, query: str, max_results: int) -> list:
    return []


def on() -> None:
    os.environ["PERSONA_BROWSER_PATH"] = os.devnull + ".none"
    # The keyless search's HTTP client (primp) is not Python's sockets, so the guard below does not hold it.
    from mibo import search
    search.WebSearch._web_search_ddg = _nothing

    def check(sock, address) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
            raise ConnectionRefusedError(f"no network: {address[0]}")

    def guard(real):
        def connect(sock, address):
            check(sock, address)
            return real(sock, address)
        return connect

    def guard_loop(real):
        def sock_connect(loop, sock, address):
            check(sock, address)
            return real(loop, sock, address)
        return sock_connect

    real_lookup = socket.getaddrinfo

    def lookup(host, *rest, **named):
        if host is not None and not _loopback(host) and not _is_ip(host):
            raise socket.gaierror(socket.EAI_NONAME, f"no network: {host}")
        return real_lookup(host, *rest, **named)

    socket.socket.connect = guard(socket.socket.connect)
    socket.socket.connect_ex = guard(socket.socket.connect_ex)
    socket.getaddrinfo = lookup
    # Windows' asyncio loop connects through the I/O completion port, not socket.connect.
    proactor_events.BaseProactorEventLoop.sock_connect = guard_loop(proactor_events.BaseProactorEventLoop.sock_connect)
