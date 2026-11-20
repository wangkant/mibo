"""The page's chat: pictures the character sends, and messages it sends later."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os

from fastapi.testclient import TestClient
import pytest

from mibo import setup_wizard as sw
from mibo import welcome

TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}
# The smallest PNG: one transparent pixel.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@pytest.fixture
def workspace(tmp_path):
    value = welcome.Workspace(tmp_path)
    sw.write_env(value.env, {"LLM_API_KEY": "key"})
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    with TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace),
                    base_url="http://127.0.0.1") as value:
        yield value


def _replying(monkeypatch, workspace, replies, events=None):
    """The character answers every message with `replies`; `events` takes what each turn was given."""
    async def reply(conversation, parts, *, choices=(), run=None):
        if events is not None:
            events.append({"conversation": conversation, "parts": parts, "choices": list(choices)})
        return [dict(item) for item in replies]

    monkeypatch.setattr(workspace.character, "reply", reply)


def test_a_picture_reply_is_kept_shown_and_served_only_to_the_page(client, workspace, monkeypatch):
    _replying(monkeypatch, workspace, [{"type": "text", "text": "look"},
                                       {"type": "image", "b64": base64.b64encode(PNG).decode()}])
    answer = client.post("/api/chat", headers=HEADERS, json={"text": "hi"}).json()
    picture = answer["messages"][-1]["picture"]
    assert [m.get("text") for m in answer["messages"][:2]] == ["hi", "look"]
    assert welcome.PICTURE_NAME.fullmatch(picture)
    served = client.get(f"/api/chat/picture/{picture}", headers=HEADERS)
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert client.get(f"/api/chat/picture/{picture}").status_code == 403
    # Still there for a page opened again.
    again = welcome.Workspace(workspace.home)
    try:
        assert again.history()["messages"][-1]["picture"] == picture
    finally:
        again.close()


def test_the_picture_route_reads_nothing_but_stored_pictures(client, workspace, tmp_path):
    (workspace.home / ".env").write_text("LLM_API_KEY=secret\n", encoding="utf-8")
    name = workspace._keep_picture(base64.b64encode(PNG).decode())
    for bad in ("..%2F..%2F.env", "..%5C..%5C.env", "%2Fetc%2Fpasswd", "C%3A%5CWindows%5Cwin.ini",
                ".env", name.upper(), name + ".png", name[:-4] + ".txt", "..", "%2E%2E"):
        response = client.get(f"/api/chat/picture/{bad}", headers=HEADERS)
        # A bare ".." is folded by the client into another route, which refuses a GET.
        assert response.status_code in (404, 405), bad
        assert b"secret" not in response.content
    assert workspace.picture("../../.env") is None and workspace.picture(str(workspace.env)) is None


def test_a_linked_picture_is_refused(client, workspace, tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    link = workspace._pictures / ("a" * 40 + ".png")
    workspace._pictures.mkdir(parents=True, exist_ok=True)
    workspace._append([{"role": "assistant", "picture": link.name}])
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test create a symbolic link")
    assert client.get(f"/api/chat/picture/{link.name}", headers=HEADERS).status_code == 404


def test_a_pictures_folder_that_leads_elsewhere_is_refused(client, workspace, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    name = "b" * 40 + ".png"
    (elsewhere / name).write_bytes(PNG)
    workspace._pictures.parent.mkdir(parents=True, exist_ok=True)
    workspace._append([{"role": "assistant", "picture": name}])
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(elsewhere), str(workspace._pictures))
        else:
            os.symlink(elsewhere, workspace._pictures, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test link a folder")
    assert client.get(f"/api/chat/picture/{name}", headers=HEADERS).status_code == 404
    # Nor is anything stored there or removed from there.
    assert workspace._keep_picture(base64.b64encode(PNG).decode()) == ""
    workspace.reset_chat()
    assert (elsewhere / name).is_file()


def test_a_picture_no_message_shows_is_not_served(client, workspace):
    name = workspace._keep_picture(base64.b64encode(PNG).decode())
    assert (workspace._pictures / name).is_file()
    assert client.get(f"/api/chat/picture/{name}", headers=HEADERS).status_code == 404
    workspace._append([{"role": "assistant", "picture": name}])
    assert client.get(f"/api/chat/picture/{name}", headers=HEADERS).status_code == 200


def test_a_link_in_the_pictures_folder_is_never_written_through(workspace, tmp_path):
    outside = tmp_path / "outside.png"
    workspace._pictures.mkdir(parents=True, exist_ok=True)
    link = workspace._pictures / f"{hashlib.sha256(PNG).hexdigest()[:40]}.png"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test create a symbolic link")
    assert workspace._keep_picture(base64.b64encode(PNG).decode()) == ""
    assert not outside.exists()


def test_a_removed_picture_is_missing_and_what_is_not_a_picture_is_not_kept(client, workspace):
    name = workspace._keep_picture(base64.b64encode(PNG).decode())
    workspace._append([{"role": "assistant", "picture": name}])
    (workspace._pictures / name).unlink()
    assert client.get(f"/api/chat/picture/{name}", headers=HEADERS).status_code == 404
    assert workspace._keep_picture(base64.b64encode(b"<svg onload=x>").decode()) == ""
    assert workspace._keep_picture("not base64!") == ""


def test_pictures_leave_with_the_messages_that_showed_them(monkeypatch, workspace):
    _replying(monkeypatch, workspace, [{"type": "image", "b64": base64.b64encode(PNG).decode()}])
    asyncio.run(workspace.chat("hi"))
    assert list(workspace._pictures.iterdir())
    workspace.reset_chat()
    assert not list(workspace._pictures.iterdir())


def test_a_failed_message_is_kept_unanswered_and_can_be_sent_again(monkeypatch, workspace, tmp_path):
    async def down(conversation, parts, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(workspace.character, "reply", down)
    with pytest.raises(ConnectionError):
        asyncio.run(workspace.chat("hi"))
    expected = [{"role": "user", "text": "hi", "seq": 1, "failed": "chat_failed"}]

    def kept(ws):
        # Each message also carries when it was sent.
        return [{k: v for k, v in m.items() if k != "at"} for m in ws.history()["messages"]]

    assert kept(workspace) == expected
    again = welcome.Workspace(workspace.home)
    try:
        assert kept(again) == expected, "a restart keeps it"
    finally:
        again.close()
    # The character never had that turn.
    from mibo import dm
    assert dm._page_turns(workspace._history_path, workspace._main.conversation) == []
    _replying(monkeypatch, workspace, [{"type": "text", "text": "here"}])
    answer = asyncio.run(workspace.chat("hi", retry=1))
    assert [(m["text"], m.get("failed")) for m in workspace.history()["messages"]] == [
        ("hi", None), ("here", None)]
    assert [m["text"] for m in answer["messages"]] == ["hi", "here"]


def test_a_character_that_does_not_start_keeps_the_message(monkeypatch, workspace):
    async def broken(conversation, parts, **kwargs):
        raise welcome.NotReady("the memory file is damaged")

    monkeypatch.setattr(workspace.character, "reply", broken)
    with pytest.raises(welcome.NotReady):
        asyncio.run(workspace.chat("hello"))
    assert workspace.history()["messages"][-1]["failed"] == "agent_failed"


def test_the_kept_chat_starts_at_a_turn_and_says_it_was_cut(monkeypatch, workspace):
    replies = [{"type": "text", "text": "one"}, {"type": "text", "text": "two"},
               {"type": "text", "text": "three"}]
    _replying(monkeypatch, workspace, replies)
    for n in range(13):
        asyncio.run(workspace.chat(f"m{n}"))
    seen = workspace.history()
    assert seen["trimmed"] is True
    assert seen["messages"][0]["role"] == "user", "never the tail of a reply"
    assert len(seen["messages"]) <= welcome.CHAT_KEPT
    again = welcome.Workspace(workspace.home)
    try:
        assert again.history()["trimmed"] is True and again.history()["messages"] == seen["messages"]
    finally:
        again.close()
    workspace.reset_chat()
    assert workspace.history()["trimmed"] is False


def test_history_since_a_number(client, workspace):
    workspace._history_path.parent.mkdir(parents=True, exist_ok=True)
    workspace._history_path.write_text(
        '{"conversation": "c1", "seq": 2, "messages": [{"role": "user", "text": "a", "seq": 1}, '
        '{"role": "assistant", "text": "b", "seq": 2}]}', encoding="utf-8")
    kept = welcome.Workspace(workspace.home)
    try:
        assert kept.history(1)["messages"] == [{"role": "assistant", "text": "b", "seq": 2}]
    finally:
        kept.close()
    assert client.get("/api/chat/history?after=0", headers=HEADERS).json()["messages"] == []
    assert client.get("/api/chat/history?after=x", headers=HEADERS).status_code == 422
    assert workspace.history()["kept"] == welcome.CHAT_KEPT


def test_a_reply_that_cannot_be_shown_leaves_no_empty_picture(monkeypatch, workspace):
    _replying(monkeypatch, workspace, [{"type": "text", "text": "here"}, {"type": "image", "b64": "x"}])
    asyncio.run(workspace.chat("hi"))
    assert [m.get("text") for m in workspace.history()["messages"]] == ["hi", "here"]


def _page_agent(tmp_path):
    from helpers import isolated_agent

    return isolated_agent(tmp_path / "agent")


def _through(monkeypatch, workspace, agent):
    """The page's character is `agent`."""
    async def ready():
        return agent

    monkeypatch.setattr(workspace.character, "_ready", ready)


