"""Name calls and memory commands: when a message addresses the persona, and
when it is a command rather than conversation; then how notes are kept,
merged, evicted and rendered.

    python -m pytest tests/test_memory_commands.py
"""
from __future__ import annotations

from pathlib import Path

from mibo.agent import Agent

from helpers import isolated_agent


def make_agent(tmp: Path, *, name: str = "Luna", lang: str = "en") -> Agent:
    return isolated_agent(tmp, persona_name=name, lang=lang)


# ---------------------------------------------------------------------------
# Keeping, merging, evicting and rendering notes
# ---------------------------------------------------------------------------

SECRET = "Alice is going through a divorce, keep it quiet"
