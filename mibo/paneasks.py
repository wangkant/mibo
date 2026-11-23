"""What a site asks of the person in the pane (browser.Pane), said on the strip under the bar (browsestrip.js) for
the tab in front: the camera, the microphone, the location and the rest (允许, 始终允许, 不允许, as browsers ask), a link
to a program of this computer (mailto:, weixin:), which is never started by the site, and a popup the page opened by
itself, which was stopped. A tab behind keeps what it asks until it comes to the front. While the character operates
nothing is asked and everything is refused. Only a refusal is saved in the profile (the browser then refuses by
itself); an allowance is kept here, so neither a run nor the Reader is ever given one."""
from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .signwatch import Profile
from .webview2 import CDP_S

if TYPE_CHECKING:
    from .browser import _Tab

# The permissions the strip asks for, by WebView2's name. The rest (notifications, sensors, autoplay, kinds not
# known) are refused without a word.
ASKED = {"Camera": "camera", "Microphone": "microphone", "Geolocation": "geolocation", "ClipboardRead": "clipboard",
         "MultipleAutomaticDownloads": "downloads", "FileReadWrite": "files", "LocalFonts": "fonts",
         "MidiSystemExclusiveMessages": "midi", "WindowManagement": "windows"}


def origin_of(address: str) -> str:
    """The site a permission is for, as the browser's profile writes it: "https://host[:port]/"."""
    parts = urlsplit(str(address))
    return f"{parts.scheme}://{parts.netloc}/" if parts.netloc else ""


