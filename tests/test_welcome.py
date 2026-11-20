"""First-run setup and the browser chat boundary."""
from __future__ import annotations


from fastapi.testclient import TestClient
import httpx
import pytest

from mibo import setup_wizard as sw
from mibo import welcome


TOKEN = "test-local-capability"
REAL_ASYNC_CLIENT = httpx.AsyncClient
HEADERS = {welcome.TOKEN_HEADER: TOKEN}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    value = welcome.Workspace(tmp_path)
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("http://127.0.0.1", 200, ""))
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    with TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace),
                    base_url="http://127.0.0.1") as value:
        yield value


def test_page_requires_no_key_but_every_api_requires_the_capability(client):
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/.env").status_code == 404
    assert client.get("/api/state").status_code == 403
    response = client.get("/api/state", headers=HEADERS)
    assert response.status_code == 200 and response.json()["configured"] is False
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.parametrize("extra", [
    {"Origin": "https://other.example"}, {"Host": "other.example"},
    {"X-Forwarded-Host": "localhost"}, {"Forwarded": "for=127.0.0.1"},
])
def test_browser_boundary_rejects_foreign_origins_and_proxy_headers(client, extra):
    assert client.get("/api/state", headers={**HEADERS, **extra}).status_code == 403


def test_one_key_is_enough_and_state_does_not_leak_it(client, workspace):
    key = "sk-local-secret-123456789"
    response = client.post("/api/config", headers=HEADERS, json={"apiKey": key, "lang": "zh"})
    assert response.status_code == 200
    assert response.json()["configured"]
    assert key not in response.text
    values = workspace.config()
    assert values["LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert values["PERSONA_NAME"] == "Mibo"
    assert (workspace.home / "persona.txt").is_file()
    assert key not in client.get("/api/state", headers=HEADERS).text


def test_invalid_key_does_not_replace_a_working_configuration(client, workspace, monkeypatch):
    sw.write_env(workspace.env, {"LLM_API_KEY": "old-key", "LLM_BASE_URL": "https://api.deepseek.com"})
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("url", 401, "echoed-sensitive-key"))
    response = client.post("/api/config", headers=HEADERS, json={"apiKey": "new-key"})
    assert response.status_code == 400 and response.json()["error"] == "key_rejected"
    assert "echoed-sensitive-key" not in response.text
    assert workspace.config()["LLM_API_KEY"] == "old-key"


def test_custom_persona_and_unrelated_settings_survive_editing(client, workspace):
    sw.write_env(workspace.env, {"LLM_API_KEY": "old-key", "LLM_BASE_URL": "https://api.deepseek.com",
                                 "ADMIN_IDS": "qq:7", "PERSONA_NAME": "Mira"})
    persona = workspace.home / "persona.txt"
    persona.write_text("My own character", encoding="utf-8")
    response = client.post("/api/config", headers=HEADERS, json={"character": "custom", "name": "Mira"})
    assert response.status_code == 200
    assert persona.read_text(encoding="utf-8") == "My own character"
    assert workspace.config()["ADMIN_IDS"] == "qq:7"
    assert not (workspace.home / "persona.txt.bak").exists()


def test_a_chosen_personality_keeps_a_copy_of_the_persona_someone_wrote(client, workspace):
    sw.write_env(workspace.env, {"LLM_API_KEY": "old-key", "LLM_BASE_URL": "https://api.deepseek.com",
                                 "PERSONA_NAME": "Mira"})
    persona = workspace.home / "persona.txt"
    persona.write_text("My own character", encoding="utf-8")
    kept = workspace.home / "persona.txt.bak"
    # An emptied name box keeps the name rather than making a new character.
    response = client.post("/api/config", headers=HEADERS, json={"character": "template", "name": ""})
    assert response.status_code == 200 and workspace.config()["PERSONA_NAME"] == "Mira"
    assert kept.read_text(encoding="utf-8") == "My own character"
    assert persona.read_text(encoding="utf-8") != "My own character"
    # A shipped persona is not worth a copy: the one someone wrote stays in the .bak.
    client.post("/api/config", headers=HEADERS, json={"character": "mibo", "name": "Mira"})
    assert kept.read_text(encoding="utf-8") == "My own character"
    # A second persona someone wrote takes the .bak; the first keeps its dated copy.
    persona.write_text("My second character", encoding="utf-8")
    client.post("/api/config", headers=HEADERS, json={"character": "template", "name": "Mira"})
    assert kept.read_text(encoding="utf-8") == "My second character"
    copies = sorted(p.read_text(encoding="utf-8") for p in workspace.home.glob("persona.txt.*.bak"))
    assert copies == ["My own character", "My second character"]


