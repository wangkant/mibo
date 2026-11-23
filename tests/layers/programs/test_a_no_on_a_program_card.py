"""A no on a card in another program holds for that task alone, as a no on a command's card does: the same task in
the same program is not started again that turn, every other task and every command goes on with its own cards, and
what the model is told says that the declined step was not done, not that nothing was."""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

if sys.platform != "win32":
    pytest.skip("the app works in other programs on Windows only", allow_module_level=True)

from mibo.desk import operate
from mibo.desk import tool as desk_tool


class Lookups(SimpleNamespace):
    def doing(self, *args) -> None:
        pass

    def away(self) -> float:
        return 0.0


def test_a_no_on_a_program_card_holds_that_task_alone(monkeypatch, tmp_path):
    started: list[str] = []

    async def run(ask_model, remote, task, program, **kwargs):
        started.append(task)
        return {"status": "declined", "result": "", "steps": ["typed 你好 into the box"], "said": [], "calls": 1}

    monkeypatch.setattr(operate, "run", run)
    agent = SimpleNamespace(roam=None, llm_dm_model="stand-in", memory_file=str(tmp_path / "memory.json"),
                            _endpoint_for=lambda model: ("http://127.0.0.1:9/v1", None), _shows_pictures=lambda: False)
    lookups = Lookups(conversation="main", trace=[], pictures=[], away_s=0.0, away_since=None)

    def use(task: str) -> str:
        return asyncio.run(desk_tool.use(agent, {"task": task, "program": "微信/WeChat"}, lookups))

    told = use("给妈妈发 你好")  # copy: voice
    assert "not done" in told and "nothing was done" not in told
    again = use("给妈妈发 你好")  # copy: voice
    other = use("给小王发 晚上见")  # copy: voice
    assert started == ["给妈妈发 你好", "给小王发 晚上见"]  # copy: voice
    assert again.startswith("(not started: they already said no")
    assert other.startswith("Task in")
    # A command after the no is not held: the shell has its own cards.
    assert not getattr(lookups, "shell_held", "")


def test_a_program_card_nobody_answered_holds_the_rest_of_the_turn(monkeypatch, tmp_path):
    async def run(ask_model, remote, task, program, **kwargs):
        return {"status": "declined", "result": "", "said": [], "calls": 1,
                "steps": [f"[declined] {operate.UNANSWERED} for send (发送); nothing was done"]}

    monkeypatch.setattr(operate, "run", run)
    agent = SimpleNamespace(roam=None, llm_dm_model="stand-in", memory_file=str(tmp_path / "memory.json"),
                            _endpoint_for=lambda model: ("http://127.0.0.1:9/v1", None), _shows_pictures=lambda: False)
    lookups = Lookups(conversation="main", trace=[], pictures=[], away_s=0.0, away_since=None)
    told = asyncio.run(desk_tool.use(agent, {"task": "给妈妈发 你好", "program": "微信/WeChat"}, lookups))  # copy: voice
    assert "nobody answered" in told and "said no" not in told
    # Nothing more is started in a program or changed by a command while nobody is there.
    assert lookups.desk_held and lookups.shell_held
    assert lookups.trace[-1]["status"] == "unanswered"
