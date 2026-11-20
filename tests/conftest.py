"""Fixtures the suites share: a scratch directory, and coroutine tests."""
from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path

import pytest

from persona_agent import agent as _agent
from persona_agent import home as _home
from persona_agent import paths as _paths


@pytest.fixture(autouse=True)
def _one_home_at_a_time():
    """A page a test starts builds its character for its own home (character.py): that home's .env
    goes into the environment and its folder becomes the root of every path. Both are put back."""
    environment, from_file, root = dict(os.environ), set(_home.FROM_ENV_FILE), _paths.ROOT
    yield
    for key in set(os.environ) - set(environment):
        del os.environ[key]
    os.environ.update(environment)
    _home.FROM_ENV_FILE.clear()
    _home.FROM_ENV_FILE.update(from_file)
    _paths.ROOT = _agent.ROOT = root


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test asks PyPI; tests/test_updates.py turns the check back on."""
    monkeypatch.setenv("UPDATE_CHECK_ENABLED", "false")


@pytest.fixture(autouse=True)
def _no_walks(monkeypatch: pytest.MonkeyPatch) -> None:
    """No service a test starts goes out to real sites; tests/test_roam.py turns walks on."""
    monkeypatch.setenv("ROAM_ENABLED", "false")


@pytest.fixture(autouse=True)
def _no_credential_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test writes to this computer's credential store (secretstore.py): a dictionary stands in."""
    import keyring
    held: dict = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: held.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: held.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: held.pop((service, name)))


@pytest.fixture(autouse=True)
def _same_on_every_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """English output whatever the system language, and no waiting on the
    disk: no test checks that a write was flushed."""
    monkeypatch.setenv("AGENT_LANG", "en")
    monkeypatch.setattr(os, "fsync", lambda fd: None)


@pytest.fixture
def tmp(tmp_path: Path) -> Path:
    """The per-test scratch directory the suites take as `tmp`.

    Every test that writes state redirects it here, so nothing a test does
    can reach the checkout's own runtime files."""
    return tmp_path


def pytest_pyfunc_call(pyfuncitem: pytest.Function):
    """Run an `async def` test on its own event loop.

    Each coroutine test is self-contained and builds whatever it needs inside
    the call, so a fresh loop per test is the whole requirement — and pytest
    stays the only thing this repository needs installed to run its tests."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    arguments = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(pyfuncitem.obj(**arguments))
    return True
