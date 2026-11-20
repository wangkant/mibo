"""Signing in to sites in the app's own browser, and what Settings › 连接 shows of it (web/signin.py).

/api/browser/signin is the service's: a run (web/operate.py) or a read with the
person's session that met a sign-in asks the pane to wait for the person
("begin" or "read"), then looks again until the page is past it ("poll"); the
chat's sign_in_to_site (web/connect.py) brings a site's sign-in to the pane
("connect") and asks how it stands ("connected"). While it waits, the column
beside the page says what is needed, the person's moves in the page do not
pause the run, and if the browser filled a saved password the site's own
sign-in button is pressed, once allowed on the 自动登录 card.

/api/signins is Settings': the sites signed in to (from the profile's cookie
names and the evidence kept, nothing loaded from the site), each with when it
was last used and the person's choices; the well-known sites to sign in to;
signing in from there; signing out of one; and clearing every session or every
saved password. Changes come from the app window's own page alone."""
from __future__ import annotations

import asyncio
import base64
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import Request

ERRORS: frozenset[str] = frozenset({"signin_invalid", "signin_window", "signin_none"})
# Settings' sign-in waits this long for the person before the column lets go.
SETTINGS_WAIT_S = 600.0
# A run's page past the sign-in this many looks in a row with no account: the person went on without one.
PAST_LOOKS = 3
# A site the cookies say is signed in: its sign-in page is looked at this long after it is opened.
CHECK_S = 3.0
# Steps in the column: the wait, its end, the press of the site's sign-in button, the task of a sign-in from Settings.
SAID = {
    "zh": {"wait": "等待登录 {host}", "check": "等待完成 {host} 的验证", "done": "已登录 {host}",
           "skip": "未登录，继续操作", "press": "按下网站的「{button}」按钮", "open": "打开 {host}",
           "task": "登录 {name}", "read": "已登录，继续读取。", "signed": "已登录 {name}，可以关闭此网页。"},
    "en": {"wait": "Waiting for sign-in on {host}", "check": "Waiting for the check on {host}",
           "done": "Signed in on {host}", "skip": "Not signed in; going on", "press": "Press the site’s “{button}” button",
           "open": "Open {host}", "task": "Sign in to {name}", "read": "Signed in; reading goes on.",
           "signed": "Signed in to {name}. You can close this page."},
}


def _lang(app) -> str:
    run = getattr(app.state, "operating", None)
    lang = run.lang if run is not None and run.hands is not None else os.environ.get("AGENT_LANG", "zh")
    return "zh" if str(lang).startswith("zh") else "en"