def test_a_model_failure_is_reported_in_the_page_and_never_stored(monkeypatch, workspace, tmp_path):
    """Every failure, not once per cooldown, and the casual excuse never becomes a message."""
    fail = [True]
    agent = _page_agent(tmp_path)

    async def chat_dm(history, pkey="", **kwargs):
        if fail[0]:
            raise TimeoutError("model down")
        return "hi back", ""

    agent._chat_dm = chat_dm
    _through(monkeypatch, workspace, agent)
    monkeypatch.setattr(workspace.character, "_build", lambda: None)
    with TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace),
                    base_url="http://127.0.0.1") as client:
        for _ in range(2):
            answer = client.post("/api/chat", headers=HEADERS, json={"text": "hi"})
            assert answer.status_code == 502 and answer.json() == {"error": "chat_failed"}
            assert workspace.history()["messages"][-1]["failed"] == "chat_failed"
        fail[0] = False
        answer = client.post("/api/chat", headers=HEADERS, json={"text": "hi"}).json()
    assert answer["reply"] == "hi back"
    # The excuse never becomes a message; the unanswered ones stay marked.
    assert [(m["text"], m.get("failed")) for m in workspace.history()["messages"]] == [
        ("hi", "chat_failed"), ("hi", "chat_failed"), ("hi", None), ("hi back", None)]
