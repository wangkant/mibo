"""The chat languages: memory commands, their replies and the failure line
in every language in `chatlangs`, each checked against
its own cases in tests/chat_language_cases/<code>.json.

A case file holds the persona's name in that language and:
- commands: a message and the command it is ("remember" with the "note"
  kept, "forget" with the note it "deletes", "recall"), or null
  for conversation that must stay conversation;
- first_person: a note and whether it is about the person saving it;
- detect: a message and the chat language `chatlangs.detect` must name.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from mibo import chatlangs

from helpers import check, isolated_agent

CASES = Path(__file__).with_name("chat_language_cases")


def _cases(code: str) -> dict:
    return json.loads((CASES / f"{code}.json").read_text(encoding="utf-8"))


def _fields(template: str) -> set:
    return set(re.findall(r"\{(\w+)\}", template))


def _agent(tmp: Path, code: str, name: str):
    lang = "zh" if code in ("zh", "zh-TW") else "en"
    return isolated_agent(tmp, persona_name=name, lang=lang)


def test_every_chat_language_is_written_and_has_cases() -> None:
    for code in chatlangs.CODES:
        check(f"{code} has a spec", code in chatlangs.SPECS)
        check(f"{code} has a case file", (CASES / f"{code}.json").is_file())


@pytest.mark.parametrize("code", sorted(chatlangs.SPECS))
def test_the_lines_a_language_says_have_their_keys_and_fields(code: str) -> None:
    spec = chatlangs.SPECS[code]
    check(f"{code}: its code", spec.code == code)
    check(f"{code}: every reply key", set(spec.replies) == set(chatlangs.REPLY_KEYS),
          repr(sorted(set(spec.replies) ^ set(chatlangs.REPLY_KEYS))))
    for key, lines in spec.replies.items():
        check(f"{code}/{key}: some lines", bool(lines) and isinstance(lines, tuple))
        for line in lines:
            want = ({"name"} if key in ("about", "from") else {"code"} if key == "approval_dm"
                    else set())
            check(f"{code}/{key}: {line!r} fields", _fields(line) == want)
    check(f"{code}: failure lines", bool(spec.failure_excuses))


@pytest.mark.parametrize("code", sorted(chatlangs.SPECS))
def test_memory_commands_in_each_language(tmp: Path, code: str) -> None:
    cases = _cases(code)
    kinds = [c["kind"] for c in cases["commands"]]
    for kind, least in (("remember", 3), ("forget", 2), (None, 4), ("recall", 1)):
        check(f"{code}: at least {least} {kind or 'conversation'} cases",
              kinds.count(kind) >= least)
    for i, case in enumerate(cases["commands"]):
        text, kind = case["text"], case["kind"]
        agent = _agent(tmp / f"{code}-{i}", code, cases["name"])
        parsed = agent._parse_memory_command(text)
        if kind is None:
            # A forget that names nothing ("forget it") is read as "forget what was just said".
            check(f"{code}: conversation, not a command: {text!r}",
                  parsed is None or parsed[0] == "forget_that", repr(parsed))
            continue
        # A forget whose object is a pointing word ("das mit dem Treffen") is read as "forget what was just said".
        check(f"{code}: {text!r} is {kind} in {code}",
              parsed is not None and parsed[2] == code
              and (parsed[0] == kind or (kind == "forget" and parsed[0] == "forget_that")),
              repr(parsed))


@pytest.mark.parametrize("code", sorted(chatlangs.SPECS))
def test_first_person_and_detection_in_each_language(code: str) -> None:
    cases = _cases(code)
    spec = chatlangs.SPECS[code]
    check(f"{code}: first-person cases", len(cases["first_person"]) >= 2)
    for case in cases["first_person"]:
        found = bool(re.search(spec.first_person, case["text"], re.IGNORECASE))
        check(f"{code}: {case['text']!r} is about the saver: {case['mine']}",
              found is case["mine"])
    check(f"{code}: detection cases", len(cases["detect"]) >= 3)
    for case in cases["detect"]:
        got = chatlangs.detect(case["text"], case.get("default", "en"))
        check(f"{code}: {case['text']!r} reads as {case['code']}", got == case["code"],
              got)


@pytest.mark.parametrize("code", sorted(chatlangs.SPECS))
def test_the_failure_line_answers_in_the_language_asked(tmp: Path, code: str) -> None:
    cases = _cases(code)
    agent = _agent(tmp, code, cases["name"])
    asked = next(c["text"] for c in cases["detect"] if c["code"] == code)
    check(f"{code}: a failed model call answers {asked!r} in {code}",
          agent._model_failure_excuse(asked) in chatlangs.SPECS[code].failure_excuses)


def test_a_language_outside_the_ten_still_has_a_failure_line(tmp: Path) -> None:
    agent = _agent(tmp, "en", "Nova")
    agent.chat_lang = "it"   # settings keep an unknown code, with a warning
    check("an unknown language falls back to the English lines",
          agent._model_failure_excuse("???") in chatlangs.SPECS["en"].failure_excuses)
