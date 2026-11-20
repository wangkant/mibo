"""The recent window on disk (recent.json): the time and number of every line
and turn, what a restart brings back, what is never kept, and a backlog that
is kept as context without being answered. No test calls a model.

Run from the repo root:

    python -m pytest tests/test_memory_recent.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from mibo import recent
from mibo.agent import Agent

from helpers import check
from helpers import make_agent

ROOM = "telegram:c1"
READER = "telegram:9"
PKEY = "private:telegram:9"


def _restart(tmp: Path, first: Agent, **settings) -> Agent:
    first.flush_state()
    return make_agent(tmp, **settings)


async def test_a_damaged_window_file_is_set_aside(tmp: Path) -> None:
    (tmp / "recent.json").write_text("{not json", encoding="utf-8")
    agent = make_agent(tmp)
    check("set aside", (tmp / "recent.json.corrupt").is_file())
    check("every chat starts empty", not agent.window_seq and not agent.dm_history)


async def test_only_recent_and_at_most_256_chats_are_kept(tmp: Path) -> None:
    now = time.time()
    convs = {f"telegram:g{i}": {"seq": 1, "folded_upto": 0, "last_at": now - i,
                                "lines": [{"name": "A", "text": "hi", "user_id": "1",
                                           "t": now - i, "seq": 1}]}
             for i in range(260)}
    convs["telegram:old"] = {"seq": 1, "last_at": now - 73 * 3600, "lines": [
        {"name": "A", "text": "old", "user_id": "1", "t": now - 73 * 3600, "seq": 1}]}
    (tmp / "recent.json").write_text(json.dumps({"format": 1, "convs": convs}),
                                     encoding="utf-8")
    agent = make_agent(tmp)
    check("past 72 hours a chat is not restored", "telegram:old" not in agent.window_seq)
    check("at most 256 chats, the newest", len(agent.window_seq) == recent.MAX_CONVS
          and "telegram:g0" in agent.window_seq and "telegram:g259" not in agent.window_seq,
          repr(len(agent.window_seq)))