@pytest.mark.parametrize("key", ["密钥 sk-abc", "sk-abc def"])
def test_a_key_pasted_with_other_words_is_turned_down_as_a_key(client, workspace, key):
    response = client.post("/api/config", headers=HEADERS, json={"apiKey": key})
    # Its own message: not a key the service refused, but text around the key.
    assert response.status_code == 400 and response.json()["error"] == "key_malformed"
    assert not workspace.config().get("LLM_API_KEY")


def test_a_blank_name_is_asked_for_by_name(client, workspace):
    response = client.post("/api/config", headers=HEADERS, json={"apiKey": "k", "name": "   "})
    assert response.status_code == 400 and response.json()["error"] == "name_required"
    assert not workspace.config().get("LLM_API_KEY")


FAN_MADE = ("chatgpt", "deepseek", "claude")
SPRITE = b"RIFF\x04\x00\x00\x00WEBP"


@pytest.fixture
def portraits(monkeypatch, tmp_path_factory):
    """Portrait sprites for the fan-made characters, never the package's own folder."""
    folder = tmp_path_factory.mktemp("portraits")
    for key in FAN_MADE:
        (folder / f"{key}.webp").write_bytes(SPRITE)
    monkeypatch.setattr(sw, "PORTRAITS", folder)
    return folder


def test_the_catalog_names_each_character_and_its_portrait(client, portraits):
    (portraits / "deepseek.webp").unlink()
    characters = {c["id"]: c for c in client.get("/api/catalog", headers=HEADERS).json()["characters"]}
    assert list(characters) == list(sw.PERSONA_KEYS)
    assert characters["claude"]["defaultNames"]["en"] == "Milady"
    assert characters["claude"]["defaultNames"]["zh"] == "大小姐"
    assert set(characters["claude"]["ownNames"]) >= {"Claude", "Milady", "大小姐", "お嬢様", "아가씨"}
    assert characters["claude"]["avatar"] == "/assets/characters/claude.webp"
    assert characters["deepseek"]["defaultNames"]["ja"] == "おさかな" and characters["deepseek"]["avatar"] is None
    assert "ChatGPT" in characters["chatgpt"]["ownNames"]
    assert characters["template"]["defaultNames"] is None and characters["template"]["avatar"] is None
    assert characters["template"]["ownNames"] == []


def test_portraits_are_served_for_characters_and_nothing_else(client, portraits):
    response = client.get("/assets/characters/claude.webp")
    assert response.status_code == 200 and response.content == SPRITE
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "max-age=86400"
    (portraits / "stray.webp").write_bytes(SPRITE)
    (portraits / "deepseek.webp").unlink()
    for name in ("deepseek.webp", "template.webp", "stray.webp", "claude", "claude.png",
                 "claude.webp.bak", "..%2Fwelcome%2Fapp.js", "..%2F..%2Fwelcome.py", "%2E%2E.webp"):
        assert client.get(f"/assets/characters/{name}").status_code == 404, name


def test_choosing_a_character_sets_its_portrait_and_editing_keeps_it(client, workspace, portraits,
                                                                    monkeypatch):
    url = "/api/config"
    state = client.post(url, headers=HEADERS, json={"apiKey": "k", "character": "claude", "lang": "en"}).json()
    assert workspace.config()["PERSONA_AVATAR"] == "claude"
    assert (state["avatar"], state["character"], state["name"]) == ("claude", "claude", "Milady")
    (workspace.home / "persona.txt").write_text("Your name is Claude. Tea only.\n", encoding="utf-8")
    state = client.get("/api/state", headers=HEADERS).json()
    assert (state["avatar"], state["character"]) == ("claude", "custom")
    state = client.post(url, headers=HEADERS, json={"apiKey": "k", "character": "custom", "name": "Claude"}).json()
    assert workspace.config()["PERSONA_AVATAR"] == "claude" and state["avatar"] == "claude"
    state = client.post(url, headers=HEADERS, json={"apiKey": "k", "character": "template", "name": "Mira"}).json()
    assert workspace.config()["PERSONA_AVATAR"] == "" and state["avatar"] == ""
    state = client.post(url, headers=HEADERS, json={"apiKey": "k", "character": "deepseek", "name": "Mira"}).json()
    assert (state["avatar"], state["name"]) == ("deepseek", "Mira")


