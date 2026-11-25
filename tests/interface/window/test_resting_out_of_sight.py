"""Pages at rest while out of sight: the app window's, the browser pane's tabs and the pet's compact chat. WebView2's
own steps (winforms.rest and wake) are stood in for and noted in order; nothing is drawn."""
from __future__ import annotations

import threading
import types

import pytest

from mibo import browser, petchat, window
from mibo.window import winforms


class Shown:
    """The app window as pywebview gives it: its form's WebView, and what is asked of it, noted in `log`."""

    def __init__(self, log: list, name: str = "main") -> None:
        self.log = log
        self.native = types.SimpleNamespace(browser=types.SimpleNamespace(webview=name))

    def evaluate_js(self, script: str) -> None:
        self.log.append(("told", self.native.browser.webview, script))

    def show(self) -> None:
        self.log.append(("show",))

    def hide(self) -> None:
        self.log.append(("hide",))

    def restore(self) -> None:
        self.log.append(("restore",))


@pytest.fixture
def log(monkeypatch) -> list:
    """What was done, in order: WebView2's rest and wake run on the window's thread, here at once."""
    done: list = []
    monkeypatch.setattr(winforms, "on_thread", lambda form, action: action())
    monkeypatch.setattr(winforms, "rest", lambda view: done.append(("rest", view)))
    monkeypatch.setattr(winforms, "wake", lambda view: done.append(("wake", view)))
    return done


def _settled() -> None:
    """The threads that tell a page or let it rest have finished."""
    for thread in threading.enumerate():
        if thread.name in ("mibo-tell", "mibo-rest"):
            thread.join(5)


def _app(log: list, tmp_path) -> window.AppWindow:
    app = window.AppWindow("http://127.0.0.1:1/", storage=tmp_path)
    app._window = Shown(log)
    app._tray = object()
    app.opened = True
    return app


def test_a_window_put_away_rests_its_page_once_the_page_came_up(log, tmp_path) -> None:
    app = _app(log, tmp_path)
    assert app.hide() is True
    assert log == [("hide",)], "a page still loading is left to load and draw its bar"
    app.frame_seen()
    _settled()
    assert log == [("hide",), ("rest", "main")]
    assert app.show() is True
    assert log[2:] == [("wake", "main"), ("show",)], "the page wakes before the window shows"


def test_what_the_page_is_told_at_rest_is_told_in_order_when_it_wakes(log, tmp_path) -> None:
    app = _app(log, tmp_path)
    pet = Shown(log, "pet")
    app.frame_seen()
    app.hide()
    for script in ("a()", "b()", "a()"):
        app._tell(app._window, script)
    app._tell(pet, "petLook()")
    _settled()
    assert [entry for entry in log if entry[0] == "told"] == [("told", "pet", "petLook()")], \
        "only the page at rest waits"
    app.show()
    _settled()
    assert [entry[2] for entry in log if entry[:2] == ("told", "main")] == ["b()", "a()"], \
        "each once, where it was told last"


def test_a_minimized_window_rests_its_page_until_it_is_back(log, tmp_path) -> None:
    app = _app(log, tmp_path)
    app.frame_seen()
    app._sized(True)()
    app._sized(True)()
    assert log == [("rest", "main")] and app.attended() is False
    app._sized(False, True)()
    assert [entry for entry in log if entry[0] != "told"] == [("rest", "main"), ("wake", "main")]
    assert app.attended() is True


def test_the_browser_pane_rests_and_wakes_with_the_window(log, tmp_path) -> None:
    app = _app(log, tmp_path)
    app._browser = types.SimpleNamespace(away=lambda on: log.append(("pane", on)))
    app.frame_seen()
    app.hide()
    app.show()
    assert log == [("rest", "main"), ("pane", True), ("hide",), ("wake", "main"), ("pane", False), ("show",)]


# -- the browser pane's tabs (browser.rests) ------------------------------------------------

NOW = 10_000.0


def _tab(**state) -> browser._Tab:
    tab = browser._Tab(1, False)
    tab.left = NOW
    for key, value in state.items():
        setattr(tab, key, value)
    return tab


def test_a_tab_in_use_stays_awake() -> None:
    assert browser.rests(_tab(), front=True, worked=False, away=False, quiet=False, now=NOW) is False
    assert browser.rests(_tab(), front=False, worked=False, away=False, quiet=False,
                         now=NOW + browser.IDLE_S - 1) is False, "a tab just left keeps going for a while"


def test_a_tab_out_of_the_front_for_some_minutes_rests() -> None:
    later = NOW + browser.IDLE_S
    assert browser.rests(_tab(), front=False, worked=False, away=False, quiet=False, now=later) is True
    assert browser.rests(_tab(), front=True, worked=False, away=False, quiet=False, now=later) is False


def test_while_the_window_is_away_every_tab_rests_but_one_the_character_works_out_of_sight() -> None:
    assert browser.rests(_tab(), front=True, worked=False, away=True, quiet=False, now=NOW) is True
    assert browser.rests(_tab(aside=True), front=False, worked=False, away=True, quiet=False, now=NOW) is False
    assert browser.rests(_tab(aside=True), front=False, worked=False, away=True, quiet=False,
                         now=NOW + browser.IDLE_S) is True, "left alone, it rests too"


@pytest.mark.parametrize("state, worked", [({"sound": True}, False), ({}, True), ({"used": NOW}, False)])
def test_sound_a_run_or_a_call_from_code_keeps_a_tab_awake(state, worked) -> None:
    tab = _tab(**state)
    assert browser.rests(tab, front=False, worked=worked, away=True, quiet=False, now=NOW + 1) is False


def test_quiet_rests_every_tab() -> None:
    assert browser.rests(_tab(sound=True), front=True, worked=True, away=False, quiet=True, now=NOW) is True


def test_a_new_tab_has_never_been_called_and_is_not_resting() -> None:
    tab = browser._Tab(1, False)
    assert tab.resting is False
    assert browser.rests(tab, front=False, worked=False, away=False, quiet=False, now=tab.left) is False


# -- the pet's compact chat ------------------------------------------------------------------

class Form:
    def __init__(self, log: list) -> None:
        self.log = log
        self.browser = types.SimpleNamespace(webview="compact")
        self.Opacity = 1.0
        self.hidden = threading.Event()

    def Hide(self) -> None:
        self.log.append(("hide",))
        self.hidden.set()


def _owner(log: list) -> types.SimpleNamespace:
    return types.SimpleNamespace(_on_pet=lambda action: action(), _tell=lambda view, script: None, _pet=object(),
                                 _leaving=False, _compact=None)


def test_the_compact_chat_put_away_rests_before_it_hides(log) -> None:
    chat = petchat.Compact(_owner(log))
    chat.window = types.SimpleNamespace(native=Form(log))
    chat.out = True
    chat.away(fade=False)
    assert log == [("rest", "compact"), ("hide",)] and chat.out is False


def test_the_compact_chat_made_ahead_rests_until_it_is_asked_for(log, monkeypatch) -> None:
    owner, form = _owner(log), Form(log)
    monkeypatch.setattr(petchat, "WARM_S", 0)
    monkeypatch.setattr(petchat.Compact, "_make", lambda chat: setattr(chat, "window", types.SimpleNamespace(native=form)))
    petchat.warm(owner)
    assert form.hidden.wait(5)
    assert log == [("rest", "compact"), ("hide",)] and owner._compact.out is False
