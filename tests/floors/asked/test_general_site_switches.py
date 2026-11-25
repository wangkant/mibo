"""The general switches for signed-in sites (web/signin.py GENERAL) widen nothing on a guarded site: a bank's, a
payment service's, a mailbox's or an account site, by its key, its home or a mailbox's hint on its host, takes
neither background browsing of its feed nor automatic sign-in from them, and keeps the person's own choices for it.
Turning a general switch on comes only from the app's own page."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from harness.app import TOKEN

from mibo import acting, cardwait, signedread, welcome
from mibo import setup_wizard as sw
from mibo.web import signin

HEADERS = {welcome.TOKEN_HEADER: TOKEN}
BANK = "https://www.icbc.com.cn/"
MAIL = "https://mail.google.com/mail/u/0/"
VIDEO = "https://www.douyin.com/"


def test_a_guarded_site_takes_neither_background_browsing_nor_automatic_sign_in_from_a_general_switch(tmp_path):
    desktop = tmp_path / "runtime" / "desktop"
    for url in (BANK, MAIL, VIDEO):
        signin.became(desktop, url, "signin")
    for name in signin.GENERAL:
        signin.set_general(desktop, name, True)
    assert [signin.background(desktop, url) for url in (BANK, MAIL, VIDEO)] == [False, False, True]
    assert [signin.auto(desktop, url) for url in (BANK, MAIL, VIDEO)] == ["", "", "always"]
    assert set(signedread.feeds_on(tmp_path / "runtime")) == {"douyin.com"}
    # Reading while they browse it and during a task are as they were for every site; the person's own choice for
    # a guarded site holds as it did.
    assert all(signin.chose(desktop, url, "task") for url in (BANK, MAIL, VIDEO))
    signin.change(desktop, signin.key(BANK), lambda entry: entry.update(auto="always"))
    assert signin.auto(desktop, BANK) == "always"


def test_the_character_turns_general_background_browsing_or_automatic_sign_in_on_only_on_their_yes(
        tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("http://127.0.0.1", 200, ""))
    asked = []

    async def no(self, card, conversation, what, ended=None, *, yes=True, no=False, risk="act", typed=True):
        asked.append(risk)
        return False

    monkeypatch.setattr(cardwait.Card, "ask", no)
    said = []
    monkeypatch.setattr(acting, "asked", lambda workspace: [{"text": said[-1], "at": 0}])
    workspace = welcome.Workspace(tmp_path / "home")
    try:
        client = TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace), base_url="http://127.0.0.1")

        def change(item: str, value: str) -> str:
            return client.post("/api/settings", headers=HEADERS, json={
                "conversation": "main", "do": "change", "item": item, "value": value}).json()["status"]

        # A message that names the switch, even to forbid it, is no yes.
        for name, words in (("auto", "千万别给我开自动登录"), ("background", "后台浏览以推荐内容这个功能是干嘛的")):  # copy: voice
            said.append(words)
            assert change(f"connect/sites-{name}", "on") == "declined"
        assert asked == ["widen", "widen"] and signin.general(workspace.home / "runtime" / "desktop") == signin.GENERAL
        # The other switches still go on their words, and turning one off needs nothing.
        said.append("把任务中读取关掉，再打开")  # copy: voice
        assert change("connect/sites-task", "off") == change("connect/sites-task", "on") == "changed"
        assert len(asked) == 2
    finally:
        workspace.close()


def test_a_general_switch_is_turned_on_only_from_the_apps_own_page(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("http://127.0.0.1", 200, ""))
    workspace = welcome.Workspace(tmp_path / "home")
    try:
        app = welcome.create_app(workspace.home, TOKEN, workspace=workspace)
        app.state.window = SimpleNamespace(pane=None, is_own_page=lambda key: False)
        client = TestClient(app, base_url="http://127.0.0.1")
        for name in signin.GENERAL:
            refused = client.post("/api/signins/general", headers=HEADERS, json={"name": name, "on": True})
            assert refused.json()["error"] == "signin_window"
        assert signin.general(workspace.home / "runtime" / "desktop") == signin.GENERAL
        # Off narrows: it needs no more than this computer.
        taken = client.post("/api/signins/general", headers=HEADERS, json={"name": "here", "on": False}).json()
        assert taken["general"]["here"] is False
    finally:
        workspace.close()
