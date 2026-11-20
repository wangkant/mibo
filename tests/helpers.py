"""Helpers the suites import: `check` and the isolated agent factory."""
from __future__ import annotations

from pathlib import Path

from persona_agent.agent import Agent


def check(name: str, cond, detail: str = "") -> None:
    """Assert `cond`, naming the property so a failure reads as English."""
    assert cond, name + (f" - {detail}" if detail else "")


def isolated_agent(tmp: Path, **settings) -> Agent:
    """A real Agent whose runtime state, read or written, lives under `tmp`.

    `settings` override the Agent keywords below."""
    tmp.mkdir(parents=True, exist_ok=True)
    a = Agent(**{
        "api_key": "test-key", "persona_name": "TestBot",
        "persona": "test persona", "lang": "en",
        "memory_file": str(tmp / "memory.json"),
        "memory_tidy_every": 0, **settings})
    return a


def make_agent(tmp: Path, **overrides) -> Agent:
    """The isolated agent most suites start from: a character called Luna."""
    return isolated_agent(tmp, **{"persona_name": "Luna", **overrides})
