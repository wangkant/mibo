"""Tests for the one record the agent is configured from.

The promises `settings.py` makes:

1. `AgentSettings()` reads the environment for the operational knobs only, so
   an embedder's own `model=` is never overridden by the surrounding `.env`.
2. `from_env()` reads the deployment, bounds included, from the same defaults
   as the constructor and `.env.example`.
3. The empty-model fallbacks resolve in dependency order, never to "".
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from persona_agent.config_env import (DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL,
                                      vision_endpoint_from_env)
from persona_agent.settings import AgentSettings

from helpers import check


#: A deployment `.env` with every setting set to something distinctive.
FULL_ENV = {
    "LLM_API_KEY": "sk-live", "LLM_BASE_URL": "https://llm.example/v1/",
    "LLM_MODEL": "live-model", "PERSONA_NAME": "Live",
    "MEMORY_FILE": "m.json", "MEMORY_MAX_PER_CONVERSATION": "9",
    "ADMIN_NAME": "O", "ADMIN_RELATIONSHIP": "rel",
    "LLM_DM_MODEL": "dm-model", "LLM_FALLBACK_MODEL": "cheap-model",
    "LLM_FALLBACK_BASE_URL": "https://fb.example/v1/", "LLM_FALLBACK_API_KEY": "sk-fb",
    "LLM_FALLBACK_THINKING": "true",
    "LLM_RATE_WINDOW_S": "13", "LLM_RATE_THRESHOLD": "14", "LLM_FALLBACK_DURATION_S": "15",
    "LLM_RATE_LIMIT_COOLDOWN_S": "16",
    "VISION_MODEL": "v-model", "VISION_API_KEY": "vk", "TAVILY_API_KEY": " tav ",
    "VISION_BASE_URL": "https://vision.example/v4/", "AGENT_LANG": " ZH ",
}


def test_the_vision_endpoint_reads_its_names() -> None:
    """VISION_API_KEY / VISION_BASE_URL carry no vendor default: the model
    VISION_MODEL names decides the provider."""
    new = vision_endpoint_from_env({"VISION_API_KEY": "vk",
                                    "VISION_BASE_URL": "https://v.example/v4/"})
    check("vision: the names are read, trailing slash trimmed",
          new == ("vk", "https://v.example/v4"), repr(new))
    check("vision: no default endpoint",
          vision_endpoint_from_env({"VISION_API_KEY": "vk"}) == ("vk", ""))
    check("vision: nothing set is nothing configured",
          vision_endpoint_from_env({}) == ("", ""))
    s = AgentSettings.from_env(env={"LLM_API_KEY": "k", "VISION_API_KEY": "vk",
                                    "VISION_BASE_URL": "https://v.example/v4/"})
    check("vision: from_env reads them",
          (s.vision_api_key, s.vision_base_url) == ("vk", "https://v.example/v4"),
          repr((s.vision_api_key, s.vision_base_url)))


def test_plain_construction_ignores_deployment_settings() -> None:
    """The constructor's own defaults, not the `.env` around it."""
    plain = AgentSettings(api_key="k")
    check("plain: literal endpoint default",
          plain.model == DEFAULT_LLM_MODEL and plain.base_url == DEFAULT_LLM_BASE_URL,
          repr((plain.model, plain.base_url)))
    check("plain: the same fallback time .env.example documents", plain.llm_fallback_duration_s == 180)
    check("plain: a 429 cools for seconds, not the failure window",
          plain.llm_rate_limit_cooldown_s == 20, repr(plain.llm_rate_limit_cooldown_s))
    empty = AgentSettings.from_env(env={}, api_key="k")
    check("an empty environment gives the documented knob defaults",
          (empty.roam_walks_a_day, empty.llm_timeout_s) == (3, 120.0))


def test_from_env_reads_the_deployment() -> None:
    s = AgentSettings.from_env(env=FULL_ENV)
    check("from_env: key, model, endpoint",
          (s.api_key, s.model) == ("sk-live", "live-model"))
    check("from_env: trailing slash trimmed off every base url",
          (s.base_url, s.vision_base_url, s.llm_fallback_base_url)
          == ("https://llm.example/v1",
              "https://vision.example/v4", "https://fb.example/v1"), repr(s.base_url))
    check("from_env: the fallback's own key", s.llm_fallback_api_key == "sk-fb")
    unset = AgentSettings.from_env(env={"LLM_API_KEY": "k"})
    check("from_env: an unset fallback endpoint stays blank, meaning the primary's",
          (unset.llm_fallback_base_url, unset.llm_fallback_api_key) == ("", ""),
          repr((unset.llm_fallback_base_url, unset.llm_fallback_api_key)))
    check("from_env: a fallback endpoint is sent `thinking` only when told it takes it",
          s.llm_fallback_thinking is True and unset.llm_fallback_thinking is False)
    check("from_env: bounded integers", s.memory_max_per_conversation == 9)
    check("from_env: the two cooldowns are read separately",
          (s.llm_fallback_duration_s, s.llm_rate_limit_cooldown_s) == (15, 16),
          repr((s.llm_fallback_duration_s, s.llm_rate_limit_cooldown_s)))
    check("from_env: .env.example's defaults are the ones that apply",
          AgentSettings.from_env(env={}).llm_fallback_duration_s == 180)
    check("from_env: language normalised", s.agent_lang == "zh", s.agent_lang)
    check("from_env: the admin's name and relationship",
          (s.admin_name, s.admin_relationship) == ("O", "rel"))
    check("from_env: overrides beat the environment",
          AgentSettings.from_env(env=FULL_ENV, persona_name="Override").persona_name
          == "Override")


