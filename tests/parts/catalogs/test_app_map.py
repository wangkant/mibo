"""The character's map of its own app (mibo/appmap.py): one catalogue that follows the Settings pages, a look-up that
never shows a key, a change made when the person asks, a change that widens the character's permissions asked in the
chat after outside material, and the one notice of where page text, window pictures and file text go."""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from harness.app import TOKEN
from mibo import appmap, cardwait, crossing, i18n, secretstore, welcome
from mibo import setup_wizard as sw
from mibo.see import when

HEADERS = {welcome.TOKEN_HEADER: TOKEN}
SETUP = welcome.ASSETS / "setup"
SECRET = "sk-app-map-secret-0123456789"
MARK = re.compile(r"""(?:kit\.item|kit\.switchRow)\(\s*"([\w-]+)\"""")
# The two colour rows are marked through colorRow(part), one per name in this loop.
COLOURS = re.compile(r"for \(const part of \[([^\]]*)\]\) rows\[part\] = colorRow\(part\)")


def _pages() -> dict[str, set[str]]:
    """Each Settings page and the items it marks, as the page scripts write them."""
    shell = (welcome.ASSETS / "setup.js").read_text(encoding="utf-8")
    order = json.loads(re.search(r"const ORDER = (\[[^\]]*\]);", shell).group(1))
    aliases = {"skills": "abilities", "tools": "abilities"}
    pages: dict[str, set[str]] = {page: set() for page in order}
    for path in SETUP.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r'part\("(\w+)"', text):
            page = aliases.get(name, name)
            if page == "abilities":
                continue
            pages[page] |= set(MARK.findall(text))
            for listed in COLOURS.findall(text):
                pages[page] |= set(re.findall(r'"([\w-]+)"', listed))
    # Skills and connectors are the abilities page's two tabs (setup.js).
    pages["abilities"] = set(re.findall(r'\["(\w+)", t\.names\.\1\]', shell))
    return pages


def test_the_catalogue_covers_every_settings_page_and_every_item_each_marks():
    pages = _pages()
    assert list(pages) == list(appmap.PAGES)
    for page, marks in pages.items():
        listed = {item.key for item in appmap.ITEMS if item.page == page}
        assert listed, page
        assert marks == listed - {""}, page
    for item in appmap.ITEMS:
        for lang in ("zh", "en"):
            assert i18n.t(item.label, lang, count=0) != item.label, (item.id, lang)
        assert appmap.where(item, "zh").startswith(i18n.t("setup.title", "zh"))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("http://127.0.0.1", 200, ""))
    value = welcome.Workspace(tmp_path / "home")
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    # No lifespan: the routes read and write the home's own files.
    return TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace), base_url="http://127.0.0.1")


@pytest.fixture
def asked(monkeypatch):
    """The questions said in the chat, each answered no."""
    seen = []

    async def ask(self, card, conversation, what, ended=None, *, yes=True, no=False, risk="act", typed=True):
        seen.append({"card": card, "risk": risk})
        return no

    monkeypatch.setattr(cardwait.Card, "ask", ask)
    return seen


def _settings(client, **payload) -> dict:
    return client.post("/api/settings", headers=HEADERS, json={"conversation": "main", **payload}).json()


def test_a_look_up_names_whether_a_key_is_set_and_never_the_key(client, workspace):
    client.post("/api/config", headers=HEADERS,
                json={"provider": "other", "baseUrl": "https://models.example/v1", "apiKey": SECRET, "model": "m"})
    assert secretstore.get(workspace.home, "LLM_API_KEY") == SECRET
    listed = _settings(client, do="list", item="")
    assert listed["status"] == "ok" and SECRET not in json.dumps(listed)
    assert [row["id"] for row in listed["items"]] == [item.id for item in appmap.ITEMS]
    service = next(row for row in listed["items"] if row["id"] == "model/service")
    assert service["now"] == "models.example · m · a key is set" and service["change"] == "no"
    # Only the person chooses the service; the character opens Settings there.
    assert _settings(client, do="change", item="model/service", value="https://other.example")["status"] == "theirs"


def test_a_change_that_widens_nothing_is_made_when_asked(client, asked):
    was = client.get("/api/quiet/settings", headers=HEADERS).json()["on"]
    done = _settings(client, do="change", item="privacy/quiet", value="off" if was else "on")
    assert done["status"] == "changed" and asked == []
    assert client.get("/api/quiet/settings", headers=HEADERS).json()["on"] is not was
    assert _settings(client, do="change", item="privacy/quiet", value="off" if was else "on")["status"] == "same"
    assert _settings(client, do="change", item="device/links", value="sideways")["status"] == "invalid"


def test_a_widening_change_after_outside_material_is_asked_in_the_chat(client, workspace, asked):
    place = workspace.home / "runtime" / "desktop"
    place.mkdir(parents=True, exist_ok=True)
    (place / "chat-doing.json").write_text(json.dumps({
        "conversation": "main", "turn": "t1", "read": {"outside": ["https://pages.example/post"], "local": []}}),
        encoding="utf-8")
    # The person turned it off in Settings.
    assert client.post("/api/remarks/settings", headers=HEADERS, json={"on": False}).json()["on"] is False
    done = _settings(client, do="change", item="privacy/remarks", value="on")
    assert done["status"] == "declined"
    ((question,),) = [asked]
    assert question["risk"] == "widen" and question["card"]["type"] == "setting"
    assert i18n.t("setup_privacy.remarksTitle", "zh", count=0) in question["card"]["zh"]["title"]
    assert client.get("/api/remarks/settings", headers=HEADERS).json()["on"] is False
    # After outside material even the person's own words naming it ask; without it, their words are the yes.
    names = [i18n.t("setup_privacy.remarksTitle", "zh", count=0)]
    assert crossing.widening({"names": names}, [f"打开{names[0]}"], {"outside": ["https://pages.example/post"]})
    assert not crossing.widening({"names": names}, [f"打开{names[0]}"], {})


def test_the_model_notice_shows_once_and_again_on_a_changed_host(client, workspace):
    desktop = workspace.home / "runtime" / "desktop"

    def save(base: str) -> None:
        client.post("/api/config", headers=HEADERS,
                    json={"provider": "other", "baseUrl": base, "apiKey": "k", "model": "m"})

    assert client.get("/api/model/notice", headers=HEADERS).json() == {"host": ""}
    save("https://one.example/v1")
    assert client.get("/api/model/notice", headers=HEADERS).json() == {"host": "one.example"}
    save("https://one.example/v2")
    assert when.told(desktop) == "one.example"
    save("https://two.example/v1")
    assert client.get("/api/model/notice", headers=HEADERS).json() == {"host": "two.example"}


def test_the_pictures_switch_is_on_until_turned_off_and_a_host_change_keeps_it(tmp_path):
    switch = when.Switch(tmp_path)
    assert switch.on()
    when.tell(tmp_path, "one.example")
    switch.set(False)
    assert not switch.on() and when.told(tmp_path) == "one.example"
    when.tell(tmp_path, "two.example")
    assert not switch.on()
    switch.set(True)
    assert switch.on()
    # A file from before the notice kept "always": "" for off.
    (tmp_path / when.SWITCH_FILE).write_text(json.dumps({"always": ""}), encoding="utf-8")
    assert not switch.on()
