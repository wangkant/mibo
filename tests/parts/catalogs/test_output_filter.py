"""The person's own output filter (data/output_filter.<lang>.json in the home), applied to every reply: a running
character applies what a fresh one would load from the same file, keeps its last good rules over a broken edit, and
drops them with the file."""
from __future__ import annotations

import json
import os
from pathlib import Path

from mibo import paths
from mibo.agent import Agent
from mibo.settings import AgentSettings

STAMP = 1_700_000_000_000_000_000


def _character(folder: Path, word: str) -> Agent:
    """A character whose home holds the person's own rules, blocking `word`."""
    rules = paths.ROOT / "data" / "output_filter.en.json"
    rules.parent.mkdir()
    _rules(rules, word, STAMP)
    return Agent(AgentSettings(api_key="test-key", persona_name="Luna", lang="en", persona="A friend.",
                               memory_file=str(folder / "memory.json")))


def _rules(path: Path, word: str, stamp: int) -> None:
    path.write_text(json.dumps([{"name": "block", "pattern": word}]), encoding="utf-8")
    os.utime(path, ns=(stamp, stamp))


def _blocks(agent: Agent, word: str) -> bool:
    return agent._apply_output_filter(word) == ""


def test_an_edited_filter_is_applied_and_a_broken_edit_keeps_the_last_good_rules(tmp_path: Path) -> None:
    agent = _character(tmp_path, "first")
    rules = agent.output_filter_file
    assert rules == paths.ROOT / "data" / "output_filter.en.json"
    assert _blocks(agent, "first")
    # A file put back from a copy is older; a rewrite may keep its time and change its size.
    _rules(rules, "restored", STAMP - 10_000_000_000)
    assert _blocks(agent, "restored")
    _rules(rules, "changed-size", STAMP - 10_000_000_000)
    assert _blocks(agent, "changed-size")
    rules.write_text("{broken", encoding="utf-8")
    assert _blocks(agent, "changed-size")
    _rules(rules, "repaired", STAMP + 10_000_000_000)
    assert _blocks(agent, "repaired")
    rules.unlink()
    assert agent._apply_output_filter("repaired") == "repaired"
    _rules(rules, "recreated", STAMP)
    assert _blocks(agent, "recreated")


def test_a_filter_file_that_cannot_be_read_for_a_moment_keeps_its_rules(tmp_path: Path, monkeypatch) -> None:
    agent = _character(tmp_path, "blocked")
    rules = agent.output_filter_file
    assert _blocks(agent, "blocked")
    real_stat = Path.stat

    def unavailable(path, *args, **kwargs):
        if path == rules:
            raise PermissionError("temporarily unavailable")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as moment:
        moment.setattr(Path, "stat", unavailable)
        assert _blocks(agent, "blocked")
    assert _blocks(agent, "blocked")