def test_an_out_of_range_setting_falls_back_rather_than_raising() -> None:
    """A typo in one setting has to behave like a typo in any other: the
    documented default, and the process still starts."""
    s = AgentSettings.from_env(env={
        "LLM_API_KEY": "k", "MEMORY_MAX_PER_CONVERSATION": "0", "ROAM_GAP_HOURS": "lots",
        "LLM_TIMEOUT_S": "0", "LLM_RATE_LIMIT_COOLDOWN_S": "0",
    })
    check("bad values: bounded ints fall back", s.memory_max_per_conversation == 50)
    check("bad values: unparseable float falls back", s.roam_gap_h == 3.0)
    check("bad values: out-of-range timeout falls back", s.llm_timeout_s == 120.0)
    check("bad values: out-of-range 429 cooldown falls back",
          s.llm_rate_limit_cooldown_s == 20, repr(s.llm_rate_limit_cooldown_s))


def _template_values() -> dict[str, str]:
    """`KEY=value` lines of `.env.example`, an inline `# comment` cut off."""
    text = (Path(__file__).resolve().parent.parent / ".env.example").read_text(
        encoding="utf-8")
    values = {}
    for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.MULTILINE):
        values[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip()
    return values


#: Fields the comparison below cannot hold equal by construction: `lang` is
#: the raw input `agent_lang` is resolved from.
_NOT_DEFAULTS = {"lang"}
#: The template starts a new setup on the first preset, while an unset endpoint
#: keeps meaning DeepSeek, for a .env holding only that key.
_NEW_SETUP_ONLY = {"LLM_BASE_URL", "LLM_MODEL"}


def test_one_source_of_defaults(monkeypatch) -> None:
    """The constructor, `from_env()` and `.env.example` agree on every default,
    so a setting left out means the same thing to an embedder, to the bot
    process and to someone reading the template. Compared by value through
    the parser, not by line, so the template can be reordered."""
    template = _template_values()
    for name in template:
        monkeypatch.delenv(name, raising=False)
    plain = AgentSettings(api_key="k")
    env_defaults = AgentSettings.from_env(env={"LLM_API_KEY": "k"})
    documented = AgentSettings.from_env(env={**{k: v for k, v in template.items() if k not in _NEW_SETUP_ONLY},
                                             "LLM_API_KEY": "k"})
    for f in dataclasses.fields(AgentSettings):
        if f.name in _NOT_DEFAULTS:
            continue
        a, b, c = (getattr(s, f.name) for s in (plain, env_defaults, documented))
        check(f"constructor and from_env agree on {f.name}", a == b, repr((a, b)))
        check(f".env.example documents the default of {f.name}", b == c, repr((b, c)))
    check("...and the comparison covered the settings it is about",
          {"LLM_FALLBACK_DURATION_S", "ROAM_GAP_HOURS", "MEMORY_TIDY_EVERY"}
          <= set(template), repr(sorted(template)[:8]))


def test_from_env_takes_each_default_from_its_field(monkeypatch) -> None:
    """`from_env()` restated the literal default beside every setting it
    read, so a default lived in two places that only a test kept equal. It
    reads the field's own now: change one there and both paths follow."""
    declared = AgentSettings.__dataclass_fields__
    moved = {
        "base_url": "https://moved.example/v1", "model": "moved-model",
        "memory_file": "moved.json",
        "memory_max_per_conversation": 51, "memory_tidy_every": 9,
        "llm_fallback_thinking": True,
        "llm_fallback_duration_s": 181, "llm_rate_limit_cooldown_s": 21,
    }
    for name, value in moved.items():
        check(f"{name} starts from another default",
              declared[name].default != value, repr(declared[name].default))
        monkeypatch.setattr(declared[name], "default", value)
    s = AgentSettings.from_env(env={"LLM_API_KEY": "k"})
    for name, value in moved.items():
        check(f"from_env: an unset {name} is the field's default",
              getattr(s, name) == value, repr(getattr(s, name)))
    s = AgentSettings.from_env(env=FULL_ENV)
    check("from_env: a set value still wins over it",
          (s.memory_file, s.model) == ("m.json", "live-model"), repr(s.memory_file))


def test_agent_lang_spellings_are_normalised() -> None:
    from persona_agent.settings import normalize_lang

    for raw, want in (("zh-CN", "zh"), ("zh_cn", "zh"), ("cn", "zh"),
                      ("Chinese", "zh"), (" ZH ", "zh"), ("en-US", "en"),
                      ("english", "en"), ("", "en"), ("ja", "ja")):
        check(f"AGENT_LANG={raw!r} reads as {want}", normalize_lang(raw) == want,
              normalize_lang(raw))
    s = AgentSettings.from_env(env={"LLM_API_KEY": "k", "AGENT_LANG": "zh_CN"})
    check("from_env: the ledgers and prompts see zh",
          s.agent_lang == "zh", s.agent_lang)
    check("constructor: lang is normalised too",
          AgentSettings(api_key="k", lang="en-GB").agent_lang == "en")


def test_the_empty_model_fallbacks_resolve_in_order() -> None:
    bare = AgentSettings(api_key="k", model="main")
    check("blank fallback model becomes the main model",
          bare.llm_fallback_model == "main")
    check("blank private model becomes the main model",
          bare.llm_dm_model == "main")
    check("judge model follows the cheap model",
          AgentSettings(api_key="k", model="main",
                        llm_fallback_model="cheap").llm_judge_model == "cheap")
    chain = AgentSettings(api_key="k", model="main", llm_fallback_model="cheap",
                          llm_judge_model="judge")
    check("an explicit judge model is kept", chain.llm_judge_model == "judge")


def test_post_init_is_idempotent() -> None:
    """`dataclasses.replace` re-runs it, and so does anything that rebuilds a
    record from another one's fields. Resolving twice must change nothing."""
    import dataclasses

    s = AgentSettings.from_env(env=FULL_ENV)
    again = dataclasses.replace(s)
    differing = [f.name for f in dataclasses.fields(s)
                 if getattr(s, f.name) != getattr(again, f.name)]
    check("re-resolving a resolved record changes nothing",
          not differing, repr(differing))


def test_the_agent_accepts_the_record_and_its_fields() -> None:
    """Both doors, and no ambiguous third one."""
    import tempfile
    import os

    from persona_agent.agent import Agent

    previous_home = os.environ.get("AGENT_HOME")
    with tempfile.TemporaryDirectory() as d:
        os.environ["AGENT_HOME"] = d
        paths = dict(memory_file=str(Path(d) / "memory.json"))
        settings = AgentSettings(api_key="k", persona_name="B",
                                 model="m", lang="en", **paths)
        from_record = Agent(settings)
        from_kwargs = Agent(api_key="k", persona_name="B", model="m",
                            lang="en", **paths)
        check("a record and its keywords build the same agent",
              from_record.settings == from_kwargs.settings)
        check("the record is kept whole on the agent",
              from_record.settings is settings)
    if previous_home is None:
        os.environ.pop("AGENT_HOME", None)
    else:
        os.environ["AGENT_HOME"] = previous_home


def test_settings_named_in_log_messages_exist() -> None:
    """A log line that tells the operator to change a setting must name one
    that exists."""
    import ast
    import re

    root = Path(__file__).resolve().parent.parent
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    known = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", env_example, re.MULTILINE))
    name = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9]\b")
    unknown = []
    for path in sorted((root / "persona_agent").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"):
                continue
            for part in ast.walk(node.args[0]):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    unknown += [f"{path.name}:{node.lineno} {setting}"
                                for setting in name.findall(part.value)
                                if setting not in known]
    check("log messages name only real settings", not unknown, repr(unknown))


def test_the_memory_settings_round_trip_and_keep_their_old_defaults() -> None:
    """The four memory settings read from the environment and fall back on a
    bad value; the two whose meaning changed keep their defaults."""
    s = AgentSettings.from_env(env={
        "LLM_API_KEY": "k", "MEMORY_CALLS_PER_DAY": "0", "MEMORY_PROMPT_CHARS": "900",
        "MEMORY_EPISODES_MAX": "7", "MEMORY_KEEP_RECENT": "false"})
    check("from_env: the memory settings are read",
          (s.memory_calls_per_day, s.memory_prompt_chars, s.memory_episodes_max,
           s.memory_keep_recent) == (0, 900, 7, False),
          repr((s.memory_calls_per_day, s.memory_prompt_chars)))
    plain = AgentSettings(api_key="k")
    check("the defaults", (plain.memory_calls_per_day, plain.memory_prompt_chars,
                           plain.memory_episodes_max, plain.memory_keep_recent)
          == (40, 2400, 120, True))
    check("the changed-meaning settings keep their defaults", plain.memory_tidy_every == 8)
    bad = AgentSettings.from_env(env={
        "LLM_API_KEY": "k", "MEMORY_CALLS_PER_DAY": "-1", "MEMORY_PROMPT_CHARS": "5",
        "MEMORY_EPISODES_MAX": "x"})
    check("bad values fall back to the defaults",
          (bad.memory_calls_per_day, bad.memory_prompt_chars,
           bad.memory_episodes_max) == (40, 2400, 120))
