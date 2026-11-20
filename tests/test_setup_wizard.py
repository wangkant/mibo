"""A home's setup: providers, the persona, the .env file, the key probe and the commands it names."""
from __future__ import annotations

import contextlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from mibo import home as homes
from mibo import setup_wizard as sw
from mibo.config_env import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL
from mibo.prompts import _TEMPLATE_RULE_RE

from helpers import check

ROOT = Path(__file__).resolve().parents[1]


FAN_MADE = ("chatgpt", "deepseek", "claude")


@pytest.fixture
def portraits(monkeypatch, tmp_path_factory) -> Path:
    """Portrait sprites for the fan-made characters, never the package's own folder."""
    folder = tmp_path_factory.mktemp("portraits")
    for key in FAN_MADE:
        (folder / f"{key}.webp").write_bytes(b"RIFF\x04\x00\x00\x00WEBP")
    monkeypatch.setattr(sw, "PORTRAITS", folder)
    return folder


# ---------------------------------------------------------------------------
# Text, language, providers
# ---------------------------------------------------------------------------


def test_the_system_language_picks_the_default(monkeypatch) -> None:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    check("locale: zh_CN is Chinese", sw.detect_lang() == "zh")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    check("locale: en_US is English", sw.detect_lang() == "en")
    check("locale: Windows' own name for Chinese",
          sw._lang_of("Chinese (Simplified)_China") == "zh")
    check("locale: C.UTF-8 says nothing", sw._lang_of("C.UTF-8") == "")


def test_the_providers_are_complete() -> None:
    keys = [p.key for p in sw.PROVIDERS]
    check("providers: the nineteen choices, Other last",
          keys == ["openrouter", "deepseek", "siliconflow", "bailian", "zhipu", "moonshot", "ark",
                   "minimax", "qianfan", "hunyuan", "openai", "anthropic", "gemini", "xai", "mistral",
                   "groq", "ollama", "lmstudio", "other"], repr(keys))
    check("providers: DeepSeek first for Chinese, OpenRouter first elsewhere",
          sw.providers_for("zh")[0].key == "deepseek" and sw.providers_for("en")[0].key == "openrouter")
    for p in sw.PROVIDERS[:-1]:
        check(f"{p.key}: https or a local address",
              p.base_url.startswith("https://") or not p.needs_key, p.base_url)
        check(f"{p.key}: a default model", p.model)
        check(f"{p.key}: says where keys come from", p.key_url or not p.needs_key)
        check(f"{p.key}: found again from its base URL", sw.provider_for_base(p.base_url) is p)
    check("providers: a root written without /v1 is still recognised",
          sw.provider_for_base("https://api.openai.com/").key == "openai")
    deepseek = sw.provider_named("deepseek")
    check("providers: the DeepSeek preset is the code's default endpoint",
          (deepseek.base_url, deepseek.model) == (DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL))


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

def test_every_character_ships_in_both_languages_ready_to_use() -> None:
    for lang in sw.LANGS:
        for character in sw.CHARACTERS:
            source = sw.persona_source(character.key, lang)
            check(f"persona {lang}/{character.key}: shipped", source.is_file(), str(source))
            raw = source.read_text(encoding="utf-8")
            text = sw.persona_text(character.key, name="Mika", lang=lang)
            check(f"persona {lang}/{character.key}: no placeholders left", "{" not in text, text)
            check(f"persona {lang}/{character.key}: no alternatives to pick from",
                  not re.search(r"\b(e\.g\.|or:)|比如：|或者：", raw), raw)
            check(f"persona {lang}/{character.key}: no notes to the reader",
                  not _TEMPLATE_RULE_RE.search(raw) and "persona.txt" not in raw, raw)
            check(f"persona {lang}/{character.key}: names the character", "Mika" in text, text)
            check(f"persona {lang}/{character.key}: short", len(text) < 1200, str(len(text)))
    shipped = {p.stem for p in (ROOT / "data" / "personas" / "en").glob("*.txt")}
    check("persona: every shipped file is on the menu",
          shipped == set(sw.PERSONA_KEYS) - {sw.TEMPLATE}, repr(shipped))


