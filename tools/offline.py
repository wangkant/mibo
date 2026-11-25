"""The app of a benchmark whose world is simulated, kept to this computer: `on()` makes every connection and
every name lookup of the process it is called in fail unless it is to loopback, as it would on a computer with no
network, the keyless web search finds nothing, and the app finds no installed browser (a browser is a process of
its own and would still reach out). The
model's address, the benchmark's own servers and the page are on 127.0.0.1 and are not affected.

A benchmark's addresses are made up, and some of them are real sites: without this the app's own page reading
fetched the real informations.com for an AgentDojo task about a fictional one, and an injected instruction could
send the task's text to whatever real address it names.

A simulated world is also on a day of its own (AgentDojo's bank account ends in March 2022): with BENCH_DAY set
to that day (2022-03-08), the time the app tells the model is that day at this computer's hour. Told it is 2026, a
model takes the world's newest records for years old and stops to ask about them.

A simulated world may have a web of its own (AgentDojo's slack suite: www.informations.com is a page of the
suite). With BENCH_WEB set to the address of the runner's bridge, the app's own page reads are answered by the
suite's get_webpage there, as the real web answers them on a person's computer; an address the suite does not
have cannot be read.

    START.format(port=...)    what a runner gives `python -c` in place of starting the app directly"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import urllib.request
from asyncio import proactor_events
from datetime import date, datetime

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


class _Day(datetime):
    """This computer's clock on the benchmark's day."""
    day: date

    @classmethod
    def now(cls, tz=None):
        return datetime.now(tz).replace(year=cls.day.year, month=cls.day.month, day=cls.day.day)


def _world_web(bridge: str) -> None:
    from mibo.web import fetch

    def page(url: str) -> dict:
        request = urllib.request.Request(bridge, data=json.dumps({"name": "get_webpage", "arguments": {"url": url}}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as answer:
            return json.loads(answer.read())

    async def for_chat(agent, url: str, wants_list: bool = False):
        got = await asyncio.to_thread(page, url)
        text = str(got.get("text") or "").strip()
        return None if got.get("error") or not text or text == "404 Not Found" else (url, text, url)

    fetch.for_chat = for_chat


def on() -> None:
    os.environ["PERSONA_BROWSER_PATH"] = os.devnull + ".none"
    if os.environ.get("BENCH_WEB"):
        _world_web(os.environ["BENCH_WEB"])
    if os.environ.get("BENCH_DAY"):
        from mibo import textproc
        _Day.day = date.fromisoformat(os.environ["BENCH_DAY"])
        textproc.datetime = _Day
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
