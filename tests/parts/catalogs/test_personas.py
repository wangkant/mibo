"""The characters the app ships (data/personas), the persona template a person copies, and the persona card: what
reaches the character is ready to use in every language, and a person's own text is theirs."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mibo import paths
from mibo import setup_wizard as sw
from mibo.agent import Agent
from mibo.prompts import _TEMPLATE_RULE_RE, render_persona_template
from mibo.settings import AgentSettings
from mibo.textproc import ReplyStyle

SHIPPED = Path(__file__).resolve().parents[3] / "data" / "personas"
FAN_MADE = ("chatgpt", "deepseek", "claude")
TEMPLATE = ("You're {bot_name}, a friend who lives on this computer.\n\n"
            "Who you talk to (optional):\n"
            "- The person you talk to is {admin_name} ({admin_relationship}). Be warm with them\n"
            "- Keep it short\n\n"
            "————\n"
            "This is the persona template. Copy it to persona.txt and rewrite it.\n")


@pytest.fixture
def portraits(monkeypatch, tmp_path_factory) -> Path:
    """Portrait sprites for the fan-made characters, never the package's own folder."""
    folder = tmp_path_factory.mktemp("portraits")
    for key in FAN_MADE:
        (folder / f"{key}.webp").write_bytes(b"RIFF\x04\x00\x00\x00WEBP")
    monkeypatch.setattr(sw, "PORTRAITS", folder)
    return folder


def _character(folder: Path, **settings) -> Agent:
    return Agent(AgentSettings(api_key="test-key", persona_name="Luna", lang="en",
                               memory_file=str(folder / "memory.json"), **settings))


def test_every_character_ships_in_every_language_ready_to_use() -> None:
    for lang in sw.LANGS:
        for character in sw.CHARACTERS:
            where = f"{lang}/{character.key}"
            source = sw.persona_source(character.key, lang)
            assert source.is_file(), where
            raw = source.read_text(encoding="utf-8")
            text = sw.persona_text(character.key, name="Mika", lang=lang)
            assert "{" not in text, where
            # No alternatives to pick from, and no notes to the reader.
            assert not re.search(r"\b(e\.g\.|or:)|比如：|或者：", raw), where
            assert not _TEMPLATE_RULE_RE.search(raw) and "persona.txt" not in raw, where
            assert "Mika" in text and len(text) < 1200, where
    assert {p.stem for p in (SHIPPED / "en").glob("*.txt")} == set(sw.PERSONA_KEYS) - {sw.TEMPLATE}


def test_only_an_unedited_shipped_persona_is_offered_for_replacement() -> None:
    for lang in sw.LANGS:
        for character in sw.CHARACTERS:
            text = sw.persona_text(character.key, name="Mika", lang=lang)
            assert sw.shipped_persona(text) == (character.key, lang, "Mika")
            # CRLF is no edit; a line added is the person's.
            assert sw.shipped_persona(text.replace("\n", "\r\n")) is not None
            assert sw.shipped_persona(text + "Loves jazz.\n") is None
    raw = sw.persona_source(sw.TEMPLATE, "en").read_text(encoding="utf-8")
    assert sw.shipped_persona(raw) == (sw.TEMPLATE, "en", "")


def test_a_template_is_filled_and_its_notes_dropped_by_the_setup_as_by_the_character() -> None:
    alone = render_persona_template(TEMPLATE, bot_name="Luna")
    assert alone.startswith("You're Luna, a friend")
    # No person named: the line about one goes, the rest stays.
    assert "{admin" not in alone and "talk to is" not in alone and "Keep it short" in alone
    assert "persona.txt" not in alone and "————" not in alone
    assert "talk to is Kai. Be warm" in render_persona_template(TEMPLATE, bot_name="Luna", admin_name="Kai")
    assert "talk to is Kai (sister)." in render_persona_template(TEMPLATE, bot_name="Luna", admin_name="Kai",
                                                                  admin_relationship="sister")
    out = render_persona_template("Hi.\n- {admin_name}, your {admin_relationship}\nBye.", bot_name="Luna",
                                  admin_name="Kai")
    assert out == "Hi.\nBye.", "a line that cannot lose its relationship cleanly is dropped"
    # No name: no sentence naming nobody.
    assert render_persona_template("Your name is {bot_name}. You like books.", bot_name="") == "You like books."
    assert render_persona_template("你叫{bot_name}，喜欢读书。", bot_name="", lang="zh") == "喜欢读书。"
    zh = sw.render_persona("- 你最熟的人是 {admin_name}（{admin_relationship}）。\n其他", name="小夏", lang="zh",
                           admin_name="小林")
    assert "小林。" in zh and "（" not in zh
    assert zh.startswith("你叫小夏。"), "a text that never names the character gets a name line"
    named = TEMPLATE.replace("{bot_name}", "Your name is {bot_name}. Hi")
    for admin in ("", "Kai"):
        assert sw.render_persona(named, name="Luna", lang="en", admin_name=admin) \
            == render_persona_template(named, bot_name="Luna", admin_name=admin) + "\n"