class Waiting:
    """The one wait in the pane: for which wall, on which page and site, whose the column's run is when it is its
    own ("read", or the site's name from Settings or the chat), whether a wall has been seen yet, the 自动登录 card
    and its answer, and where the site's sign-in button was pressed."""

    def __init__(self, desktop):
        self.desktop = desktop
        self.state: dict | None = None

    def begin(self, pane, wall: str, lang: str, own: str = "", seen: bool = True) -> None:
        from ..web import signin
        url = pane.address()
        host = urlsplit(url).hostname or ""
        self.state = {"wall": wall, "host": host, "site": signin.key(url), "lang": lang, "own": own, "seen": seen,
                      "asked": False, "once": False, "pressed": "", "card": "", "began": time.time(), "past": 0}
        pane.op["wait"] = {"wall": wall, "site": host}
        pane.op_said(SAID[lang]["check" if wall == "verification" else "wait"].format(host=host))

    def poll(self, pane, within: float) -> dict:
        """Look at the page until it is past the wall or `within` seconds went: {"status": "ok"|"waiting"|
        "stopped"}, "ok" with "signed": False when a run's page went on without an account."""
        from .. import signwatch
        from ..web import signin
        state, until = self.state, time.monotonic() + within
        while True:
            op = pane.op
            if state is None or state is not self.state or op is None or not op.get("wait"):
                return {"status": "stopped"}
            if op.get("held") == "stopped":
                self.state = None
                return {"status": "stopped"}
            url = pane.address()
            found = signwatch.check(pane.cdp, url)
            if found.get("kind") in signin.WAITED or found.get("form"):
                state["seen"] = state["seen"] or found.get("kind") in signin.WAITED
                state["past"] = 0
                signwatch.observe(pane, url, found)
            elif signin.past(found, url):
                now = signwatch.observe(pane, url, found)
                entry = signin.load(self.desktop).get(signin.key(url)) or {}
                if now == "in" and (state["seen"] or entry.get("at", 0) >= state["began"] - 1):
                    return self._past(pane, url, True)
                state["past"] += 1
                if not state["own"] and state["seen"] and state["past"] >= PAST_LOOKS:
                    return self._past(pane, url, False)
            if found.get("filled") and found.get("button"):
                self._filled(pane, url, found["button"])
            if time.monotonic() > until:
                return {"status": "waiting"}
            time.sleep(1.0)

    def _past(self, pane, url: str, signed: bool) -> dict:
        state, op = self.state, pane.op
        said = SAID[state["lang"]]
        if op["steps"] and op["steps"][-1]["state"] == "doing":
            op["steps"][-1].update(state="done", text=said["done" if signed else "skip"].format(host=state["host"]))
        op.update(wait=None, card=None)
        pane._tell_op()
        if state["own"]:
            pane.op_end("done", said["read"] if state["own"] == "read" else said["signed"].format(name=state["own"]))
        self.state = None
        return {"status": "ok", "url": url, "signed": signed}

    def _filled(self, pane, url: str, button: dict) -> None:
        """The browser filled a saved password: the site's own button is pressed when the person allows it for
        the site (asked once on the card), never more than once on a page."""
        from ..web import signin
        state, op = self.state, pane.op
        allowed = signin.auto(self.desktop, url)
        if allowed == "always" or state["once"]:
            if state["pressed"] == url:
                return
            state["pressed"] = url
            pane.op_said(SAID[state["lang"]]["press"].format(button=button.get("words") or "→"))
            for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
                pane.cdp("Input.dispatchMouseEvent", {"type": kind, "x": button["x"], "y": button["y"],
                                                      "button": "left", "buttons": 1, "clickCount": 1})
            pane.op_result("done")
            # Back to waiting: a code or a check after it is still the person's.
            pane.op_said(SAID[state["lang"]]["wait"].format(host=state["host"]))
        elif not allowed and not state["asked"]:
            state["asked"], state["card"] = True, secrets.token_urlsafe(8)
            op["card"] = {"id": state["card"], "kind": "auto_sign_in", "site": state["host"]}
            pane._tell_op()

    def answer(self, pane, ident: str, said: str) -> bool:
        """The person's press on the 自动登录 card: "once", "always" or "no" ("always" and "no" kept for the
        site, changeable in Settings)."""
        from ..web import signin
        state = self.state
        if state is None or pane.op is None or state["card"] != ident:
            return False
        if said in ("always", "no"):
            def keep(entry: dict) -> None:
                entry["auto"] = "always" if said == "always" else "never"
            signin.change(self.desktop, signin.key(pane.address()), keep)
        state["once"] = said in ("once", "always")
        state["card"] = ""
        pane.op["card"] = None
        pane._tell_op()
        return True

    def end(self, pane) -> None:
        self.state = None
        if pane.op is not None:
            pane.op.update(wait=None, card=None)


