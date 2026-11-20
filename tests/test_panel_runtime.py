"""The runtime panel: running behind the window, the update notice and what the models used."""
from __future__ import annotations

import json
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mibo import updates, welcome
from mibo.panels import runtime

TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LANG", "en")
    workspace = welcome.Workspace(tmp_path)
    app = welcome.create_app(tmp_path, TOKEN, workspace=workspace)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield types.SimpleNamespace(app=app, client=client, home=tmp_path, workspace=workspace,
                                    desktop=tmp_path / "runtime" / "desktop")
    workspace.close()


def _found(home: Path, latest: str = "99.0.0") -> None:
    cache = home / "runtime" / "desktop" / "update.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"checked": time.time(), "latest": latest, "failed": False}), encoding="utf-8")


def test_the_panel_needs_the_capability(page) -> None:
    assert page.client.get("/api/runtime").status_code == 403
    for path in ("background", "check"):
        assert page.client.post(f"/api/runtime/{path}", json={}).status_code == 403, path


def test_background_can_be_chosen_only_where_a_window_can_hide(page) -> None:
    seen = page.client.get("/api/runtime", headers=HEADERS).json()
    assert seen["background"] is False and seen["canHide"] is False
    refused = page.client.post("/api/runtime/background", json={"on": True}, headers=HEADERS)
    assert (refused.status_code, refused.json()) == (400, {"error": "background_unavailable"})
    page.app.state.window = types.SimpleNamespace(can_hide=True)
    on = page.client.post("/api/runtime/background", json={"on": True}, headers=HEADERS).json()
    assert on["background"] is True and on["canHide"] is True
    assert welcome.app_settings(page.desktop) == {"background": True}
    off = page.client.post("/api/runtime/background", json={"on": False}, headers=HEADERS).json()
    assert off["background"] is False, "turning it off never needs the icon"


def test_checking_now_asks_and_shows_what_it_found(page, monkeypatch) -> None:
    asked = []

    def check(home, timeout):
        asked.append(timeout)
        _found(home)
        return "99.0.0"

    monkeypatch.setattr(updates, "check", check)
    seen = page.client.post("/api/runtime/check", json={}, headers=HEADERS).json()
    assert asked == [10.0]
    assert seen["update"]["version"] == "99.0.0"
    assert seen["update"]["url"].endswith("v99.0.0") and seen["checked"]


def test_a_check_that_did_not_reach_the_server_is_not_called_up_to_date(page) -> None:
    cache = page.desktop / "update.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"checked": time.time(), "latest": "", "failed": True}), encoding="utf-8")
    seen = page.client.get("/api/runtime", headers=HEADERS).json()
    assert seen["update"] is None and seen["checkFailed"] is True


def test_someone_who_asks_is_told_even_with_the_daily_check_off(page, monkeypatch) -> None:
    monkeypatch.setenv("UPDATE_CHECK_ENABLED", "false")
    _found(page.home)
    assert updates.notice(page.home) is None
    assert page.client.get("/api/runtime", headers=HEADERS).json()["update"]["version"] == "99.0.0"


def test_the_panel_shows_what_the_models_used_today_and_this_week(page) -> None:
    from mibo import usage

    assert page.client.get("/api/runtime", headers=HEADERS).json()["usage"]["week"]["calls"] == 0
    now = time.time()
    book = usage.UsageBook(page.home / "runtime" / usage.USAGE_FILE)
    book.add("main", {"prompt_tokens": 900, "completion_tokens": 100, "cost": 0.01}, now)
    book.add("judge", {"prompt_tokens": 50}, now)
    book.add("main", {"prompt_tokens": 10}, now - 3 * 86400)
    book.add("main", {"prompt_tokens": 10}, now - 9 * 86400)
    book.flush(now)
    seen = page.client.get("/api/runtime", headers=HEADERS).json()["usage"]
    assert (seen["today"]["calls"], seen["today"]["tokens"], seen["today"]["cost"]) == (2, 1050, 0.01)
    assert (seen["week"]["calls"], seen["week"]["tokens"]) == (3, 1060)
    assert [m["model"] for m in seen["models"]] == ["main", "judge"]
    assert seen["todayPurposes"] == {"other": 2}