class AskingPane:
    """The part of browser.Pane that holds what sites ask, on the form's thread (`permits` and `unpermit` come from
    another). Each tab keeps its own `notices` and the permissions allowed `once` on its page."""

    def _permission(self, sender, args) -> None:
        """A site asks for the camera, the microphone, the location or the rest. Refused without a word while the
        character operates, and for the kinds never asked about; allowed at once where the person allowed it always,
        or this time on this page; else the strip asks, for the tab that asked (a deferral holds the site's request
        until the press). Nothing is saved in the profile here: the press decides that."""
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState as State
        tab, kind, origin = self._tab_of(sender), ASKED.get(str(args.PermissionKind), ""), origin_of(str(args.Uri))
        args.SavesInProfile = False
        if self.op is not None or not kind or tab is None:
            args.State = State.Deny
            return
        if kind in self._permits(tab).get(origin, ()) or kind in tab.once.get(origin, ()):
            args.State = State.Allow
            return
        # A page asking for the camera and the microphone at once is asked about both on one strip.
        notice = next((n for n in tab.notices if n["kind"] == "permission" and n["origin"] == origin), None)
        if notice is None:
            notice = self._notice(tab, "permission", origin=origin, what=[], asks=[])
        if kind not in notice["what"]:
            notice["what"] = sorted({*notice["what"], kind}, key=list(ASKED.values()).index)
        notice["asks"].append((args, args.GetDeferral()))
        if tab is self._tab:
            self._tell_prompt()

    def _permits(self, tab: _Tab) -> dict:
        return self._permits_private if tab.private else self._kept["permits"]

    def _notice(self, tab: _Tab, kind: str, origin: str = "", **more) -> dict:
        """Something for the strip, on `tab`: a permission asked, a program's link, a popup stopped. A program's link
        or a popup takes the place of the one of its kind before it."""
        tab.notices[:] = [n for n in tab.notices if n["kind"] == "permission" or n["kind"] != kind]
        self._noticed += 1
        host = urlsplit(origin or (str(tab.core.Source) if tab.core is not None else tab.url)).hostname or ""
        notice = {"id": self._noticed, "kind": kind, "origin": origin, "host": host, **more}
        tab.notices.append(notice)
        if tab is self._tab and kind != "permission":
            self._tell_prompt()
        return notice

    def _tell_prompt(self) -> None:
        """The strip shows the first thing the tab in front asks, or nothing."""
        tab = self._tab
        notice = tab.notices[0] if tab is not None and tab.notices else None
        self.tell({"prompt": None if notice is None else {k: v for k, v in notice.items() if k != "asks"}})

    def _clear(self, tab: _Tab) -> None:
        """What `tab` asked goes unanswered, refused and not saved (its page left, it closed, a run began), and what
        was allowed this time ends with its page."""
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState as State
        for notice in tab.notices:
            for args, deferral in notice.get("asks", ()):
                args.State = State.Deny
                deferral.Complete()
        tab.notices.clear()
        tab.once.clear()

    def _answer(self, ident: int, how: str) -> None:
        """The person's press on the strip: "once" (允许, 打开), "always" (始终允许) or "no" (不允许, 取消, ×). A
        refusal is saved in the profile, so the browser refuses by itself from then on; an allowance is kept here
        (always) or for this page (once). Nothing is allowed while the character operates."""
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState as State
        tab = next((t for t in self._tabs if any(n["id"] == ident for n in t.notices)), None)
        if tab is None or (self.op is not None and how != "no"):
            return
        notice = next(n for n in tab.notices if n["id"] == ident)
        tab.notices.remove(notice)
        yes = how != "no"
        if notice["kind"] == "permission":
            origin, what = notice["origin"], notice["what"]
            if how == "always":
                permits = self._permits(tab)
                permits[origin] = sorted({*permits.get(origin, ()), *what})
                if not tab.private:
                    self._keep()
            elif yes:
                tab.once.setdefault(origin, set()).update(what)
            for args, deferral in notice["asks"]:
                args.State = State.Allow if yes else State.Deny
                args.SavesInProfile = not yes and not tab.private
                deferral.Complete()
        elif notice["kind"] == "app" and yes:
            threading.Thread(target=os.startfile, args=(notice["url"],), name="mibo-browser", daemon=True).start()
        elif notice["kind"] == "popup" and yes:
            # In a tab of its own in front, as a link would open (the page that tried keeps no hold of it).
            self._switch(self._new_tab(tab.private))
            self._open(notice["url"], here=True)
        self._tell_prompt()

    def _hush(self) -> None:
        """A run begins: whatever the tabs were asking is refused, and nothing is asked until it ends."""
        for tab in self._tabs:
            self._clear(tab)
        self._tell_prompt()

    def permits(self) -> list[dict]:
        """The site permissions the person decided, for Settings, by site: [{"origin", "host", "kinds": [{"kind",
        "state": "allow" | "deny"}]}]. Allowed always is kept here; refused is in the profile (WebView2's
        GetNonDefaultPermissionSettingsAsync). From a thread other than the form's."""
        rows = {(origin, kind): "allow" for origin, kinds in self._kept["permits"].items() for kind in kinds}
        with Profile(self).page() as (_, core_of):
            asked: list = []
            self.ui(lambda: asked.append(core_of().Profile.GetNonDefaultPermissionSettingsAsync()))
            asked[0].Wait(int(CDP_S * 1000))
            self.ui(lambda: rows.update({(str(s.PermissionOrigin), ASKED[str(s.PermissionKind)]): "deny"
                                         for s in asked[0].Result if str(s.PermissionKind) in ASKED
                                         and str(s.PermissionState) == "Deny"}))
        sites: dict[str, dict] = {}
        for (origin, kind), state in rows.items():
            site = sites.setdefault(origin, {"origin": origin, "host": urlsplit(origin).hostname or origin, "kinds": []})
            site["kinds"].append({"kind": kind, "state": state})
        return sorted(sites.values(), key=lambda site: site["host"])

    def unpermit(self, origin: str, kind: str) -> None:
        """A site permission taken back in Settings: the site is asked about it again next time. From a thread other
        than the form's."""
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind as Kind
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState as State

        def drop() -> None:
            kinds = self._kept["permits"].get(origin, [])
            if kind in kinds:
                kinds.remove(kind)
                if not kinds:
                    del self._kept["permits"][origin]
                self._keep()
        self.ui(drop)
        name = next(name for name, word in ASKED.items() if word == kind)
        with Profile(self).page() as (_, core_of):
            asked: list = []
            self.ui(lambda: asked.append(core_of().Profile.SetPermissionStateAsync(getattr(Kind, name), origin,
                                                                                    State.Default)))
            asked[0].Wait(int(CDP_S * 1000))

    def _external(self, sender, args) -> None:
        """mailto:, a program's own scheme: never started by the site (nor the browser's own dialog shown); the strip
        names it, and its 打开 starts it, the person's own press. Nothing is named while the character operates."""
        args.Cancel = True
        tab = self._tab_of(sender)
        if self.op is None and tab is not None:
            self._notice(tab, "app", origin_of(str(args.InitiatingOrigin)), url=str(args.Uri))