def test_a_written_character_takes_a_portrait_without_losing_its_persona(client, workspace, portraits,
                                                                       monkeypatch):
    client.post("/api/config", headers=HEADERS, json={"apiKey": "k", "character": "claude", "lang": "en"})
    (workspace.home / "persona.txt").write_text("My own words.\n", encoding="utf-8")
    state = client.post("/api/config", headers=HEADERS,
                        json={"apiKey": "k", "character": "custom", "name": "Mira", "avatar": "deepseek"}).json()
    assert (state["avatar"], state["character"]) == ("deepseek", "custom")
    assert (workspace.home / "persona.txt").read_text(encoding="utf-8") == "My own words.\n"
    state = client.post("/api/config", headers=HEADERS,
                        json={"apiKey": "k", "character": "custom", "name": "Mira", "avatar": ""}).json()
    assert state["avatar"] == ""
    for bad in ("../claude", "template", "own"):
        response = client.post("/api/config", headers=HEADERS,
                               json={"apiKey": "k", "character": "custom", "name": "Mira", "avatar": bad})
        assert response.json()["error"] == "invalid_character", bad


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 32


def test_a_picture_of_ones_own_is_kept_checked_served_and_removed(client, workspace, portraits,
                                                                  monkeypatch):
    client.post("/api/config", headers=HEADERS, json={"apiKey": "k", "character": "claude", "lang": "en"})
    assert client.get("/api/avatar", headers=HEADERS).status_code == 404
    assert client.post("/api/avatar", content=PNG).status_code == 403
    state = client.post("/api/avatar", headers=HEADERS, content=PNG).json()
    assert state["avatar"] == "own" and state["ownAvatar"]
    assert workspace.config()["PERSONA_AVATAR"] == "own"
    response = client.get("/api/avatar", headers=HEADERS)
    assert response.content == PNG and response.headers["content-type"] == "image/png"
    assert client.get("/api/avatar").status_code == 403
    # A JPEG replaces it: one file, never two.
    client.post("/api/avatar", headers=HEADERS, content=JPEG)
    assert sorted(p.name for p in workspace.home.glob("avatar.*")) == ["avatar.jpg"]
    assert client.get("/api/avatar", headers=HEADERS).headers["content-type"] == "image/jpeg"
    for data, error in ((b"just text, named .png", "avatar_type"), (b"GIF89a" + b"\0" * 8, "avatar_type"),
                        (PNG + b"\0" * sw.MAX_OWN_AVATAR, "avatar_too_large")):
        response = client.post("/api/avatar", headers=HEADERS, content=data)
        assert response.status_code == 400 and response.json()["error"] == error
    assert sorted(p.name for p in workspace.home.glob("avatar.*")) == ["avatar.jpg"]
    state = client.post("/api/config", headers=HEADERS,
                        json={"apiKey": "k", "character": "claude", "name": "Milady", "avatar": "own"}).json()
    assert state["avatar"] == "own"
    state = client.post("/api/avatar/remove", headers=HEADERS, json={}).json()
    assert state["avatar"] == "claude" and state["ownAvatar"] == ""
    assert not list(workspace.home.glob("avatar.*"))
    assert client.get("/api/avatar", headers=HEADERS).status_code == 404
    # A setting left pointing at a deleted picture shows the portrait instead.
    sw.write_env(workspace.env, {"PERSONA_AVATAR": "own"})
    assert workspace.summary()["avatar"] == "claude"


def test_state_shows_the_portrait_of_an_unedited_shipped_character(workspace, portraits):
    sw.write_env(workspace.env, {"LLM_API_KEY": "k", "AGENT_LANG": "en"})
    assert workspace.summary()["avatar"] == ""
    sw.write_persona(workspace.home, "chatgpt", name="ChatGPT", lang="en")
    assert workspace.summary()["avatar"] == "chatgpt"
    sw.write_env(workspace.env, {"PERSONA_AVATAR": "claude"})
    assert workspace.summary()["avatar"] == "claude"
    sw.write_env(workspace.env, {"PERSONA_AVATAR": "../claude"})
    assert workspace.summary()["avatar"] == "chatgpt"
    (portraits / "chatgpt.webp").unlink()
    assert workspace.summary()["avatar"] == ""
    sw.write_env(workspace.env, {"PERSONA_AVATAR": ""})
    sw.write_persona(workspace.home, "template", name="Mira", lang="en")
    assert workspace.summary()["avatar"] == ""


def test_unknown_provider_or_insecure_remote_url_is_rejected(client):
    for fields in ({"provider": "unknown"}, {"baseUrl": "http://remote.example/v1"},
                   {"baseUrl": "https://user:password@remote.example/v1"}):
        response = client.post("/api/config", headers=HEADERS, json={"apiKey": "test", **fields})
        assert response.status_code == 400


def test_changing_the_api_endpoint_never_sends_the_saved_key(client, workspace, monkeypatch):
    sw.write_env(workspace.env, {"LLM_API_KEY": "old-key", "LLM_BASE_URL": "https://api.deepseek.com"})
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: pytest.fail("must not send a saved key to a new endpoint"))
    response = client.post("/api/config", headers=HEADERS, json={"baseUrl": "https://new.example/v1"})
    # Said as such: the saved key stays with the address it was saved for.
    assert response.status_code == 400 and response.json()["error"] == "key_again"


