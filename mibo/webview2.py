"""The WebView2 plumbing of the app's browser (browser.py, signedread.py, signwatch.py): a view on the pane's
folder, a script run in its page and a DevTools call to it, each on the thread it must run on."""
from __future__ import annotations

import contextlib
import functools
import json
import threading
from collections.abc import Callable
from pathlib import Path

# A DevTools call to the page: how long it may take.
CDP_S = 20.0
# Every view on the pane's folder runs with Playwright's own switches for pages not in front, so a page out of sight
# keeps its timers and drawing (the views of one folder share one browser and must ask alike).
BROWSER_ARGS = ("--disable-background-timer-throttling --disable-renderer-backgrounding "
                "--disable-backgrounding-occluded-windows")


@functools.cache
def language() -> str:
    """The language of the browser's own prompts (Save password?): the app's as the browser first starts, not the
    system's. Every WebView2 on the pane's folder asks for this same one, or the later ones fail to start."""
    from . import i18n
    code = i18n.lang()
    return {"zh": "zh-CN"}.get(code, code)


def make_view(folder: Path, private: bool = False):
    """A WebView2 control on the pane's folder, so in the same browser processes as the pane's tabs, not started
    yet; `private`: an InPrivate profile, so no sign-in of the person's reaches the page and nothing of it stays."""
    from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2

    view = WebView2()
    properties = CoreWebView2CreationProperties()
    properties.UserDataFolder = str(Path(folder) / "webview")
    properties.IsInPrivateModeEnabled = private
    properties.Language = language()
    properties.AdditionalBrowserArguments = BROWSER_ARGS
    view.CreationProperties = properties
    return view


def seal(core) -> None:
    """Nothing reaches Python from the page, and nobody inspects the app through it."""
    settings = core.Settings
    settings.IsWebMessageEnabled = False
    settings.AreHostObjectsAllowed = False
    settings.AreDevToolsEnabled = False


def run_script(core, script: str) -> tuple[threading.Event, list]:
    """Run `script` in a page, on the form's thread; its answer is heard there too (as pywebview does)."""
    from System import Action, String
    from System.Threading.Tasks import Task, TaskScheduler

    done = threading.Event()
    heard: list = []

    def finished(task) -> None:
        with contextlib.suppress(Exception):
            heard.append(task.Result)
        done.set()
    core.ExecuteScriptAsync(script).ContinueWith(Action[Task[String]](finished),
                                                  TaskScheduler.FromCurrentSynchronizationContext())
    return done, heard


def script_answer(asked: tuple[threading.Event, list] | None, seconds: float):
    """What a script run by `run_script` answered, from a thread other than the form's; None when it took too
    long."""
    if not asked:
        return None
    done, heard = asked
    return heard[0] if done.wait(seconds) and heard else None


def _devtools(core, method: str, params: dict, box: dict, done: threading.Event, session: str = "") -> None:
    """One DevTools protocol call in the page, or with `session` in one of its frames from another site, in
    process (no debugging port); started on the form's thread, its answer heard on a pool thread, so a thread
    waiting for it never holds the form."""
    from System import Action, String
    from System.Threading.Tasks import Task

    def finished(task) -> None:
        try:
            box["result"] = json.loads(str(task.Result))
        except Exception:
            inner = task.Exception.InnerException if task.Exception is not None else None
            box["error"] = str(inner.Message if inner is not None else "the call failed")
        done.set()
    box["handler"] = finished
    call = (core.CallDevToolsProtocolMethodForSessionAsync(session, method, json.dumps(params)) if session
            else core.CallDevToolsProtocolMethodAsync(method, json.dumps(params)))
    call.ContinueWith(Action[Task[String]](finished))


def call_devtools(ui: Callable, core_of: Callable, method: str, params: dict, timeout: float,
                  session: str = "") -> dict:
    """`method` sent to the page `core_of()` gives (on the form's thread), from a thread other than the
    form's; a suspended page is resumed first. Raises RuntimeError with the page's own reason."""
    box: dict = {}
    done = threading.Event()

    def start() -> None:
        core = core_of()
        if core is None:
            box["error"] = "the page is closed"
            done.set()
            return
        if core.IsSuspended:
            core.Resume()
        _devtools(core, method, params, box, done, session)
    ui(start)
    if not done.wait(timeout):
        raise RuntimeError(f"Timed out: {method}")
    if "error" in box:
        raise RuntimeError(box["error"])
    return box["result"]
