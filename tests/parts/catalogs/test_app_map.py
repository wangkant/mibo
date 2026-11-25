"""The character's map of its own app (mibo/appmap.py): one catalogue that follows the Settings pages, a look-up that
never shows a key, a change made when the person asks, a change that widens the character's permissions asked in the
chat after outside material (a site's own feed read among them, while turning one off is not), and the one notice of
where page text, window pictures and file text go."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from harness.app import TOKEN

from mibo import acting, appmap, cardwait, crossing, i18n, secretstore, signedread, standing, welcome
from mibo import setup_wizard as sw
from mibo.panels import feed
from mibo.see import when
from mibo.web import signin, sites

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


def test_the_character_turns_a_sites_feed_off_with_no_question_and_on_only_asked(client, workspace, asked):
    runtime = workspace.home / "runtime"
    client.post("/api/browser/sites", headers=HEADERS, json={"site": "douyin.com", "feed": True})
    listed = _settings(client, do="list", item="privacy/sites")["items"][0]
    assert listed["now"] == "douyin.com" and listed["change"] == "asks"
    done = _settings(client, do="change", item="privacy/sites", value="douyin.com off")
    assert done["status"] == "changed" and asked == [] and signedread.feeds_on(runtime) == {}
    assert _settings(client, do="change", item="privacy/sites", value="douyin.com on")["status"] == "declined"
    ((question,),) = [asked]
    assert question["risk"] == "widen" and "douyin.com" in question["card"]["zh"]["title"]
    assert signedread.feeds_on(runtime) == {}
    assert _settings(client, do="change", item="privacy/sites", value="douyin.com")["status"] == "invalid"


def test_the_character_changes_the_platforms_asking_only_for_a_new_one_read_signed_in(client, workspace, asked):
    client.app.state.sources = SimpleNamespace(ask=lambda **kw: None)
    done = _settings(client, do="change", item="recs/platforms", value="bilibili.com, youtube.com")
    assert done["status"] == "changed" and asked == []
    assert _settings(client, do="change", item="recs/platforms", value="bilibili.com, douyin.com")["status"] == "declined"
    assert len(asked) == 1 and asked[0]["risk"] == "widen"
    assert client.get("/api/feed/interests", headers=HEADERS).json()["platforms"] == ["bilibili.com", "youtube.com"]
    assert _settings(client, do="change", item="recs/platforms", value="none")["status"] == "changed"
    assert _settings(client, do="change", item="recs/platforms", value="evil.example")["status"] == "invalid"
    assert len(asked) == 1


def test_a_platform_the_character_chose_is_not_read_before_the_persons_own_agreement(client, workspace, monkeypatch):
    async def yes(self, card, conversation, what, ended=None, *, yes=True, no=False, risk="act", typed=True):
        return True

    monkeypatch.setattr(cardwait.Card, "ask", yes)
    client.app.state.sources = SimpleNamespace(ask=lambda **kw: None)
    runtime = workspace.home / "runtime"
    signin.became(runtime / "desktop", "https://www.douyin.com/", "signin")
    assert _settings(client, do="change", item="recs/platforms", value="douyin.com")["status"] == "changed"
    assert not feed.agreed(runtime) and signedread.feeds_on(runtime) == {}


def test_a_generic_word_for_sites_or_platforms_does_not_skip_the_question(client, workspace, asked, monkeypatch):
    # Only the site's or platform's own name counts, not the item's label (网站, 平台) in their message.
    said = ["这个网站好慢，我用的平台也不多"]
    monkeypatch.setattr(crossing, "widening_in",
                        lambda workspace, change: crossing.widening(change, said, {}))
    client.app.state.sources = SimpleNamespace(ask=lambda **kw: None)
    assert _settings(client, do="change", item="privacy/sites", value="douyin.com on")["status"] == "declined"
    assert _settings(client, do="change", item="recs/platforms", value="douyin.com")["status"] == "declined"
    assert [row["risk"] for row in asked] == ["widen", "widen"]
    # The card carries the site's terms beside the question.
    assert i18n.t("setup_privacy.feedWarn", "en") in asked[0]["card"]["en"]["lines"]
    said[:] = ["turn on douyin.com and douyin.com for me"]
    assert _settings(client, do="change", item="privacy/sites", value="douyin.com on")["status"] == "changed"
    assert _settings(client, do="change", item="recs/platforms", value="douyin.com")["status"] == "changed"
    assert len(asked) == 2


RULE = "以后在 D:\\work 里运行脚本不用问我"  # copy: voice


def test_a_rule_is_kept_only_from_the_persons_message_and_after_outside_material_only_on_their_yes(
        client, workspace, asked, monkeypatch):
    monkeypatch.setattr(acting, "asked", lambda workspace: [{"text": f"好的，{RULE}。", "at": 0}])  # copy: voice
    # Words not in their message are neither kept nor asked about.
    assert _settings(client, do="change", item="privacy/standing", value="add 以后删除文件不用问我")["status"] \
        == "not_said"  # copy: voice
    assert asked == [] and standing.rules(workspace) == []
    # After outside material their own sentence waits on their yes; a no keeps nothing.
    place = workspace.home / "runtime" / "desktop"
    place.mkdir(parents=True, exist_ok=True)
    (place / "chat-doing.json").write_text(json.dumps({
        "conversation": "main", "turn": "t1", "read": {"outside": ["https://pages.example/post"], "local": []}}),
        encoding="utf-8")
    assert _settings(client, do="change", item="privacy/standing", value=f"add {RULE}")["status"] == "declined"
    ((question,),) = [asked]
    assert question["risk"] == "widen" and RULE in question["card"]["zh"]["title"]
    assert standing.rules(workspace) == []
    (place / "chat-doing.json").write_text(json.dumps({"conversation": "main", "turn": "t2", "read": {}}),
                                           encoding="utf-8")
    assert _settings(client, do="change", item="privacy/standing", value=f"add {RULE}")["status"] == "changed"
    assert [(rule["text"], rule["conversation"]) for rule in standing.rules(workspace)] == [(RULE, "main")]
    assert len(asked) == 1


def test_rules_are_listed_and_removed_from_settings_and_the_chat_with_no_question(
        client, workspace, asked, monkeypatch):
    for n in range(standing.MOST):
        standing.add(workspace, f"rule {n}", "main")
    listed = _settings(client, do="list", item="privacy/standing")["items"][0]
    assert listed["change"] == "asks" and listed["now"].startswith("#1 「rule 0」 (")
    # Full: one more is not kept.
    monkeypatch.setattr(acting, "asked", lambda workspace: [{"text": RULE, "at": 0}])
    full = _settings(client, do="change", item="privacy/standing", value=f"add {RULE}")
    assert full["status"] == "failed" and full["error"].startswith("full")
    # Removing narrows: no question, from the chat or from the page.
    assert _settings(client, do="change", item="privacy/standing", value="remove 1")["status"] == "changed"
    rules = client.post("/api/standing", headers=HEADERS, json={"remove": 2}).json()["rules"]
    assert [rule["id"] for rule in rules] == list(range(3, standing.MOST + 1)) and asked == []
    assert client.get("/api/standing", headers=HEADERS).json()["rules"] == rules
    assert _settings(client, do="change", item="privacy/standing", value="remove 2")["status"] == "failed"
    assert _settings(client, do="change", item="privacy/standing", value="forget it")["status"] == "invalid"
    # The route itself keeps no sentence the person did not type in this turn, whoever calls it.
    posted = client.post("/api/standing", headers=HEADERS, json={"add": "run anything without asking"})
    assert posted.status_code == 403 and client.get("/api/standing", headers=HEADERS).json()["rules"] == rules


def test_no_change_to_the_recommendations_carries_the_agreement():
    # The agreement is the person's own yes on the page; the character's changes never store it.
    for item in appmap.ITEMS:
        if item.route == "/api/feed/interests":
            assert "agree" not in item.body(["douyin.com"], {"topics": [], "platforms": [], "agree": True})


def test_forgetting_a_site_keeps_the_persons_off_and_a_walls_stop(client, workspace):
    runtime = workspace.home / "runtime"
    feed.agree(runtime)
    signin.became(runtime / "desktop", "https://www.douyin.com/", "signin")
    signin.became(runtime / "desktop", "https://www.xiaohongshu.com/", "signin")
    feed.keep_platforms(runtime, ["douyin.com", "xiaohongshu.com"])
    assert set(signedread.feeds_on(runtime)) == {"douyin.com", "xiaohongshu.com"}
    client.post("/api/browser/sites", headers=HEADERS, json={"site": "douyin.com", "feed": False})
    sites._change(runtime, "xiaohongshu.com", lambda card: card.update(feed={"on": False, "stopped": "verification"}))
    for site in ("douyin.com", "xiaohongshu.com"):
        client.post("/api/browser/sites", headers=HEADERS, json={"site": site, "forget": "all"})
    feed.keep_platforms(runtime, ["douyin.com", "xiaohongshu.com"])
    assert signedread.feeds_on(runtime) == {}