def test_the_panel_splits_todays_requests_by_purpose(page) -> None:
    from mibo import usage

    now = time.time()
    book = usage.UsageBook(page.home / "runtime" / usage.USAGE_FILE)
    for label in ("reply", "reply", "gate", "check"):
        book.add("main", {}, now, label)
    book.flush(now)
    seen = page.client.get("/api/runtime", headers=HEADERS).json()["usage"]
    assert seen["todayPurposes"] == {"reply": 2, "gate": 1, "check": 1}



# ---------------------------------------------------------------- the window's own bar

# A browser tab is told the figure the pet would be: in a new home, the first.
NO_BAR = {"frameless": False, "maximized": False, "figure": "mibo", "goto": ""}

def test_a_browser_tab_and_a_framed_window_are_told_to_draw_no_bar(page) -> None:
    assert page.client.get("/api/window").status_code == 403
    assert page.client.post("/api/window", json={"action": "minimize"}).status_code == 403
    assert page.client.get("/api/window", headers=HEADERS).json() == NO_BAR
    refused = page.client.post("/api/window", json={"action": "minimize"}, headers=HEADERS)
    assert (refused.status_code, refused.json()) == (400, {"error": "window_unavailable"})
    # A window that kept its title bar: the page's buttons are not shown and do nothing.
    own = {**HEADERS, runtime.WINDOW_HEADER: "its-key"}
    page.app.state.window = types.SimpleNamespace(
        can_hide=True, frameless=False, maximized=False, frame_seen=lambda: None,
        figure=lambda: "deepseek", take_goto=lambda: "",
        control=lambda action: True, is_own_page=lambda key: key == "its-key")
    assert page.client.get("/api/window", headers=own).json()["frameless"] is False
    assert page.client.post("/api/window", json={"action": "minimize"}, headers=own).status_code == 400


def test_the_bar_s_buttons_reach_the_window(page) -> None:
    asked, seen = [], []

    def control(action: str) -> bool:
        asked.append(action)
        if action == "maximize":
            shown.maximized = True
        return action != "close"

    shown = types.SimpleNamespace(frameless=True, maximized=False, frame_seen=lambda: seen.append(1),
                                  figure=lambda: "deepseek", take_goto=lambda: "",
                                  control=control, is_own_page=lambda key: key == "its-key")
    page.app.state.window = shown
    own = {**HEADERS, runtime.WINDOW_HEADER: "its-key"}
    # A browser tab on the same address has the token and not the window's key:
    # it draws no window bar, presses no button, and does not count as the page having asked.
    for tab in (HEADERS, {**HEADERS, runtime.WINDOW_HEADER: "guess"}):
        assert page.client.get("/api/window", headers=tab).json() == NO_BAR
        refused = page.client.post("/api/window", json={"action": "close"}, headers=tab)
        assert (refused.status_code, refused.json()) == (400, {"error": "window_unavailable"})
    assert seen == [] and asked == []
    assert page.client.get("/api/window", headers=own).json() == {**NO_BAR, "frameless": True, "figure": "deepseek"}
    assert seen == [1], "the window is told the page draws the bar"
    done = page.client.post("/api/window", json={"action": "maximize"}, headers=own)
    assert done.json() == {**NO_BAR, "frameless": True, "maximized": True, "figure": "deepseek"}
    assert page.client.post("/api/window", json={"action": "minimize"}, headers=own).status_code == 200
    # Not one of the four, and one the window could not do.
    for action in ("resize-top", "", "close"):
        refused = page.client.post("/api/window", json={"action": action}, headers=own)
        assert (refused.status_code, refused.json()) == (400, {"error": "window_unavailable"}), action
    assert asked == ["maximize", "minimize", "close"]
