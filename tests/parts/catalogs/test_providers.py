"""The model providers the setup offers (setup_wizard.PROVIDERS), and the settings template that starts with what
the page fills in."""
from __future__ import annotations

import re
from pathlib import Path

from dotenv import dotenv_values

from mibo import setup_wizard as sw
from mibo.config_env import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL

TEMPLATE = Path(__file__).resolve().parents[3] / ".env.example"


def test_every_provider_has_an_address_a_model_and_where_keys_come_from() -> None:
    assert [p.key for p in sw.PROVIDERS] == [
        "openrouter", "deepseek", "siliconflow", "bailian", "zhipu", "moonshot", "ark", "minimax", "qianfan",
        "hunyuan", "openai", "anthropic", "gemini", "xai", "mistral", "groq", "ollama", "lmstudio", "other"]
    # DeepSeek first for Chinese, OpenRouter first elsewhere.
    assert sw.providers_for("zh")[0].key == "deepseek" and sw.providers_for("en")[0].key == "openrouter"
    for p in sw.PROVIDERS[:-1]:
        assert p.base_url.startswith("https://") or not p.needs_key, p.key
        assert p.model, p.key
        assert p.key_url or not p.needs_key, p.key
        assert sw.provider_for_base(p.base_url) is p, p.key
    assert sw.provider_for_base("https://api.openai.com/").key == "openai"
    deepseek = sw.provider_named("deepseek")
    assert (deepseek.base_url, deepseek.model) == (DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL)


def test_the_env_template_reads_top_down() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    values = dotenv_values(TEMPLATE)
    assert list(values)[:6] == ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "PERSONA_NAME", "PERSONA_AVATAR",
                                "AGENT_LANG"]
    # Every comment on its own line, so no value reads a comment's words.
    assert [line for line in text.splitlines() if not line.lstrip().startswith("#") and re.search(r"\s#", line)] == []
    assert [key for key, value in values.items() if value and value.lstrip().startswith("#")] == []
    assert values["PERSONA_TZ_OFFSET_HOURS"] == ""
    assert (values["LLM_BASE_URL"], values["LLM_MODEL"]) == (sw.PROVIDERS[0].base_url, sw.PROVIDERS[0].model)
    # Present tense, no release history.
    assert not re.search(r"\b(since|in|until) 0\.\d|before it existed|as they were|used to\b", text)
