"""Settings › Connections' signed-in sites (panels/signins.py, web/signin.py): every signed-in site follows the general
switches unless it has a choice of its own (background browsing and automatic sign-in reach only the content
platforms the app knows), a site signed in for the first time takes them with one line and no
panel, and the one list shows each site signed in or signed out with a saved password, with the cookies of the
rest counted below it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from harness.app import TOKEN

from mibo import setup_wizard as sw
from mibo import signedread, signwatch, welcome
from mibo.web import signin, sites

HEADERS = {welcome.TOKEN_HEADER: TOKEN}
NEWS = "https://news.example/"
SHOP = "https://shop.example/"
# A content platform the app knows, which background browsing and automatic sign-in reach from the general
# switches.
PLATFORM = "https://medium.com/"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("http://127.0.0.1", 200, ""))
    value = welcome.Workspace(tmp_path / "home")
    yield value
    value.close()


@pytest.fixture
def client(workspace, monkeypatch):
    """The app with a window whose page is the app's own and a profile holding the cookies of `held`."""
    held = {"news.example": {"sid"}, "cookies.example": {"sid"}}
    monkeypatch.setattr(signwatch, "Profile", lambda pane: SimpleNamespace(names=lambda: held))
    app = welcome.create_app(workspace.home, TOKEN, workspace=workspace)
    app.state.window = SimpleNamespace(pane=SimpleNamespace(), is_own_page=lambda key: True)
    return TestClient(app, base_url="http://127.0.0.1")


def _desktop(workspace):
    return workspace.home / "runtime" / "desktop"


def _row(client, site: str) -> dict:
    return next(row for row in client.get("/api/signins", headers=HEADERS).json()["sites"] if row["site"] == site)


def test_a_home_with_no_general_switches_keeps_what_every_site_did(workspace):
    desktop = _desktop(workspace)
    signin.became(desktop, NEWS, "signin")
    assert signin.general(desktop) == {"here": True, "task": True, "background": False, "auto": False}
    assert signin.chose(desktop, NEWS, "here") and signin.chose(desktop, NEWS, "task")
    assert signin.auto(desktop, NEWS) == "" and not signin.background(desktop, NEWS)
    assert signin.kept_out(desktop, NEWS) and signedread.feeds_on(workspace.home / "runtime") == {}


def test_a_site_signed_in_for_the_first_time_takes_the_general_switches(client, workspace):
    desktop = _desktop(workspace)
    for name in ("background", "auto"):
        client.post("/api/signins/general", headers=HEADERS, json={"name": name, "on": True})
    client.post("/api/signins/general", headers=HEADERS, json={"name": "task", "on": False})
    signin.became(desktop, PLATFORM, "signin")
    row = _row(client, "medium.com")
    assert row["fresh"] and row["own"] == []
    assert (row["here"], row["task"], row["background"], row["auto"]) == (True, False, True, "always")
    assert signin.connected(desktop) == [] and not signin.kept_out(desktop, PLATFORM)
    assert signedread.feeds_on(workspace.home / "runtime")["medium.com"]["url"] == PLATFORM
    # The page tells it once: no panel waits on it.
    client.post("/api/signins", headers=HEADERS, json={"op": "seen", "site": "medium.com"})
    assert not _row(client, "medium.com")["fresh"]


def test_a_sites_own_choice_wins_over_the_general_switch_until_it_follows_again(client, workspace):
    desktop, runtime = _desktop(workspace), workspace.home / "runtime"
    signin.became(desktop, PLATFORM, "signin")
    client.post("/api/signins/general", headers=HEADERS, json={"name": "background", "on": True})
    for name in ("here", "background", "auto"):
        client.post("/api/signins", headers=HEADERS, json={"op": "choose", "site": "medium.com", "name": name,
                                                           "on": False})
    row = _row(client, "medium.com")
    assert row["own"] == ["here", "background", "auto"]
    assert (row["here"], row["background"], row["auto"]) == (False, False, "never")
    assert signedread.feeds_on(runtime) == {} and signin.kept_out(desktop, PLATFORM)
    # Back to the general switch, a wall's stop with it.
    sites._change(runtime, "medium.com", lambda card: card["feed"].update(stopped="verification"))
    for name in ("here", "background"):
        client.post("/api/signins", headers=HEADERS, json={"op": "follow", "site": "medium.com", "name": name})
    row = _row(client, "medium.com")
    assert row["own"] == ["auto"] and row["here"] and row["background"] and row["stopped"] == ""
    assert set(signedread.feeds_on(runtime)) == {"medium.com"}
    # Turning the general switch off leaves a site's own on as it is.
    client.post("/api/signins", headers=HEADERS, json={"op": "choose", "site": "medium.com", "name": "task",
                                                       "on": True})
    client.post("/api/signins/general", headers=HEADERS, json={"name": "task", "on": False})
    assert signin.chose(desktop, PLATFORM, "task")


def test_one_list_shows_signed_in_sites_and_saved_passwords_and_counts_the_other_cookies(client, workspace):
    desktop = _desktop(workspace)
    signin.became(desktop, NEWS, "signin")
    signin.change(desktop, "news.example", lambda entry: entry.update(saved=True))
    signin.change(desktop, "shop.example", lambda entry: entry.update(saved=True, home=SHOP))
    signin.change(desktop, "gone.example", lambda entry: entry.update(state="out", home="https://gone.example/"))
    listing = client.get("/api/signins", headers=HEADERS).json()
    assert "kept" not in listing
    assert [(row["site"], row["state"], row["saved"]) for row in listing["sites"]] == [
        ("news.example", "in", True), ("shop.example", "out", True)]
    # Cookies of a site not listed are counted under the list.
    assert listing["others"] == 1
    # A site listed signed out is still the person's to choose for and to sign in to.
    assert _row(client, "shop.example")["here"]
