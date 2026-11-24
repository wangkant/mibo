"""The optional hardening (shell/netguard.py): with it on, a command not read as using the network cannot connect
anywhere, loopback included, over TCP or UDP, IPv4 or IPv6, while one read as using it and a program's run can; no
command but a program's run can register a scheduled task; and turning it off leaves Windows' filters and the Task
Scheduler's folders as they were. Setting it up needs administrator rights and changes the machine, so these run
only in a step of their own on CI's Windows runner, which is elevated: elsewhere they skip and say so."""
from __future__ import annotations

import contextlib
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading

import pytest

from mibo.shell import netguard
from mibo.shell import run as running

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="Windows' own network filters"),
    pytest.mark.skipif(sys.platform == "win32" and not ctypes.windll.shell32.IsUserAnAdmin(),
                       reason="needs administrator rights: it adds filters to Windows' network stack"),
    pytest.mark.skipif(os.environ.get("CI") != "true" or os.environ.get("MIBO_HARDENING_TESTS") != "1",
                       reason="changes the machine's network filters and task folders: runs only in CI's own step "
                              "for it (CI=true, MIBO_HARDENING_TESTS=1), alone"),
]


@pytest.fixture(scope="module")
def hardened(tmp_path_factory):
    record = str(tmp_path_factory.mktemp("netguard") / netguard.RECORD)
    before = json.loads(netguard._powershell(netguard._FOLDERS) or "[]")
    sid = netguard.own_sid()
    netguard.apply(True, record, sid)
    try:
        yield {"record": record, "before": before, "sid": sid}
    finally:
        netguard.apply(False, record, sid)


@contextlib.contextmanager
def _listener(family, kind):
    """A listener of the test's own (which the hardening leaves alone) on loopback: the port, and whether anything
    reached it."""
    host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
    sock = socket.socket(family, kind)
    sock.bind((host, 0))
    reached = threading.Event()
    if kind == socket.SOCK_STREAM:
        sock.listen(1)
    sock.settimeout(15)

    def wait():
        with contextlib.suppress(OSError):
            if kind == socket.SOCK_STREAM:
                sock.accept()[0].close()
            else:
                sock.recvfrom(16)
            reached.set()

    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    try:
        yield host, sock.getsockname()[1], reached
    finally:
        sock.close()
        thread.join(16)


def _connect(host: str, port: int, kind: int) -> str:
    if kind == socket.SOCK_STREAM:
        return (f"$c = New-Object Net.Sockets.TcpClient; $c.Connect('{host}', {port}); 'connected'; $c.Close()")
    return (f"$u = New-Object Net.Sockets.UdpClient('{host}', {port}); [void]$u.Send([byte[]](1,2), 2); 'sent'; "
            "$u.Close()")


def _run(command: str, tmp_path, tier: str, online: bool) -> dict:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(running, "SPARE", running.Spare())
        try:
            return running.run(command, str(tmp_path), tier=tier, online=online, home=tmp_path, limit_s=60)
        finally:
            running.SPARE.close()


CASES = [(socket.AF_INET, socket.SOCK_STREAM), (socket.AF_INET6, socket.SOCK_STREAM), (socket.AF_INET, socket.SOCK_DGRAM)]


@pytest.mark.parametrize(("family", "kind"), CASES, ids=["tcp4", "tcp6", "udp4"])
def test_a_command_not_read_as_using_the_network_cannot_reach_it(hardened, tmp_path, family, kind):
    for tier, online, allowed in (("change", False, False), ("read", False, False), ("change", True, True),
                                  ("program", False, True)):
        with _listener(family, kind) as (host, port, reached):
            done = _run(_connect(host, port, kind), tmp_path, tier, online)
            reached.wait(5 if allowed else 2)
        assert reached.is_set() == allowed, (tier, online, done)


def test_no_command_but_a_programs_run_registers_a_scheduled_task(hardened, tmp_path):
    name = f"mibo-test-{os.getpid()}"
    done = _run(f"schtasks /create /tn {name} /tr cmd.exe /sc once /st 23:59 /f", tmp_path, "change", True)
    assert done["code"] != 0 and "denied" in (done["err"] + done["out"]).lower(), done
    assert subprocess.run(["schtasks", "/query", "/tn", name], capture_output=True).returncode != 0


def test_turning_the_hardening_off_leaves_windows_as_it_was(tmp_path_factory):
    record = str(tmp_path_factory.mktemp("netguard-off") / netguard.RECORD)
    before = json.loads(netguard._powershell(netguard._FOLDERS) or "[]")
    engine = netguard.Engine()
    try:
        filters = {name: len(engine.filters(layer)) for name, layer in netguard.LAYERS.items()}
    finally:
        engine.close()
    sid = netguard.own_sid()
    assert netguard.apply(True, record, sid)["present"]
    assert netguard.apply(True, record, sid)["present"]  # twice is once
    assert not netguard.apply(False, record, sid)["present"]
    assert json.loads(netguard._powershell(netguard._FOLDERS) or "[]") == before
    engine = netguard.Engine()
    try:
        assert {name: len(engine.filters(layer)) for name, layer in netguard.LAYERS.items()} == filters
    finally:
        engine.close()