def test_large_and_malformed_posts_are_rejected(client):
    assert client.post("/api/config", headers=HEADERS, content="x" * (welcome.MAX_BODY + 1)).status_code == 413
    assert client.post("/api/config", headers=HEADERS, content="[]").status_code == 400
    assert client.post("/api/config", headers=HEADERS, content="{").status_code == 400


def test_chat_asks_the_character_and_is_kept(workspace, monkeypatch):
    sw.write_env(workspace.env, {"LLM_API_KEY": "key"})
    asked = []

    async def reply(conversation, parts, *, choices=(), run=None):
        asked.append((conversation, parts))
        return [{"type": "text", "text": "hello"}]

    monkeypatch.setattr(workspace.character, "reply", reply)
    import asyncio
    answer = asyncio.run(workspace.chat("hello"))
    assert answer["reply"] == "hello"
    assert [(m["role"], m["text"]) for m in answer["messages"]] == [("user", "hello"), ("assistant", "hello")]
    # The character is given the chat by the page's own name for it, and the words as typed.
    assert asked == [(workspace._main.conversation, [{"type": "text", "text": "hello"}])]
    # Each message carries when it was said, for the page's day lines and times.
    last = dict(workspace.history()["messages"][-1])
    assert isinstance(last.pop("at"), str) and last == {"role": "assistant", "text": "hello", "seq": 2}
    restored = welcome.Workspace(workspace.home)
    try:
        assert restored._main.conversation == workspace._main.conversation
        assert restored.history() == workspace.history()
        restored.reset_chat()
        assert restored.history()["messages"] == []
        assert restored.history()["chat"] != workspace.history()["chat"]
        assert restored._main.conversation != workspace._main.conversation
    finally:
        restored.close()


def test_a_memory_answer_is_marked_and_a_forget_marks_the_words_on_the_page(workspace, monkeypatch):
    sw.write_env(workspace.env, {"LLM_API_KEY": "key", "PERSONA_NAME": "Mira", "AGENT_LANG": "en"})
    answers = {"my sister lives in Denver. The weather is fine": ["nice city"],
               "Mira, what do you remember": ["Here's what I remember:", "About you: your sister lives in Denver"],
               "Mira, forget Denver": ["forgotten: your sister lives in Denver"],
               "Mira, forget Paris": ["nothing matching to forget"]}
    scrub = {"words": ["Denver"], "texts": [], "lines": [], "mark": "en"}

    async def reply(conversation, parts, *, choices=(), run=None):
        said = parts[-1]["text"]
        return [{"type": "text", "text": t, **({"scrub": scrub} if said == "Mira, forget Denver" else {})}
                for t in answers[said]]

    monkeypatch.setattr(workspace.character, "reply", reply)
    import asyncio
    assert "command" not in asyncio.run(workspace.chat("my sister lives in Denver. The weather is fine"))["messages"][-1]
    recall = asyncio.run(workspace.chat("Mira, what do you remember"))
    said = [m for m in recall["messages"] if m["role"] == "assistant"]
    assert [m.get("command") for m in said] == ["recall", "recall"]
    # The way to Settings › Memory goes under the answer's last line only.
    assert [bool(m.get("manage")) for m in said] == [False, True]
    # Nothing was forgotten: nothing changes on the page.
    kept = asyncio.run(workspace.chat("Mira, forget Paris"))
    assert "forgotLines" not in kept
    gone = asyncio.run(workspace.chat("Mira, forget Denver"))
    texts = [m["text"] for m in workspace.history()["messages"]]
    # Only the sentences holding the words become the mark; the command and its answer stay.
    assert texts == ["(forgotten) The weather is fine", "nice city", "Mira, what do you remember",
                     "Here's what I remember:", "(forgotten)", "Mira, forget Paris",
                     "nothing matching to forget", "Mira, forget Denver", "forgotten: your sister lives in Denver"]
    assert gone["forgotLines"] == 2 and gone["messages"] == workspace.history()["messages"]
    assert "Denver" not in (workspace.home / "runtime" / "desktop" / "browser-chat.json").read_text(
        encoding="utf-8").replace("forget Denver", "").replace("your sister lives in Denver", "")


def test_the_state_says_when_the_character_cannot_reach_its_model(client, workspace, monkeypatch):
    assert client.get("/api/state", headers=HEADERS).json()["modelUnreachable"] is False
    workspace.character.agent.__dict__["model_unreachable"] = True
    assert client.get("/api/state", headers=HEADERS).json()["modelUnreachable"] is True


def test_the_state_carries_the_admins_name(client, workspace):
    sw.write_env(workspace.env, {"ADMIN_NAME": "Kai"})
    assert client.get("/api/state", headers=HEADERS).json()["adminName"] == "Kai"
