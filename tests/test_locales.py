"""mibo/locales/: every language has every key, with its slots, in its own script."""
from __future__ import annotations

import pytest

from mibo import i18n, langs
from tools import locale_gaps

from helpers import check


@pytest.mark.parametrize("code", [code for code in langs.CODES if code != "en"])
def test_every_language_has_every_key(code: str) -> None:
    problems = locale_gaps.problems(code)
    check(f"locales/{code}.json has no gaps", not problems, "\n".join(problems))


def test_the_interface_language_follows_the_env_file(tmp_path, monkeypatch) -> None:
    """A rewritten .env must be read again, and so must another home."""
    monkeypatch.delenv("UI_LANG", raising=False)
    monkeypatch.delenv("AGENT_LANG", raising=False)
    monkeypatch.setenv("AGENT_HOME", str(tmp_path))
    env = tmp_path / ".env"
    env.write_text("AGENT_LANG=ja", encoding="utf-8")
    check("read from the home's .env", i18n.lang() == "ja", i18n.lang())
    env.write_text("AGENT_LANG=de  # switched", encoding="utf-8")
    check("a rewritten file is read again", i18n.lang() == "de", i18n.lang())
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("AGENT_LANG=ko", encoding="utf-8")
    monkeypatch.setenv("AGENT_HOME", str(other))
    check("another home has its own answer", i18n.lang() == "ko", i18n.lang())