def test_a_template_is_filled_and_its_notes_dropped() -> None:
    template = ("You're {bot_name}.\n"
                "- The person you're closest to is {admin_name} ({admin_relationship}).\n"
                "- Everyone else: read the room\n\n————\n"
                "This is the persona template. Copy it to persona.txt.")
    alone = sw.render_persona(template, name="Nova", lang="en")
    check("render: name filled", alone.startswith("You're Nova."), alone)
    check("render: no admin, no admin line", "closest" not in alone, alone)
    check("render: the note is gone", "template" not in alone, alone)
    with_admin = sw.render_persona(template, name="Nova", lang="en", admin_name="Kay")
    check("render: an admin without a relationship has no empty brackets",
          "closest to is Kay." in with_admin, with_admin)
    related = sw.render_persona(template, name="Nova", lang="en", admin_name="Kay",
                                admin_relationship="sister")
    check("render: relationship filled", "Kay (sister)" in related, related)
    zh = sw.render_persona("- 你最熟的人是 {admin_name}（{admin_relationship}）。\n其他", name="小夏",
                           lang="zh", admin_name="小林")
    check("render: Chinese brackets dropped too", "小林。" in zh and "（" not in zh, zh)
    check("render: a text that never names the character gets a name line",
          zh.startswith("你叫小夏。"), zh)


def test_only_an_unedited_shipped_persona_is_offered_for_replacement(monkeypatch) -> None:
    for lang in sw.LANGS:
        for character in sw.CHARACTERS:
            text = sw.persona_text(character.key, name="Mika", lang=lang)
            check(f"origin {lang}/{character.key}: recognised with its name",
                  sw.shipped_persona(text) == (character.key, lang, "Mika"),
                  repr(sw.shipped_persona(text)))
            check(f"origin {lang}/{character.key}: CRLF does not count as an edit",
                  sw.shipped_persona(text.replace("\n", "\r\n")) is not None)
            check(f"origin {lang}/{character.key}: an edit is the user's",
                  sw.shipped_persona(text + "Loves jazz.\n") is None)
    raw = sw.persona_source(sw.TEMPLATE, "en").read_text(encoding="utf-8")
    check("origin: the raw template copied as is",
          sw.shipped_persona(raw) == (sw.TEMPLATE, "en", ""))


def test_the_fan_made_characters_come_last_with_their_own_names(portraits) -> None:
    check("menu: Mibo first, the three after it, the template last",
          sw.PERSONA_KEYS == ("mibo", *FAN_MADE, sw.TEMPLATE),
          repr(sw.PERSONA_KEYS))
    check("menu: only they and Mibo have names of their own",
          [c.name_in("en") for c in sw.CHARACTERS if c.stem] == ["Mibo", "White Dragon", "Big Fish", "Milady"])
    check("name: Mibo's, the same in every language",
          [sw.character_for("mibo").name_in(lang) for lang in ("zh", "ja", "ko", "ru")] == ["Mibo"] * 4)
    check("name: by language",
          [sw.character_for("chatgpt").name_in(lang) for lang in ("zh", "zh-TW", "ja", "ko", "de")]
          == ["白龙", "白龍", "白竜", "백룡", "Weiße Drachin"])
    check("name: the default follows the character", sw.name_for("claude", "Nova", "en") == "Milady")
    check("name: the language's default too", sw.name_for("deepseek", "小夏", "zh") == "大肥鱼")
    check("name: another character's own name follows", sw.name_for("claude", "GPT-chan", "en") == "Milady")
    check("name: another character's old name follows too",
          sw.name_for("claude", "ChatGPT", "en") == "Milady")
    check("name: a home still called by the old name keeps it",
          sw.name_for("chatgpt", "ChatGPT", "en") == "ChatGPT" and sw.name_for("claude", "Claude", "zh") == "Claude")
    check("name: a chosen name stays", sw.name_for("claude", "Mira", "en") == "Mira")
    check("name: a character without one keeps the name", sw.name_for("template", "Nova", "en") == "Nova")
    check("name: leaving a fan-made character goes back to the default, as on the page",
          sw.name_for("template", "Claude", "en") == "Nova" and sw.name_for("template", "Claude娘", "en") == "Nova")
    check("portrait: the fan-made ones", [k for k in sw.PERSONA_KEYS if sw.portrait(k)] == list(FAN_MADE))
    check("portrait: none for a name that is not a character",
          sw.portrait("../portraits/claude") is None and sw.avatar_for("template") == "")
    (portraits / "claude.webp").unlink()
    check("portrait: a missing file means none", sw.avatar_for("claude") == "")