def mount(app, workspace, body) -> None:
    from .. import browsed
    from ..web import gate, signin, sites
    from .runtime import WINDOW_HEADER

    desktop = workspace.home / "runtime" / "desktop"
    runtime = desktop.parent
    waiting = Waiting(desktop)

    def window_or_none():
        window = getattr(app.state, "window", None)
        if window is None or window.pane is None:
            raise ValueError("signin_none")
        return window

    def own_window(request: Request):
        window = getattr(app.state, "window", None)
        if window is None or window.pane is None or not window.is_own_page(request.headers.get(WINDOW_HEADER, "")):
            raise ValueError("signin_window")
        return window

    def names(window) -> dict | None:
        """{site: cookie names} the profile holds; None when it could not be opened."""
        from ..signwatch import Profile
        try:
            return Profile(window.pane).names() if window is not None else None
        except RuntimeError:
            return None

    def state_of(window, site: str) -> str:
        held = names(window)
        return signin.status(signin.load(desktop).get(site), None if held is None else held.get(signin.bare(site), set()),
                             site)

    def open_waiting(window, url: str, task: str, wall: str, own: str, seen: bool) -> dict:
        """The page brought to the pane for a sign-in that no run waits on (a read, Settings, the chat): a run of
        its own in the column, waiting."""
        pane = window.pane
        if pane.op is not None:
            return {"status": "busy"}
        if not pane.ready(url):
            return {"status": "no_page"}
        lang = _lang(app)
        pane.operate(task)
        pane.op_said(SAID[lang]["open"].format(host=urlsplit(url).hostname or ""))
        pane.op_result("done")
        waiting.begin(pane, wall, lang, own=own, seen=seen)
        return waiting.poll(pane, 2.0)

    def own_sign_in(window, name: str, url: str, lang: str) -> None:
        """A sign-in asked for from Settings or the chat: the site's sign-in page in the pane, the column waiting
        until the person is in."""
        pane = window.pane
        began = open_waiting(window, url, SAID[lang]["task"].format(name=name), "sign_in", name, False)
        if began.get("status") != "waiting":
            return
        until = time.monotonic() + SETTINGS_WAIT_S
        while time.monotonic() < until and pane._view is not None:
            if waiting.poll(pane, signin.POLL_S).get("status") != "waiting":
                return
        if pane.op is not None and waiting.state is not None:
            waiting.end(pane)
            pane.op_end("stopped", "")

    def start_sign_in(window, name: str, home: str, url: str) -> dict:
        """Settings' 登录 or the chat's: a site already signed in just opens; else its sign-in waits in the pane."""
        from ..signwatch import check
        site = signin.key(home)
        if state_of(window, site) == "in" and window.pane.op is None:
            # The cookies say signed in; the site's sign-in page says whether the site still agrees (it lets a
            # signed-in person through, or shows its form again: then the person signs in again here).
            window.pane.ready(url or home)
            time.sleep(CHECK_S)
            found = check(window.pane.cdp, window.pane.address())
            if not (found.get("form") or found.get("kind") in signin.WAITED):
                return {"status": "in", "site": site}
        if window.pane.op is not None:
            return {"status": "busy", "site": site}
        signin.change(desktop, site, lambda entry: entry.update(name=entry.get("name") or name,
                                                                home=entry.get("home") or home))
        threading.Thread(target=own_sign_in, args=(window, name, url or home, _lang(app)), name="personagent-signin",
                         daemon=True).start()
        return {"status": "waiting", "site": site}

    @app.post("/api/browser/signin")
    async def browser_signin(request: Request):
        """The service's: begin waiting in the pane for the person's sign-in, look again, or give up; bring a
        site's sign-in to the pane for the chat, and say how it stands."""
        payload = await body(request)
        op, window = payload.get("op"), window_or_none()
        pane = window.pane
        if op == "begin":
            if pane.op is None:
                return {"status": "stopped"}
            await asyncio.to_thread(waiting.begin, pane, str(payload.get("wall") or "sign_in"), _lang(app))
            return await asyncio.to_thread(waiting.poll, pane, 2.0)
        if op == "read":
            url, task = payload.get("url"), payload.get("task")
            if not (isinstance(url, str) and browsed.web(url) and isinstance(task, str) and task.strip()):
                raise ValueError("signin_invalid")
            # Nobody at the app: nothing comes up for them; the read says the site wants a sign-in.
            if not window.attended():
                return {"status": "away"}
            return await asyncio.to_thread(open_waiting, window, url, task.strip()[:200],
                                           str(payload.get("wall") or "sign_in"), "read", True)
        if op == "poll":
            return await asyncio.to_thread(waiting.poll, pane, signin.POLL_S)
        if op == "end":
            await asyncio.to_thread(waiting.end, pane)
            return {"status": "ok"}
        if op == "connect":
            home, url, name = payload.get("home"), payload.get("url"), payload.get("name")
            if not (isinstance(home, str) and browsed.web(home) and isinstance(url, str) and browsed.web(url)
                    and isinstance(name, str) and name.strip()):
                raise ValueError("signin_invalid")
            if not window.attended():
                return {"status": "away"}
            return await asyncio.to_thread(start_sign_in, window, name.strip()[:60], home, url)
        if op == "connected":
            site = str(payload.get("site") or "")
            if waiting.state is not None and waiting.state["site"] == site and pane.op is not None:
                return {"status": "waiting"}
            return {"status": "ok" if await asyncio.to_thread(state_of, window, site) == "in" else "stopped"}
        raise ValueError("signin_invalid")

    @app.post("/api/signins/card")
    async def signin_card(request: Request):
        """The person's press on the 自动登录 card, from the app window's own page alone."""
        window = own_window(request)
        payload = await body(request)
        ident, said = payload.get("id"), payload.get("answer")
        if not isinstance(ident, str) or said not in ("once", "always", "no"):
            raise ValueError("signin_invalid")
        return {"ok": await asyncio.to_thread(waiting.answer, window.pane, ident, said)}

    def rows(window) -> dict:
        """The sites signed in to (or that the app cannot tell of), the well-known sites to sign in to, and the
        sessions and saved passwords the profile holds."""
        from ..signwatch import icon_path
        lang = _lang(app)
        held = names(window)
        saved = signin.load(desktop)
        keys = list(saved)
        # A session the profile holds for a well-known site counts though it was signed in to some other way.
        for row in signin.hints():
            if row["site"] not in keys and held is not None and signin.has_session(held.get(row["site"], set()),
                                                                                    row["site"]):
                keys.append(row["site"])
        cards = sites.load(runtime)
        allowed = gate.Allowed(desktop).all()
        out, kept = [], []
        for key in keys:
            entry, place = saved.get(key) or {}, signin.hint(key)
            state = signin.status(entry, None if held is None else held.get(signin.bare(key), set()), key)
            name = entry.get("name") or (place.get("name") or {}).get(lang) or (place.get("name") or {}).get("en") or key
            if state == "in" or entry.get("saved"):
                kept.append({"site": key, "name": name, "session": state == "in", "saved": bool(entry.get("saved"))})
            if state == "out":
                continue
            home = entry.get("home") or place.get("home") or f"https://{key}/"
            feed = (cards.get(sites.key_of(home)) or {}).get("feed") or {}
            icon = icon_path(desktop / "browser", key) if window is not None else None
            out.append({"site": key, "name": name, "home": home, "state": state,
                        "at": entry.get("at", 0), "used": entry.get("used", 0), "saved": bool(entry.get("saved")),
                        "auto": entry.get("auto", ""), "here": entry.get("here", True) is not False,
                        "task": entry.get("task", True) is not False, "background": bool(feed.get("on")),
                        "stopped": feed.get("stopped", ""), "fresh": bool(entry.get("fresh")),
                        "example": signin.example(key, lang), "allowed": allowed.get(key, []),
                        "icon": ("data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode())
                        if icon is not None and icon.exists() else signin.mark(place.get("id", ""))})
        listed = {signin.bare(r["site"]) for r in kept}
        others = sum(1 for site in (held or {}) if site not in listed)
        # Signed-in sites first, the most recently used first.
        out.sort(key=lambda row: (row["state"] != "in", -(row["used"] or row["at"] or 0)))
        wait = waiting.state
        return {"sites": out, "kept": kept, "others": others, "window": window is not None, "picks": signin.picks(lang),
                "waiting": wait["site"] if wait and wait["own"] and wait["own"] != "read" else ""}

    @app.get("/api/signins")
    async def signins_view():
        window = getattr(app.state, "window", None)
        return await asyncio.to_thread(rows, window if window is not None and window.pane is not None else None)

    @app.post("/api/signins")
    async def signins_change(request: Request):
        """Settings: sign in to a site (a well-known one or any address), a choice for one, sign out of one,
        mark its first panel seen, clear every session or every saved password."""
        from ..signwatch import Profile
        window = own_window(request)
        payload = await body(request)
        op, site = payload.get("op"), payload.get("site")
        if op == "signin":
            place = next((row for row in signin.hints() if row["id"] == payload.get("id")), None)
            if place is not None:
                lang = _lang(app)
                name, home, url = place["name"].get(lang) or place["name"]["en"], place["home"], place.get("signin") or ""
            else:
                typed = str(payload.get("url") or "").strip()
                typed = typed if "://" in typed else f"https://{typed}"
                parts = urlsplit(typed)
                if not browsed.web(typed) or not parts.hostname or "." not in parts.hostname and parts.hostname != "localhost":
                    raise ValueError("signin_invalid")
                found = signin.find(parts.hostname)
                entry = signin.load(desktop).get(signin.key(typed)) or {}
                name = entry.get("name") or (parts.hostname or "").removeprefix("www.")
                home = entry.get("home") or signin.home_of(typed)
                url = typed if parts.path not in ("", "/") else (entry.get("signin") or found.get("signin") or home)
            return await asyncio.to_thread(start_sign_in, window, name, home, url)
        if op == "clear" and payload.get("what") in ("sessions", "passwords"):
            what = payload["what"]
            await asyncio.to_thread(Profile(window.pane).clear, what)
            for key in list(signin.load(desktop)):
                if what == "sessions":
                    signin.signed_out(desktop, key)
                else:
                    signin.change(desktop, key, lambda entry: entry.pop("saved", None))
            return await asyncio.to_thread(rows, window)
        listing = await asyncio.to_thread(rows, window)
        row = next((r for r in listing["sites"] + listing["kept"] if r["site"] == site), None)
        if not isinstance(site, str) or row is None:
            raise ValueError("signin_invalid")
        if op == "seen":
            signin.change(desktop, site, lambda entry: entry.update(fresh=False, told=True))
        elif op == "choose" and payload.get("name") in ("here", "task", "auto", "background") \
                and isinstance(payload.get("on"), bool):
            name, on = payload["name"], payload["on"]
            if name == "background":
                def switch(card: dict) -> None:
                    feed = card.setdefault("feed", {})
                    feed.update(on=on, url=feed.get("url") or row["home"])
                    feed.pop("stopped", None)
                sites._change(runtime, sites.key_of(row["home"]), switch)
            else:
                value = ("always" if on else "never") if name == "auto" else on
                signin.change(desktop, site, lambda entry: entry.update({name: value}))
        elif op == "signout":
            await asyncio.to_thread(Profile(window.pane).sign_out, site)
            signin.signed_out(desktop, site)
        else:
            raise ValueError("signin_invalid")
        return await asyncio.to_thread(rows, window)
