"""The chat languages (mibo/chatlangs): each of the ten is written out, says every line a memory command answers
with, knows when a note is about the person saving it, is told apart in a message, and answers a failed model call
in the language it was asked in. Each language's cases are tests/data/chat_language_cases/<code>.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mibo import chatlangs
from mibo.agent import Agent
from mibo.settings import AgentSettings

CASES = Path(__file__).resolve().parents[2] / "data" / "chat_language_cases"


def _cases(code: str) -> dict:
    return json.loads((CASES / f"{code}.json").read_text(encoding="utf-8"))


def test_every_chat_language_is_written_and_has_cases() -> None:
    assert sorted(chatlangs.SPECS) == sorted(chatlangs.CODES)
    assert sorted(path.stem for path in CASES.glob("*.json")) == sorted(chatlangs.CODES)


@pytest.mark.parametrize("code", chatlangs.CODES)
def test_every_line_a_language_says_is_there_and_fills_no_placeholder(code: str) -> None:
    spec = chatlangs.SPECS[code]
    assert spec.code == code
    assert set(spec.replies) == set(chatlangs.REPLY_KEYS)
    for key, lines in spec.replies.items():
        assert lines and isinstance(lines, tuple), f"{code}/{key}"
        assert [line for line in lines if re.search(r"\{\w+\}", line)] == [], f"{code}/{key}"
    assert spec.failure_excuses


@pytest.mark.parametrize("code", chatlangs.CODES)
def test_a_note_about_the_saver_and_the_language_of_a_message_are_told_apart(code: str) -> None:
    cases, spec = _cases(code), chatlangs.SPECS[code]
    assert len(cases["first_person"]) >= 2 and len(cases["detect"]) >= 3
    for case in cases["first_person"]:
        assert bool(re.search(spec.first_person, case["text"], re.IGNORECASE)) is case["mine"], case["text"]
    for case in cases["detect"]:
        assert chatlangs.detect(case["text"], case.get("default", "en")) == case["code"], case["text"]


def test_a_failed_model_call_answers_in_the_language_asked(tmp_path: Path) -> None:
    character = Agent(AgentSettings(api_key="test-key", persona_name="Nova", lang="en", persona="A friend.",
                                    memory_file=str(tmp_path / "memory.json")))
    for code in chatlangs.CODES:
        asked = next(case["text"] for case in _cases(code)["detect"] if case["code"] == code)
        assert character._model_failure_excuse(asked) in chatlangs.SPECS[code].failure_excuses, asked
    # The settings keep a language outside the ten, with a warning; its failure line is English.
    character.chat_lang = "it"
    assert character._model_failure_excuse("???") in chatlangs.SPECS["en"].failure_excuses
