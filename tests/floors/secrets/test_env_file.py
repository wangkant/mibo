"""The .env writer (setup_wizard.write_env), through which keys, connector secrets and the character's name
are saved: every value reads back as written, and no value can write a line of its own, so nothing a page
or a connector hands over can replace the key or the address it is sent to."""
from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from mibo import setup_wizard as sw


@pytest.mark.parametrize("value", [
    "Zed #1", "#hash", " padded ", "it's", 'say "hi"', "a\\b", "C:\\Program Files\\x", "plain",
    "key-with-dash_and.dot", "sk-abc # not a comment", "'quoted'"])
def test_every_value_reads_back_through_dotenv_as_written(tmp_path: Path, value: str) -> None:
    env = tmp_path / ".env"
    env.write_text("# keep\nPERSONA_NAME=before\n", encoding="utf-8")
    sw.write_env(env, {"PERSONA_NAME": value, "ADMIN_NAME": value})
    assert dotenv_values(env)["PERSONA_NAME"] == value
    assert dotenv_values(env)["ADMIN_NAME"] == value
    assert sw.env_get(env, "PERSONA_NAME") == value.strip()
    assert env.read_text(encoding="utf-8").startswith("# keep\n")


def test_no_value_can_write_a_line_of_its_own(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    sw.write_env(env, {"LLM_API_KEY": "sk-real", "LLM_BASE_URL": "https://api.example.com"})
    tricks = {"PERSONA_NAME": "a\u2028LLM_BASE_URL=https://evil.example",
              "ADMIN_NAME": "b\x0bLLM_BASE_URL=https://evil.example\x85c",
              "ADMIN_RELATIONSHIP": "朋友\u3000#1"}
    sw.write_env(env, tricks)
    # A later write must not split what an earlier one wrote, either.
    sw.write_env(env, {"LLM_MODEL": "m"})
    values = dotenv_values(env)
    assert (values["LLM_API_KEY"], values["LLM_BASE_URL"]) == ("sk-real", "https://api.example.com")
    for key, value in tricks.items():
        assert values[key] == value, key


def test_a_plain_value_is_written_bare() -> None:
    assert sw.set_env_values("", {"A": "https://api.example.com/v1", "B": "C:\\x\\y"}) \
        == "A=https://api.example.com/v1\nB=C:\\x\\y"
