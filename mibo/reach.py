"""Which of several hosts to fetch from, by which of them answers here.

The vendor's own host is always first while it answers. A public mirror comes in only for bytes the app checks
against a hash it already holds (a skill's files, a runtime's archive), so a mirror can make a download possible
but never change what arrives. Which host answers is found by a short probe through situation.py's recording
transport, so the same outcome also lands in the situation table; nothing is chosen from the interface language.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import situation

# A probe's answer is used this long before the host is asked again.
KEEP_S = 600
_seen: dict[str, tuple[float, bool]] = {}
_asking: dict[str, asyncio.Task] = {}


def runtime_of(home: Path) -> Path:
    from .paths import runtime_dir_for
    return runtime_dir_for(Path(home), os.getenv("AGENT_RUNTIME_DIR", ""))


async def _ask(runtime: Path, host: str) -> bool:
    # No system proxy, as the guarded fetch uses none: what answers here answers for it too.
    try:
        async with (httpx.AsyncClient(timeout=situation.PROBE_TIMEOUT_S, follow_redirects=False, trust_env=False,
                                      transport=situation.recording_transport(runtime)) as http,
                    http.stream("HEAD", f"https://{host}/")):
            pass
    except httpx.HTTPError:
        answered = False
    else:
        answered = True
    _seen[host] = (time.monotonic(), answered)
    return answered


async def answers(runtime: Path, host: str) -> bool:
    """Whether `host` answered a probe in the last KEEP_S, asking it now (at most PROBE_TIMEOUT_S) otherwise."""
    hit = _seen.get(host)
    if hit and time.monotonic() - hit[0] < KEEP_S:
        return hit[1]
    if host not in _asking or _asking[host].done():
        _asking[host] = asyncio.ensure_future(_ask(runtime, host))
    return await asyncio.shield(_asking[host])


async def order(runtime: Path, urls: list[str]) -> list[str]:
    """Those of `urls` whose host answers, in the order given; none when nothing answers, so a network that reaches
    none of them is told within one probe rather than after each download's own wait."""
    hosts = list(dict.fromkeys(urlsplit(u).hostname for u in urls))
    up = dict(zip(hosts, await asyncio.gather(*(answers(runtime, h) for h in hosts))))
    return [u for u in urls if up[urlsplit(u).hostname]]


async def first(runtime: Path, hosts: list[str]) -> str:
    """The first of `hosts` that answers, or ""."""
    up = await asyncio.gather(*(answers(runtime, h) for h in hosts))
    return next((h for h, ok in zip(hosts, up) if ok), "")
