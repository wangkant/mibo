"""How the character sees a page and acts in it: Chrome's accessibility tree, one
line per control with an id the model acts by, over any Tab's `cdp`.

From browser-use's browser_use/ax.py (MIT, see NOTICE), itself a port of Browser
Use Pi's ax.ts: the state print, the settle wait, the covered-target check, the
trusted press and release, insertText plus a real last key, and the value read
back. Changed for Mibo: CDP goes through `Tab.cdp(method, params)` (no daemon,
no event thread; the settle wait watches the page alone), secret fields print as
`[secret]` with their value hidden and are never typed into, and FACTS_JS reads
what the consent gate (gate.py) needs of a target: its form, the text box it
belongs to, the heading over it and any money amount by it.

Ours on top, for what a text-only model could not see or do: one DOM snapshot
a look finds what is shown as clickable though the tree names no control there
(a row, a menu entry, a date in a calendar: a pointer cursor, the outermost of
its kind), boxes that scroll by themselves (a virtual conversation list) and
the tooltip, icon or class of a control with no name; Playwright's ways for
ordinary controls (date, time, colour and range fields set by value, several options of a list chosen at once,
the click point on the first box of an element) and the rest of Playwright MCP's actions (keys with modifiers,
typing that adds to a field, double and right clicks, a drag from one element onto another with the browser's own
drag and drop caught as Playwright's crDragDrop does, waiting until words show or go); an element can be found by the
words it shows; scrolling goes inside a box and on until some words show; the
settle wait holds while the page says it is busy; a control drawn again since
the look is found again by its role, name and the text before it; and a ring
stays round the control a card asks about.

The whole page, not the window: the state holds the whole tree when it fits;
when it does not, its top, its end and what stands on the screen now, with
how many lines are cut above and below, so scrolling shows the rest (as
browser-use shows what is in view). A table's cells stay apart by `|`.
`whole` gives every word of the page for a question (browser-use's and
Stagehand's extract), the page taken to its end, a list that draws only the
rows in view read step by step; `seek` scrolls to a row not drawn yet.

A frame from another site runs in a process of its own, which the page's
session does not reach: as Playwright and Stagehand do, each is read in its own
session (Tab.frames, from Target.setAutoAttach with flatten) and printed where
it sits, its ids numbered apart (FRAME_IDS) so an action goes to its session.
Payment, sign-in and bot-check frames are named and left to the person.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from typing import Any

from .pageact import Acting
from .pagejs import (
    ACTIVE_JS,
    AGAIN_JS,
    BOX_JS,
    FACTS_JS,
    HOLD_JS,
    INNER_JS,
    LOCATE_JS,
    PROBE_JS,
    SCREEN_JS,
    SECRET_EMPTY_JS,
    UNRING_JS,
    UP_JS,
    VALUE_JS,
    VISIBLE_JS,
)
from .pageprint import VALUE_MAX, Looking
from .pageread import Reading
from .pagewords import (
    CDP_TIMEOUT_MS,
    FRAME_IDS,
    SECRET_AUTOCOMPLETE,
    SECRET_LABEL,
    SECRET_SELECTOR,
    clip,
    fold,
    is_context_loss,
    norm,
    now,
    quote,
)

# The listeners that hear a press.
PRESS_EVENTS = re.compile(r"^(?:click|dblclick|auxclick|mouse(?:down|up)|pointer(?:down|up)|touch(?:start|end))$")


class Page(Looking, Reading, Acting):
    """The state print and id-based actions on one Tab. Ids are Chrome backendNodeIds, valid until the next look."""

    def __init__(self, tab):
        self.tab = tab
        # Role and name of every id in the last print, and which of them are secret.
        self.last: dict[int, tuple[str, str]] = {}
        self.secrets: set[int] = set()
        # A part of a clickable shown as a control of its own -> the clickable round it.
        self.outer: dict[int, int] = {}
        self.interactive = 0
        # The text line before each id (digits out: a live count moves), the print before this one, and every
        # line of the last print before it was cut (for `grep`).
        self.near: dict[int, str] = {}
        self.before: tuple[dict, dict] = ({}, {})
        self.lines: list[str] = []
        # Where in those lines each id's own line and the lines under it are ([start, end), for a look at one
        # part), and the stretches the print left out ([start, end)).
        self.spans: dict[int, tuple[int, int]] = {}
        self.cut: list[tuple[int, int]] = []
        # Prints made of this page so far: a look's snapshot number.
        self.looks = 0
        # The whole value of each field whose line shows only its start (for `grep`).
        self.values: dict[int, str] = {}
        # The app's own script world in the page, for the ring: (document, context id); the last document a
        # blank page was waited for on.
        self._world: tuple[Any, int] | None = None
        self._waited: Any = None
        # Frames from another site read in the last look: number -> {"session", "url", "owner"}, the owner being
        # its frame element as (session, id) in the document that holds it; each frame's number by its frame id,
        # kept across looks so its ids stay the same.
        self.frames: dict[int, dict] = {}
        self._numbers: dict[str, int] = {}
        # What a drag the browser caught carries (Input.dragIntercepted), and whether that event is heard yet.
        self._dragged: dict | None = None
        self._drag_heard = False

    async def cdp(self, method: str, **params: Any) -> dict:
        return await self.tab.cdp(method, params)

    async def _in(self, session: str, method: str, **params: Any) -> dict:
        """A DevTools command to the page ("") or to a frame from another site."""
        return await self.tab.cdp(method, params, session)

    def _node(self, ident: int) -> tuple[str, int]:
        """The session an id is in ("" for the page) and its id there."""
        k, local = divmod(ident, FRAME_IDS)
        return (self.frames[k]["session"] if k else ""), local

    def _id(self, session: str, local: int) -> int:
        return local + FRAME_IDS * next((k for k, f in self.frames.items() if f["session"] == session), 0)

    def frame_url(self, ident: int) -> str:
        """The address of the frame from another site an id is in; "" for one of the page's own."""
        k = ident // FRAME_IDS
        return self.frames[k]["url"] if k else ""

    # --- page probes

    async def _evaluate(self, fn: str, session: str = "") -> Any:
        r = await self._in(session, "Runtime.evaluate", expression=f"({fn})()", timeout=CDP_TIMEOUT_MS,
                           awaitPromise=True, returnByValue=True, userGesture=True)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text"))
        return (r.get("result") or {}).get("value")

    async def probe(self, session: str = "") -> dict:
        return await self._evaluate(PROBE_JS, session)

    async def settle(self, cap_ms: float = 3000, quiet_ms: float = 120, since: float = 0, session: str = "") -> dict:
        """Wait until the document (the page's, or a frame's from another site) is parsed and the DOM has been
        quiet for quiet_ms, at most cap_ms."""
        start, probe = now(), None
        limit = cap_ms
        while now() - start < limit:
            try:
                probe = await self.probe(session)
                if probe["ready"] == "loading":
                    limit = max(cap_ms, 6000)
                # The page says it is still answering (a lookup, a list coming): it is given up to 10 s.
                if probe.get("busy"):
                    limit = max(limit, 10_000)
                probe["idle"] = min(probe["idle"], now() - (since or start))
                if probe["ready"] != "loading" and probe["idle"] >= quiet_ms and not probe.get("busy"):
                    return {"why": "quiet", "probe": probe}
            except Exception as e:
                if not is_context_loss(e):
                    return {"why": "error"}
                probe = None
            await asyncio.sleep((max(20, quiet_ms - probe["idle"]) if probe and probe["ready"] != "loading" else 60) / 1000)
        return {"why": "cap", "probe": probe}

    async def visible_text(self, session: str = "") -> str:
        return await self._evaluate(VISIBLE_JS, session) or ""

    async def screen_text(self) -> str:
        return await self._evaluate(SCREEN_JS) or ""

    # --- one node

    async def on_node(self, ident: int, fn: str, argument: Any = None) -> Any:
        return await self._call_on(*self._node(ident), fn, argument)

    async def _call_on(self, session: str, local: int, fn: str, argument: Any = None) -> Any:
        obj = (await self._in(session, "DOM.resolveNode", backendNodeId=local))["object"]
        if not obj.get("objectId"):
            raise RuntimeError("Node unavailable.")
        try:
            r = await self._in(session, "Runtime.callFunctionOn", objectId=obj["objectId"], functionDeclaration=fn,
                               arguments=[{} if argument is None else {"value": argument}], returnByValue=True,
                               awaitPromise=True)
            if r.get("exceptionDetails"):
                d = (r["exceptionDetails"].get("exception") or {}).get("description")
                raise RuntimeError(("Node operation failed." if d is None else d).split("\n    at ")[0])
            return (r.get("result") or {}).get("value")
        finally:
            with contextlib.suppress(Exception):
                await self._in(session, "Runtime.releaseObject", objectId=obj["objectId"])

    async def _found(self, session: str, r: dict) -> int | None:
        """The id of the element a Runtime.evaluate in `session` gave back, or None."""
        obj = r.get("result") or {}
        if not obj.get("objectId"):
            return None
        try:
            local = (await self._in(session, "DOM.describeNode", objectId=obj["objectId"]))["node"].get("backendNodeId")
        finally:
            with contextlib.suppress(Exception):
                await self._in(session, "Runtime.releaseObject", objectId=obj["objectId"])
        return None if local is None else self._id(session, local)

    async def _offset(self, session: str) -> tuple[float, float]:
        """Where a frame from another site starts in the top page, through every frame it sits in."""
        x = y = 0.0
        while session:
            where, owner = next(f["owner"] for f in self.frames.values() if f["session"] == session)
            at = await self._call_on(where, owner, INNER_JS)
            x, y, session = x + at["x"], y + at["y"], where
        return x, y

    async def focus(self, ident: int) -> None:
        session, local = self._node(ident)
        await self._in(session, "DOM.focus", backendNodeId=local)

    async def facts(self, ident: int) -> dict:
        """FACTS_JS of an element; a part of a clickable shown on its own carries the clickable's class too, as the
        press is the clickable's."""
        facts = await self.on_node(ident, FACTS_JS) or {}
        if ident in self.outer:
            whole = await self.on_node(self.outer[ident], FACTS_JS) or {}
            facts["classes"] = f"{facts.get('classes', '')} {whole.get('classes', '')}".strip()
        return facts

    async def _up(self, session: str, local: int, group: str) -> list[str]:
        """Remote objects of an element and the elements over it, out through shadow roots, up to its document's
        body (not crossing into the frame that holds it), at most 30; released with `group`."""
        obj = (await self._in(session, "DOM.resolveNode", backendNodeId=local, objectGroup=group))["object"]
        chain = await self._in(session, "Runtime.callFunctionOn", objectId=obj["objectId"], objectGroup=group,
                               functionDeclaration=UP_JS, returnByValue=False)
        props = await self._in(session, "Runtime.getProperties", objectId=chain["result"]["objectId"],
                               ownProperties=True)
        return [p["value"]["objectId"] for p in sorted((p for p in props["result"] if p["name"].isdigit()),
                                                       key=lambda p: int(p["name"]))]

    async def under(self, x: float, y: float) -> tuple[int | None, bool, list[int]]:
        """What a press at a point of the view goes down on: the element there (None on nothing), whether it is in a
        frame from another site, and every element the last look lists from it up to its document's body, out
        through shadow roots, the nearest first."""
        hit = (await self.cdp("DOM.getNodeForLocation", x=int(x), y=int(y), includeUserAgentShadowDOM=False)
               ).get("backendNodeId")
        if not hit:
            return None, False, []
        if (await self.cdp("DOM.describeNode", backendNodeId=hit))["node"].get("nodeName") in ("IFRAME", "FRAME",
                                                                                                 "OBJECT", "EMBED"):
            # Its document is not this one's: a frame from another site.
            return hit, True, []
        # A browser that keeps another site's frame in the page's own process answers with the element inside it:
        # the same press, so the same answer, by whose document the element is in.
        if await self._call_on("", hit, "function(){return this.ownerDocument.location.origin}") != await self._evaluate(
                "() => location.origin"):
            return hit, True, []
        group = "pa-up"
        listed = []
        try:
            for obj in await self._up("", hit, group):
                local = (await self.cdp("DOM.describeNode", objectId=obj))["node"].get("backendNodeId")
                if local in self.last:
                    listed.append(local)
        finally:
            await self.cdp("Runtime.releaseObjectGroup", objectGroup=group)
        return hit, False, listed

    async def handled(self, ident: int) -> bool:
        """Whether a press on the element is heard: a click, pointer, mouse or touch listener on it or on an element
        over it below the body (DOMDebugger.getEventListeners, as browser-use finds controls by their listeners)."""
        session, local = self._node(ident)
        group = "pa-heard"
        try:
            for obj in await self._up(session, local, group):
                listeners = (await self._in(session, "DOMDebugger.getEventListeners", objectId=obj))["listeners"]
                if any(PRESS_EVENTS.match(heard["type"]) for heard in listeners):
                    return True
        finally:
            await self._in(session, "Runtime.releaseObjectGroup", objectGroup=group)
        return False

    async def value(self, ident: int) -> str:
        return str(await self.on_node(ident, VALUE_JS) or "")

    async def secret_unfilled(self, ident: int) -> str | None:
        """The form of `ident` holds a secret field still empty (a password, a card number, a code): that field
        gets the focus, for the person to type into, and its label comes back; None when there is none."""
        return await self.on_node(ident, SECRET_EMPTY_JS, SECRET_SELECTOR)

    async def active(self) -> int | None:
        """The id of the element with focus, inside a frame from another site when the focus is there; or None."""
        session = ""
        while True:
            ident = await self._found(session, await self._in(session, "Runtime.evaluate", expression=ACTIVE_JS))
            inner = next((f["session"] for f in self.frames.values() if ident is not None
                          and f["owner"] == (session, self._node(ident)[1])), None)
            if inner is None:
                return ident
            session = inner

    async def secret(self, ident: int) -> bool:
        """A field never typed into: by its type, autocomplete, or its own words (read off the DOM each time)."""
        session, local = self._node(ident)
        node = (await self._in(session, "DOM.describeNode", backendNodeId=local))["node"]
        attrs = node.get("attributes") or []
        at = {attrs[i - 1].lower(): attrs[i] for i in range(1, len(attrs), 2)}
        if at.get("type", "").lower() == "password" or SECRET_AUTOCOMPLETE.match(at.get("autocomplete", "")):
            return True
        words = " ".join(at.get(k, "") for k in ("name", "id", "placeholder", "aria-label", "title"))
        return ident in self.secrets or bool(SECRET_LABEL.search(f"{words} {self.last.get(ident, ('', ''))[1]}"))

    def describe(self, ident: int) -> str:
        n = self.last.get(ident)
        if not n:
            return f"[{ident}]"
        return f"[{ident}] {n[0]}" + (f' "{clip(n[1], 60)}"' if n[1] else "")

    def grep(self, words: str) -> str:
        """The lines of the last look (before it was cut) that hold these words, each with the line before it and
        the two after it (a table row whose name is a link goes on in the next line); and in a field's whole
        value, the part around them."""
        want = [w for w in fold(words).split() if w]
        hits: list[str] = []
        for i, line in enumerate(self.lines):
            if want and all(w in fold(line) for w in want):
                hits += [x for x in self.lines[max(0, i - 1):i + 3] if x not in hits]
        for ident, value in self.values.items():
            if not want or all(w in fold(value[:VALUE_MAX]) for w in want):
                continue
            at = fold(value).find(want[0]) if all(w in fold(value) for w in want) else -1
            if at >= 0:
                hits.append(f"{self.describe(ident)} = …{quote(value[max(0, at - 150):at + 250])}…")
        return clip("\n".join(hits), 1500)

    async def locate(self, words: str) -> int | None:
        """The element showing these words (see LOCATE_JS), in the page or else in a frame from another site
        read in the last look, as an id an action takes; it joins the last look as role "text" so the gate and
        the card can name it."""
        ident = None
        for session in ["", *(f["session"] for f in self.frames.values())]:
            ident = await self._found(session, await self._in(session, "Runtime.evaluate",
                                                               expression=f"({LOCATE_JS})({json.dumps(words)})"))
            if ident is not None:
                break
        if ident is not None and ident not in self.last:
            self.last[ident] = ("text", clip(norm(words), 80))
        return ident

    async def alive(self, ident: int) -> bool:
        try:
            return bool(await self.on_node(ident, "function(){return (this.nodeType===1?this:this.parentElement)"
                                                  ".isConnected;}"))
        except Exception:
            return False

    async def relocate(self, ident: int) -> int | None:
        """A control the page drew again since the look (a live list redraws every second): a fresh look, and
        the one control there with the same role and name, or among several the one after the same text."""
        role, name = self.last.get(ident) or self.before[0].get(ident) or ("", "")
        near = self.near.get(ident, self.before[1].get(ident, ""))
        if not role:
            return None
        await self.state()
        same = [i for i, (r, n) in self.last.items() if r == role and fold(n) == fold(name)]
        if len(same) > 1:
            same = [i for i in same if self.near.get(i, "") == near] or same[:0]
        return same[0] if len(same) == 1 else None

    async def again(self, ident: int, press: bool = False) -> int | None:
        """`ident` drawn anew since the look, found in one step in the page (AGAIN_JS) by its name and the text
        before it; the new id joins the last look. With `press` it is pressed in that same step. None when not
        exactly one is found."""
        role, name = self.last.get(ident) or self.before[0].get(ident) or ("", "")
        near = self.near.get(ident, self.before[1].get(ident, ""))
        if not name:
            return None
        session = self._node(ident)[0]
        found = await self._found(session, await self._in(
            session, "Runtime.evaluate", userGesture=True,
            expression=f"({AGAIN_JS})({json.dumps(name)}, {json.dumps(near)}, {json.dumps(press)})"))
        if found is not None:
            self.last[found], self.near[found] = (role, name), near
        return found

    async def box(self, ident: int) -> dict:
        b = await self.on_node(ident, BOX_JS)
        x, y = await self._offset(self._node(ident)[0])
        return {**b, "x": b["x"] + x, "y": b["y"] + y}

    async def _ring_world(self) -> int:
        """The app's own script world in the page now, made once per document."""
        probe = await self.probe()
        if self._world is None or self._world[0] != probe.get("doc"):
            frame = (await self.cdp("Page.getFrameTree"))["frameTree"]["frame"]["id"]
            world = await self.cdp("Page.createIsolatedWorld", frameId=frame, worldName="mibo-ring")
            self._world = (probe.get("doc"), world["executionContextId"])
        return self._world[1]

    async def hold_ring(self, ident: int | None) -> None:
        """A ring that stays round `ident` while a card waits on it, in the app's own world; None takes it away.
        Only for the person watching: a page that will not take it is left as it is."""
        try:
            world = await self._ring_world()
            if ident is None:
                await self.cdp("Runtime.evaluate", expression=UNRING_JS, contextId=world)
                return
            session, local = self._node(ident)
            while session:
                # In a frame from another site: the ring goes round the frame that holds it, in the page.
                session, local = next(f["owner"] for f in self.frames.values() if f["session"] == session)
            obj = (await self.cdp("DOM.resolveNode", backendNodeId=local, executionContextId=world))["object"]
            await self.cdp("Runtime.callFunctionOn", objectId=obj["objectId"], functionDeclaration=HOLD_JS)
            await self.cdp("Runtime.releaseObject", objectId=obj["objectId"])
        except Exception:
            self._world = None

    async def screenshot(self) -> str:
        """The viewport as a small JPEG, base64, for the card."""
        metrics = await self.cdp("Page.getLayoutMetrics")
        view = metrics.get("cssVisualViewport") or metrics.get("visualViewport") or {}
        wide, high = float(view.get("clientWidth") or 1280), float(view.get("clientHeight") or 800)
        return (await self.cdp("Page.captureScreenshot", format="jpeg", quality=60,
                        clip={"x": float(view.get("pageX") or 0), "y": float(view.get("pageY") or 0),
                              "width": wide, "height": high, "scale": min(1.0, 720 / max(wide, 1))}))["data"]
