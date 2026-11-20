"""The character's name and the nicknames on its card, where a memory command begins with one.

    python -m pytest tests/test_addressing.py
"""
from __future__ import annotations

import json
from pathlib import Path

from persona_agent import agent as agent_module

from helpers import check, isolated_agent


def _agent_with_card(tmp: Path, monkeypatch, card: dict, name: str, lang: str):
    (tmp / "persona.card.json").write_text(json.dumps(card), encoding="utf-8")
    monkeypatch.setattr(agent_module, "ROOT", tmp)
    monkeypatch.setenv("PERSONA_CARD_FILE", "persona.card.json")
    return isolated_agent(tmp / "state", persona_name=name, lang=lang)


def test_the_persona_card_gives_the_character_its_nicknames(tmp, monkeypatch) -> None:
    a = _agent_with_card(tmp, monkeypatch, {"aliases": ["鲸鱼", " ", 7]}, "鲸鱼娘", "zh")
    check("the card's aliases are read, blanks and non-text dropped",
          a.persona_aliases == ("鲸鱼",), str(a.persona_aliases))
    parsed = a._parse_memory_command("鲸鱼，记住 我下周搬家")
    check("a memory command through the nickname is a command",
          parsed is not None and parsed[0] == "remember"
          and "下周搬家" in parsed[1], str(parsed))


def test_no_card_means_no_nicknames(tmp, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "ROOT", tmp)
    monkeypatch.setenv("PERSONA_CARD_FILE", "persona.card.json")
    a = isolated_agent(tmp / "state", persona_name="Sofía")
    check("no aliases", a.persona_aliases == ())
    parsed = a._parse_memory_command("sofia, remember I moved to Lisbon")
    check("and a memory command written without the accent is a command",
          parsed is not None and parsed[0] == "remember"
          and "Lisbon" in parsed[1], str(parsed))
