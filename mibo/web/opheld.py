"""The page's own requests while operate.Hands acts: paused and looked at, what carries text typed in the run (or
a choice made in it, or leaves on a watched press, or takes the page to another site) held for a card, the rest let
through untouched; a held request let go on yes and dropped on no; and at the end, what was typed and never let out
put back. A mixin of operate.Hands: its state is set in Hands.__init__."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from urllib.parse import urlsplit

from . import gate
from .opcarry import beacon, bears, leaves_of, leaving, only_reads, shape, squeeze, summary_of, texts_of
from .opoutside import HEAR_S, RESTORE_JS, reading
from .opsaid import SAID
from .pagewords import clip

logger = logging.getLogger("mibo.web")

# Requests the page makes while the character operates that are paused and looked at: navigations, and the kinds
# that can send or change something. Images, scripts, styles, fonts and media load untouched until something is
# typed (TYPED_WATCHED): from then on a picture's address could carry it to another site.
WATCHED = [{"urlPattern": "*", "resourceType": kind, "requestStage": "Request"}
           for kind in ("Document", "XHR", "Fetch", "Ping", "Other")]
TYPED_WATCHED = WATCHED + [{"urlPattern": "*", "resourceType": kind, "requestStage": "Request"}
                           for kind in ("Image", "Script", "Stylesheet", "Font", "Media")]
# After a link the run followed or an address it was let go to, how long the page may go on to other sites by
# itself (a redirect, a search result's hop) without a card.
FOLLOW_S = 10.0


class Holding:
    """The page's own requests, for operate.Hands."""

    async def _watch(self) -> None:
        """Requests of the operated tab are paused and looked at, from the first look on; a file chooser the page
        opens is caught, never shown, and its dialogs are answered here."""
        if self._paused is not None or self._closed:
            return
        self._paused = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def heard(params: dict) -> None:
            # On the browser's own thread: handed to the loop, never answered here.
            if not self._closed:
                loop.call_soon_threadsafe(self._paused.put_nowait, params)

        def chooser(params: dict) -> None:
            if not self._closed:
                self._file = params

        def answer(params: dict) -> None:
            self._answering = loop.create_task(self._dialog(params))

        def dialog(params: dict) -> None:
            # Answered at once on the loop: the page, and the step that opened the dialog, wait for it.
            if not self._closed:
                loop.call_soon_threadsafe(answer, params)

        def answered(params: dict) -> None:
            if self._noting:
                self._status[str(params.get("requestId") or "")] = int((params.get("response") or {}).get("status") or 0)
        self._address = await self._url()
        self.sites.add(gate.site_of(self._address))
        self._frame = (await self.tab.cdp("Page.getFrameTree", {}))["frameTree"]["frame"]["id"]
        await self.tab.events("Fetch.requestPaused", heard)
        await self.tab.events("Page.fileChooserOpened", chooser)
        await self.tab.events("Page.javascriptDialogOpening", dialog)
        await self.tab.events("Network.responseReceived", answered)
        await self.tab.cdp("Network.enable", {})
        await self.tab.cdp("Fetch.enable", {"patterns": WATCHED})
        try:
            await self.tab.cdp("Page.enable", {})
            await self.tab.cdp("Page.setInterceptFileChooserDialog", {"enabled": True})
        except Exception:
            logger.info("[Agent] operate: the browser would not catch file choosers; a page may open one",
                        exc_info=True)
        self._drain = asyncio.create_task(self._let_through())

    async def _let_through(self) -> None:
        """Each paused request in turn: held for a card, set aside beside a confirmed press, or let go."""
        while not self._closed:
            params = await self._paused.get()
            try:
                await self._sort(params)
            except Exception:
                logger.debug("[Agent] operate: a paused request could not be let through", exc_info=True)

    async def _sort(self, params: dict) -> None:
        """One paused request: held (the page's own navigation with its card at once), set aside, or let go, a
        navigation of the page's main frame making its site one of the run's."""
        request = params.get("request") or {}
        site = gate.site_of(str(request.get("url") or ""))
        get = str(request.get("method") or "GET").upper() in ("GET", "HEAD", "OPTIONS")
        top = params.get("resourceType") == "Document" and params.get("frameId") == self._frame
        hold = self._hold(params, self._carries(params), site, get, top)
        if hold is None:
            return
        if hold and top:
            # The page cannot be read while its own navigation waits: that card comes at once.
            self._navs.append((asyncio.create_task(self._held_nav(params, hold)), params))
            return
        if hold:
            self._holding.append((params, hold))
            return
        if top:
            self.sites.add(site)
            self._address = str(request.get("url") or "")
            # What was typed and now goes to its own site in the page's address has gone: a request of that
            # site carrying it later carries nothing new.
            for t in self.typed:
                if t["site"] == site and bears(texts_of(request), t["text"]):
                    t["went"] = True
        if self._noting and not get:
            # What went out while an act call ran, for its Noticed line.
            parts = urlsplit(str(request.get("url") or ""))
            self._went.append((f"{str(request.get('method')).upper()} {parts.hostname or ''}{parts.path}"[:120],
                               str(params.get("networkId") or "")))
        await self.tab.cdp("Fetch.continueRequest", {"requestId": params["requestId"]})

    def _hold(self, params: dict, carried: list[dict], site: str, get: bool, top: bool) -> list[dict] | None:
        """What a paused request is held for, the entries its card is about ([] when it goes on), or None when it
        waits beside a confirmed press."""
        request = params.get("request") or {}
        press = self._pressing
        sends = not get and params.get("resourceType") != "Ping"
        if press is not None and not (carried and site != press["site"]):
            # A confirmed press: its own site's requests go, a post only once one is seen carrying the card's
            # words; the others wait for the press to end beside it.
            if not get and press["said"] and not press["matched"]:
                if not bears(texts_of(request), press["said"]):
                    press["aside"].append(params)
                    return None
                press["matched"] = True
            return []
        if not top and only_reads(request, carried, params.get("resourceType") == "Ping"):
            return []
        if not top and not carried and self._own(site) and (beacon(request) or self._works_on_theirs(request, site)):
            # The page's own telemetry to its own site, or the page working on the person's own words there (a
            # translation, a search), with nothing typed in it beyond those words: no one's act, let through by rule
            # with no reviewer. A press is judged by its control before it is made, whatever its requests are called.
            return []
        if self._watching is not None and sends and self._submits(request):
            return [self._watching, *carried]
        if carried:
            return carried
        if self._choice is not None and sends:
            return [self._choice]
        if top and site not in self.sites and time.monotonic() > self._follow_until:
            # The page going by itself to a site that is not the run's.
            return [{"leave": True, "field": "", "text": ""}]
        return []
    def _own(self, site: str) -> bool:
        """The site of the page the run is on, when it is not a sensitive one (acting.sensitive)."""
        from .. import acting
        return site == gate.site_of(self._address) and not acting.sensitive(site)

    def _works_on_theirs(self, request: dict, site: str) -> bool:
        """A request, not a DELETE, that takes the person's own words typed on this site (`asked`) to it."""
        texts = texts_of(request)
        return str(request.get("method") or "").upper() != "DELETE" and any(
            t.get("asked") and t["site"] == site and bears(texts, t["text"]) for t in self.typed)

    def _carries(self, params: dict) -> list[dict]:
        """The typed entries a paused request carries, in its body or address: a GET only when it goes to
        another site than the one the text was typed on (a new tab, a fetch). The person's own words typed on a site
        they named (`asked`) are carried only to another site."""
        request = params.get("request") or {}
        if not self.typed:
            return []
        get = str(request.get("method") or "GET").upper() in ("GET", "HEAD", "OPTIONS")
        site = gate.site_of(str(request.get("url") or ""))
        if not get and request.get("hasPostData") and not request.get("postData") and not request.get("postDataEntries"):
            # A body the browser would not show: whatever was typed may be in it.
            return [t for t in self.typed if not (t.get("asked") and site == t["site"])]
        texts = texts_of(request)
        # Typed a key at a time, a field's text is sent as it grows: to another site, any start of it is carried.
        starts = {squeeze(x) for x in texts if squeeze(x)}
        return [t for t in self.typed if not ((get or t.get("went") or t.get("asked")) and site == t["site"])
                and (bears(texts, t["text"]) or (site != t["site"] and any(squeeze(t["text"]).startswith(x)
                                                                           for x in starts)))]

    def _submits(self, request: dict) -> bool:
        """A request that leaves on a watched press and is its act: a DELETE, or one to the page's own site or its
        form's (a save, a submission). The page's monitoring and reads to its other hosts on the same click are not
        the press's act."""
        if str(request.get("method") or "").upper() == "DELETE":
            return True
        return gate.site_of(str(request.get("url") or "")) in self._watching["sites"]

    async def _held_cards(self) -> dict:
        """The requests held since the last look, each by its act's one card: {"status", "line", "kind"};
        "declined" when the person said no (that request is dropped), "waiting" when the card waits for an
        answer. The requests one act holds (a press's submission and its retries, what a form saves twice) go as
        its first card was answered (`kept`); a press confirmed meanwhile never lets out what was held before it."""
        lines, ended = [], {"status": "ok", "kind": ""}
        while self._holding:
            # It leaves the list only once answered: if this step breaks off, close() still drops it.
            held = await self._held_card(*self._holding[0])
            self._holding.pop(0)
            lines.append(held["line"])
            if held["status"] != "ok":
                ended = {k: held[k] for k in ("status", "kind", "result") if k in held}
        return {**ended, "line": "\n".join(lines)}

    async def _held_nav(self, params: dict, carried: list[dict]) -> None:
        """The page's own navigation, held: its card at once, its outcome among what the page did, for the next
        line."""
        held = await self._held_card(params, carried, top=True)
        self._told.append(held["line"])
        if held["status"] in ("declined", "waiting"):
            self._turned = {k: held[k] for k in ("status", "kind", "result") if k in held}

    async def _held_card(self, params: dict, carried: list[dict], top: bool = False) -> dict:
        """The card for one held request, and the request let go on yes, dropped on no: {"status", "line",
        "kind"}. A navigation of the page itself said no to is answered 204, so the page stays as it was."""
        first = carried[0]
        card, what = await self._card_of_held(params.get("request") or {}, carried, top)
        act = card["act"]
        kept = self.kept.get(act)
        decision, passed, does = await self._held_decided(card, params.get("request") or {}, carried, kept)
        card["kind"] = reading(card["kind"], does)
        if decision == "read":
            await self._drop(params, top)
            return {"status": "failed", "kind": card["kind"], "line": f"[read-only] {what[1]}; the person set the "
                    f"browser to read only, so it was dropped"}
        if decision == "turned" or (kept or {}).get("turned"):
            self.kept[act] = {"turned": True, "line": passed, "does": does}
            await self._drop(params, top)
            return {"status": "declined", "kind": card["kind"], "line": f"[declined] {what[1]}; {passed}"}
        answer = kept if kept is not None else {"yes": True} if decision == "go" else None
        if answer is None:
            try:
                card["picture"] = await asyncio.wait_for(self.page.screenshot(), 3)
            except Exception:
                card["picture"] = ""
            answer = await self.ask(card)
            if answer is not None and not answer.get("waiting"):
                self.kept[act] = {**answer, "does": does}
        elif decision == "go":
            self.kept[act] = {"yes": True, "line": passed, "does": does}
        if answer and answer.get("waiting"):
            # Nobody answered in time: the card waits, and so does the act; nothing of it goes meanwhile.
            await self._drop(params, top)
            return {"status": "waiting", "kind": card["kind"], "result": answer["waiting"],
                    "line": f"[waiting] {what[1]}; the card waits for the person's answer, so it was held back"}
        if answer and answer.get("yes"):
            if first.get("leave"):
                self.sites.add(card["site"])
                self._follow_until = time.monotonic() + FOLLOW_S
            else:
                self.confirmed = True
            # A bare submission the person let out took all that was typed for it.
            for t in self.typed if first.get("watch") else carried:
                t["out"] = True
            await self.tab.cdp("Fetch.continueRequest", {"requestId": params["requestId"]})
            how = (passed or "the person's answer to this act before") if decision == "kept" else (
                passed if decision == "go" else "the person said yes on a card")
            return {"status": "ok", "kind": card["kind"], "line": f"[{'went' if first.get('leave') else 'held'}] "
                    f"{what[0]}: {how}, and it went"}
        await self._drop(params, top)
        for t in self.typed if first.get("watch") else carried:
            t["no"] = True
        return {"status": "declined", "kind": card["kind"], "line": f"[declined] {what[1]}; the person "
                f"{'said no' if answer else 'did not answer'}, so it was dropped"}

    async def _card_of_held(self, request: dict, carried: list[dict], top: bool) -> tuple[dict, tuple[str, str]]:
        """The card for a held request, with the act it belongs to (one question for it, and the answer kept for
        the turn), and its line as (it went, it would have gone)."""
        url = str(request.get("url") or "")
        site = gate.site_of(url)
        first = carried[0]
        chose = any(c.get("choice") for c in carried)
        label = f"{request.get('method', 'POST')} {urlsplit(url).path}"[:120]
        try:
            # A page opening a window to another site can stall its own scripts while that is held, and no page
            # can be read while its own navigation waits.
            shown_at = await asyncio.to_thread(lambda: self.tab.url) if top else await asyncio.wait_for(
                self._url(), HEAR_S * 3)
        except (asyncio.TimeoutError, RuntimeError):
            shown_at = ""
        card = {"id": secrets.token_urlsafe(8), "kind": "press" if chose else "submit", "site": site,
                "url": shown_at, "button": SAID[self.lang]["chose" if chose else "held"],
                # The fields typed into, then the request's other short values (a recipient the page put in it),
                # so the card reads back what goes, not only the words typed.
                "to": "、".join(dict.fromkeys([c["field"] for c in carried if c["field"]] + [
                    v for v in leaves_of(request)[2] if v and len(v) <= 40
                    and v not in {c["text"].strip() for c in carried}][:4]))[:120],
                "text": "\n".join(dict.fromkeys(c["text"] for c in carried if c["text"]))[:2000],
                "label": label, "skippable": False,
                "why": "the page itself sends what was typed (it saves by itself, for example when a field loses "
                       "the focus)"}
        if first.get("leave"):
            card.update(kind="leave", to="", text=clip(url, 300), button="", label="",
                        why="the page goes to a site that is not one of this run's")
            what = (f"the page went on to {site}, another site", f"the page tried to go on to {site}, another site")
        elif first.get("watch"):
            # A press: the card says what pressing it sends, the form's fields as the person sees them; a press with
            # no fields is named by its button alone.
            card.update(kind="submit" if first["text"] else "press", button=first["button"], to="",
                        text=first["text"] or card["text"], why=f"pressing {first['button']!r} sends this ({label})")
            what = (f"pressing {first['button']!r} sent {label}", f"pressing {first['button']!r} would send {label}")
            if str(request.get("method") or "").upper() == "DELETE":
                # A DELETE deletes, whatever the button says: a delete's card, never the reviewer's.
                card.update(kind="delete", why=f"pressing {first['button']!r} sends a DELETE ({label})")
        else:
            what = (f"the page sent {card['text'][:60]!r} by itself ({label})",
                    f"the page tried to send {card['text'][:60]!r} by itself ({label})")
        if card["kind"] not in ("delete", "leave") and gate.hands_over(
                "\n".join(f"{c['field']}: {c['text']}" for c in carried if c["text"])):
            # What was typed holds an identity number, a home address or a bank account: handed over, costly.
            card["kind"] = "grant"
        card["act"] = ("held", card["kind"], site, card["button"] if first.get("watch") else card["text"])
        return card, what

    async def _held_decided(self, card: dict, request: dict, carried: list[dict],
                            kept: dict | None) -> tuple[str, str, str]:
        """_decided for a held request: the answer kept for its act, else the person's mode (and the reviewer)."""
        if kept is not None:
            return "kept", kept.get("line", ""), kept.get("does", "")
        site = card["site"]
        if not all(c.get("site", site) == site for c in carried):
            # What was typed on one site going to another is never left to the reviewer; going on to another site
            # with nothing typed carried is.
            return "ask", "", ""
        chose = any(c.get("choice") for c in carried)
        # One verdict an endpoint in this turn: the same act to the same site, method and path is never judged twice
        # with different outcomes, whatever ids and counters its body carries this time.
        url = str(request.get("url") or "")
        key = json.dumps(["held", card["kind"], site, str(request.get("method") or "GET").upper(), shape(url),
                          card["text"], card["button"], chose], ensure_ascii=False)
        return await self._decided(card["kind"], site, leaving(url) if carried[0].get(
            "leave") else {"text": card["text"], "page_says": card["button"], "request": summary_of(request),
                           "effects": ["the page saves the choice the moment it is made"] if chose else []}, key)

    async def _drop(self, params: dict, top: bool) -> None:
        """A held request that does not go: a navigation of the page answered 204 (nothing to show, the page stays
        as it was, what was typed in it too), any other failed."""
        if top:
            await self.tab.cdp("Fetch.fulfillRequest", {"requestId": params["requestId"], "responseCode": 204,
                                                       "responseHeaders": [], "body": ""})
        else:
            await self.tab.cdp("Fetch.failRequest", {"requestId": params["requestId"], "errorReason": "BlockedByClient"})

    async def let_go(self) -> None:
        """The person signs in: nothing of the run holds the page's requests until the next look. Those paused now
        go on, except one carrying what was typed, which is dropped (as at close)."""
        if self._paused is None or self._closed or self._released is not None:
            return
        self._released = self.tab._fetch
        await self._release_held()
        await self.tab.cdp("Fetch.disable", {})

    async def _release_held(self) -> None:
        """Every request held or still paused goes on, except one carrying what was typed, which is dropped."""
        while self._paused is not None and not self._paused.empty():
            params = self._paused.get_nowait()
            self._holding.append((params, self._carries(params)))
        for params, carried in self._holding:
            # A request the page dropped meanwhile is gone already.
            with contextlib.suppress(Exception):
                await self.tab.cdp("Fetch.failRequest" if carried else "Fetch.continueRequest",
                                   {"requestId": params["requestId"], **({"errorReason": "BlockedByClient"} if carried else {})})
        self._holding = []

    async def close(self, restore: bool = False) -> None:
        """The run is over. With `restore` (the person said no, or stopped it) each field typed into and never
        let out gets back what it held, while its requests are still held: a timer or a beacon of the page
        cannot send it later; so does a field whose sending the person refused on a card, however the run
        ended. Then what is still held is dropped, and the page's requests are no longer looked at."""
        # A navigation of the page still waiting for its card stays where it was (no page is read while it waits).
        for task, params in self._navs:
            if not task.done():
                task.cancel()
                with contextlib.suppress(Exception):
                    await self._drop(params, True)
        self._navs = []
        back = [t for t in self.typed if not t["out"] and (restore or t.get("no"))]
        if back and self._paused is not None:
            for t in back:
                try:
                    await self.page.on_node(t["node"], RESTORE_JS, [t.get("shows", t["text"]), t["before"]])
                except Exception:
                    logger.debug("[Agent] operate: a typed field was gone before it could be put back")
            await asyncio.sleep(HEAR_S)
        self._closed = True
        if self._drain is not None:
            self._drain.cancel()
        await self._release_held()
        if self._paused is not None:
            with contextlib.suppress(Exception):
                await self.tab.cdp("Page.setInterceptFileChooserDialog", {"enabled": False})
            with contextlib.suppress(Exception):
                await self.tab.cdp("Fetch.disable", {})
