"""The interface languages (mibo/locales): every language has every key with its slots in its own script, the
language follows the home's .env, and a first run starts in the system's language."""
from __future__ import annotations

import pytest

from mibo import i18n, langs
from mibo import setup_wizard as sw
from tools import locale_gaps


@pytest.mark.parametrize("code", [code for code in langs.CODES if code != "en"])
def test_every_language_has_every_key(code: str) -> None:
    assert locale_gaps.problems(code) == [], f"locales/{code}.json"


def test_the_interface_language_follows_the_env_file(tmp_path, monkeypatch) -> None:
    """A rewritten .env is read again, and another home has its own answer."""
    monkeypatch.delenv("UI_LANG", raising=False)
    monkeypatch.delenv("AGENT_LANG", raising=False)
    monkeypatch.setenv("AGENT_HOME", str(tmp_path))
    env = tmp_path / ".env"
    env.write_text("AGENT_LANG=ja", encoding="utf-8")
    assert i18n.lang() == "ja"
    env.write_text("AGENT_LANG=de  # switched", encoding="utf-8")
    assert i18n.lang() == "de"
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("AGENT_LANG=ko", encoding="utf-8")
    monkeypatch.setenv("AGENT_HOME", str(other))
    assert i18n.lang() == "ko"


def test_the_system_language_picks_the_first_language(monkeypatch) -> None:
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    assert sw.detect_lang() == "zh"
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert sw.detect_lang() == "en"
    # Windows' own name for a locale, and one that names no language.
    assert sw._lang_of("Chinese (Simplified)_China") == "zh"
    assert sw._lang_of("C.UTF-8") == ""