# ---------------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------------

def test_the_env_template_reads_top_down() -> None:
    from dotenv import dotenv_values

    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = dotenv_values(ROOT / ".env.example")
    keys = list(values)
    check("template: the settings the page fills in come first",
          keys[:6] == ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "PERSONA_NAME", "PERSONA_AVATAR",
                       "AGENT_LANG"],
          repr(keys[:6]))
    inline = [line for line in text.splitlines()
              if not line.lstrip().startswith("#") and re.search(r"\s#", line)]
    check("template: every comment is on its own line", not inline, repr(inline))
    check("template: nothing parses as a comment's words",
          not [k for k, v in values.items() if v and v.lstrip().startswith("#")])
    check("template: the time zone defaults to this machine",
          values["PERSONA_TZ_OFFSET_HOURS"] == "")
    check("template: the default endpoint is the first preset's",
          (values["LLM_BASE_URL"], values["LLM_MODEL"])
          == (sw.PROVIDERS[0].base_url, sw.PROVIDERS[0].model))
    check("template: present tense, no release history",
          not re.search(r"\b(since|in|until) 0\.\d|before it existed|as they were|used to\b",
                        text))


# ---------------------------------------------------------------------------
# The key probe
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def fake_openai(statuses: list[int], seen: list):
    """A local OpenAI-compatible endpoint answering with `statuses` in turn."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server's naming
            length = int(self.headers.get("Content-Length") or 0)
            seen.append((self.path, self.headers.get("Authorization"),
                         json.loads(self.rfile.read(length) or b"{}")))
            status = statuses.pop(0) if statuses else 200
            body = (b'{"choices":[{"message":{"content":"OK"}}]}' if status == 200
                    else b'{"error":{"message":"Unsupported parameter: max_tokens"}}'
                    if status == 400 else b'{"error":{"message":"nope"}}')
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


# ---------------------------------------------------------------------------
# The commands it names
# ---------------------------------------------------------------------------


def _name_and_avatar(home: Path) -> tuple[str, str]:
    return sw.env_get(home / ".env", "PERSONA_NAME"), sw.env_get(home / ".env", "PERSONA_AVATAR")


def test_the_next_steps_fit_this_machine(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AGENT_HOME", raising=False)
    launcher = sw.Launcher(python=str(homes.CHECKOUT / ".venv" / "Scripts" / "python.exe"),
                           home=homes.CHECKOUT)
    if homes.is_checkout():
        lines = launcher.shown("run")
        check("checkout: from the checkout, with its .venv python",
              lines[0].startswith("cd ") and lines[1].endswith("-m mibo run")
              and not Path(lines[1].split(" -m")[0]).is_absolute(), repr(lines))
        check("checkout: the chat runs from the checkout", launcher.cwd() == str(homes.CHECKOUT))
    elsewhere = sw.Launcher(python=launcher.python, home=tmp_path)
    monkeypatch.delenv("AGENT_HOME", raising=False)
    check("a home that a bare command would not find is named, set or not",
          "--home" in " ".join(elsewhere.shown("chat")))
    monkeypatch.setenv("AGENT_HOME", str(tmp_path))
    check("--home is carried into the commands", "--home" in " ".join(elsewhere.shown("chat"))
          and elsewhere.argv("chat")[-3:] == ["--home", str(tmp_path), "chat"])