def test_a_persons_own_persona_is_cut_only_at_a_template_note() -> None:
    for own in ("I'm Mira.\n---\nSecond section, kept.",
                "I'm Mira.\n===\nMy notes live in persona.txt, my diary elsewhere.",
                "I'm Mira.\n---\nThe template I started from is long gone.\n\npersona.txt is mine now."):
        assert render_persona_template(own, bot_name="Luna") == own


def test_a_persona_file_reaches_the_character_filled_and_a_note_alone_gives_the_first_character(tmp_path) -> None:
    persona = paths.ROOT / "persona.txt"
    persona.write_text(TEMPLATE, encoding="utf-8")
    filled = _character(tmp_path / "a").persona
    assert filled.startswith("You're Luna") and "{" not in filled and "persona.txt" not in filled
    persona.write_text("————\nThis is the persona template. Copy it to persona.txt.", encoding="utf-8")
    first = _character(tmp_path / "b").persona
    shipped = sw.persona_text(sw.CHARACTERS[0].key, name="Luna", lang="en")
    assert first.splitlines()[0] == shipped.splitlines()[0] and "persona.txt" not in first


def test_the_persona_card_gives_the_reply_style_or_the_default(tmp_path) -> None:
    (paths.ROOT / "persona.card.json").write_text(
        json.dumps({"name": "Kai", "reply_style": {"emoji": True, "max_chars": 320}}), encoding="utf-8")
    style = _character(tmp_path, persona="A friend.").reply_style
    assert (style.allow_emoji, style.max_chars) == (True, 320)
    for unusable in ({}, {"reply_style": None}, {"reply_style": "yes"}, None):
        assert ReplyStyle.from_card(unusable) == ReplyStyle()


def test_the_fan_made_characters_come_last_with_their_own_names(portraits) -> None:
    assert sw.PERSONA_KEYS == ("mibo", *FAN_MADE, sw.TEMPLATE)
    assert [c.name_in("en") for c in sw.CHARACTERS if c.stem] == ["Mibo", "White Dragon", "Big Fish", "Milady"]
    assert [sw.character_for("mibo").name_in(lang) for lang in ("zh", "ja", "ko", "ru")] == ["Mibo"] * 4
    assert [sw.character_for("chatgpt").name_in(lang) for lang in ("zh", "zh-TW", "ja", "ko", "de")] \
        == ["白龙", "白龍", "白竜", "백룡", "Weiße Drachin"]
    # The default name follows the character, in the language's own form.
    assert sw.name_for("claude", "Nova", "en") == "Milady"
    assert sw.name_for("deepseek", "小夏", "zh") == "大肥鱼"
    # Another character's own name or earlier name follows too; a home called by the earlier name keeps it.
    assert sw.name_for("claude", "GPT-chan", "en") == "Milady"
    assert sw.name_for("claude", "ChatGPT", "en") == "Milady"
    assert sw.name_for("chatgpt", "ChatGPT", "en") == "ChatGPT" and sw.name_for("claude", "Claude", "zh") == "Claude"
    # A chosen name stays; a character without one keeps the name; leaving a fan-made one goes back to the default.
    assert sw.name_for("claude", "Mira", "en") == "Mira"
    assert sw.name_for("template", "Nova", "en") == "Nova"
    assert sw.name_for("template", "Claude", "en") == "Nova" and sw.name_for("template", "Claude娘", "en") == "Nova"
    assert [k for k in sw.PERSONA_KEYS if sw.portrait(k)] == list(FAN_MADE)
    assert sw.portrait("../portraits/claude") is None and sw.avatar_for("template") == ""
    (portraits / "claude.webp").unlink()
    assert sw.avatar_for("claude") == ""
