"""The actions of pageops.Page, as Playwright and Playwright MCP take them (NOTICE): a click after the actionability
checks with a trusted press and release, typing by insertText and a real last key, a value set straight into a date,
time, colour or range field, keys and chords, a wheel over a box, a hover, a wait for words, a drag with the
browser's own drag and drop caught, a selection, going to an address and back. Each runs through `_act`, which
says in one line what changed. A mixin of pageops.Page: it uses the page's own probes and node calls."""
from __future__ import annotations

import asyncio
import contextlib
import math
import re
import time

from .pageinput import KEYS, SIGNS, as_value, chord
from .pagejs import (
    CENTER_JS,
    END_JS,
    HIT_JS,
    KIND_JS,
    MOVED_JS,
    PLACE_JS,
    POINT_JS,
    SCROLLER_JS,
    SELECT_JS,
    SELECT_TEXT_JS,
    SET_JS,
    STABLE_JS,
)
from .pageread import MORE_S
from .pagewords import SET_BY_VALUE, clip, fold, norm, now, quote, well_formed

# How far `scroll ... until` goes, in wheels.
UNTIL_WHEELS = 30

# How long `wait` with `until` or `gone` waits for the words (Playwright MCP's wait_for), seconds.
WAIT_S = 15.0
# Mouse moves a drag takes from one control to the other, so a list that follows the mouse sees it go by.
DRAG_STEPS = 8
# Playwright's actionability (NOTICE): a control not yet visible, stable, enabled or free to take the click is tried
# again after these waits (its retry ladder, the last repeating) until ACTION_S have gone, as its default action
# timeout in Playwright MCP.
ACTION_S = 5.0
ACTION_WAITS = (0.0, 0.02, 0.1, 0.1, 0.5)
NOT_YET = re.compile(r"Target (hidden|disabled|covered|outside viewport|not stable)")


class Refused(Exception):
    """An action the page operations will not do; its text goes back to the loop as is."""


def _moved(was: dict | None, stood: dict | None, after: dict | None, stands: dict | None) -> str:
    """Where a dragged item went: its place among its own (PLACE_JS) and on the page, before and after."""
    if after is None:
        return ""
    dx, dy = (round(stands["x"] - stood["x"]), round(stands["y"] - stood["y"])) if stands else (0, 0)
    if after == was:
        return f"; it moved {dx},{dy} on the page" if max(abs(dx), abs(dy)) > 2 else "; it did not move"
    if after["before"]:
        return f"; it now comes after {quote(after['before'])}"
    return f"; it now comes first, before {quote(after['after'])}"


class Acting:
    """The actions of pageops.Page."""

    async def _point(self, ident: int, editable_cover: bool = False) -> dict:
        """Playwright's actionability checks before a pointer action (NOTICE): attached, visible, stable over two
        frames, enabled and receiving the events at its point, tried again on its retry ladder (ACTION_WAITS)
        until ACTION_S when one is not yet so. The point, unobstructed, in the top page; else raises why not."""
        began, tries = time.monotonic(), 0
        while True:
            try:
                return await self._point_once(ident, editable_cover)
            except RuntimeError as error:
                if not NOT_YET.search(str(error)) or time.monotonic() - began > ACTION_S:
                    raise
            await asyncio.sleep(ACTION_WAITS[min(tries, len(ACTION_WAITS) - 1)])
            tries += 1

    async def _point_once(self, ident: int, editable_cover: bool = False) -> dict:
        """Scroll into view and return an unobstructed centre point in the top page, or raise why not."""
        session, local = self._node(ident)
        frame = session
        while frame:
            # The frames it sits in come into view first.
            frame, owner = next(f["owner"] for f in self.frames.values() if f["session"] == frame)
            with contextlib.suppress(Exception):
                await self._in(frame, "DOM.scrollIntoViewIfNeeded", backendNodeId=owner)
        with contextlib.suppress(Exception):
            await self._in(session, "DOM.scrollIntoViewIfNeeded", backendNodeId=local)
        try:
            await self.on_node(ident, STABLE_JS)
            p = await self.on_node(ident, POINT_JS, editable_cover)
        except RuntimeError as error:
            if "outside viewport" not in str(error):
                raise
            # Still out of the window after the browser's own scroll (inside a box that clips it, a row of a
            # carousel): brought to the middle, as a person scrolls to it.
            await self.on_node(ident, CENTER_JS)
            p = await self.on_node(ident, POINT_JS, editable_cover)
        if p["covered"]:
            try:
                await self.on_node(ident, CENTER_JS)
                p = await self.on_node(ident, POINT_JS, editable_cover)
            except Exception:
                pass
        if p["covered"]:
            raise RuntimeError("Target covered by another element; nothing was clicked")
        x, y = await self._offset(session)
        return {**p, "x": p["x"] + x, "y": p["y"] + y}

    async def _click_at(self, x: float, y: float, modifiers: int = 0, button: str = "left", count: int = 1) -> None:
        if not all(math.isfinite(v) for v in (x, y)):
            raise ValueError("Coordinates must be finite.")
        # A double click is two presses, the second counted as such (Playwright's clickCount).
        for n in range(1, count + 1):
            await self.cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=n,
                           modifiers=modifiers)
            await self.cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=n,
                           modifiers=modifiers)

    async def _act(self, op: str, ident: int | None, body) -> str:
        """Runs one action and returns one line: navigated to <url> / page changed / no change. An action in a
        frame from another site counts what changed in that frame too."""
        session = self._node(ident)[0] if ident is not None else ""
        try:
            before = await self.probe()
        except Exception:
            before = None
        try:
            inner = await self.probe(session) if session else None
        except Exception:
            inner = None
        what = self.describe(ident) if ident is not None else ""
        try:
            detail = await body()
        except Refused:
            raise
        except Exception as e:
            return well_formed(f"[failed] {op} {what}: {e}")
        began = now()
        moved = await self.settle(since=began, session=session) if session else {}
        settled = await self.settle(since=began)
        change = await self.change(before, settled.get('probe'))
        if change == "no change" and inner and (moved.get("probe") or {}).get("n", inner["n"]) != inner["n"]:
            change = "page changed"
        return well_formed(f"[ok] {op} {what}{detail} -> {change}")

    async def change(self, before: dict | None, after: dict | None = None) -> str:
        if after is None:
            try:
                after = await self.probe()
            except Exception:
                after = None
        if not before or not after:
            return "page changed"
        if after["doc"] != before["doc"]:
            return f"navigated to {after['url']}"
        if after["url"] != before["url"]:
            # The same document at another address (a fragment, the page's own routing): its refs still hold.
            return f"page changed; the address is now {after['url']}"
        return "page changed" if after["n"] != before["n"] else "no change"

    async def click_again(self, ident: int) -> str:
        """A click on a control the page keeps drawing anew: found and pressed in one step (`again`), so the
        press cannot land on another row that moved under the pointer."""
        async def body() -> str:
            if await self.again(ident, press=True) is None:
                raise RuntimeError("it was drawn anew and could not be found again; nothing was clicked")
            return " (drawn anew since the look: pressed where it is now)"
        return await self._act("click", ident, body)

    async def click(self, ident: int, how: str = "", x: float | None = None, y: float | None = None) -> str:
        """A click; `how` "double" for a double click, "right" for the right button (the page's own menu); with x, y
        that far from the element's top left (Playwright's click position, checked as `at` does)."""
        async def body() -> str:
            if x is not None:
                p = await self.at(ident, x, y)
                await self._click_at(p["x"], p["y"], 0, "right" if how == "right" else "left",
                                     2 if how == "double" else 1)
                return f" at {round(x)},{round(y)} from its top left"
            try:
                p = await self._point(ident)
            except Exception:
                if await self.alive(ident):
                    raise
                fresh = await self.again(ident, press=not how)
                if fresh is None:
                    raise
                if not how:
                    # Drawn anew between the look and now: found and pressed in one step.
                    return " (drawn anew since the look: pressed where it is now)"
                p = await self._point(fresh)
            # Ctrl (2) adds an option to a list where several can be chosen, as a person does.
            await self._click_at(p["x"], p["y"], 2 if p["multi"] and not how else 0, "right" if how == "right" else "left",
                                 2 if how == "double" else 1)
            return ""
        return await self._act(f"{how} click".strip(), ident, body)

    async def at(self, ident: int | None, x: float | None = None, y: float | None = None, press: bool = True) -> dict:
        """A point for the pointer in the top page's view, as Playwright takes one: an id alone is its centre after
        the actionability checks (_point); an id with x, y is that far from its top left (Playwright's click
        `position`), scrolled into view; x, y alone are a point of the view as a picture of it shows. A point the
        button goes down on (`press`), given from an id, must fall on that element or a part of it. {"x", "y"};
        raises why it cannot land."""
        if ident is not None and x is None and press:
            return await self._point(ident)
        if ident is not None and x is None:
            # Where something is let go: its middle, whatever is drawn over it (a frame with no fill).
            b = await self.box(ident)
            x, y = b["w"] / 2, b["h"] / 2
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
            raise RuntimeError("a point needs x and y as numbers")
        if ident is not None:
            session, local = self._node(ident)
            with contextlib.suppress(Exception):
                await self._in(session, "DOM.scrollIntoViewIfNeeded", backendNodeId=local,
                               rect={"x": x, "y": y, "width": 1, "height": 1})
            if press:
                hit = await self.on_node(ident, HIT_JS, {"x": x, "y": y})
                if not hit["on"]:
                    raise RuntimeError(f"Target covered: {round(x)},{round(y)} from the top left of "
                                       f"{self.describe(ident)} falls on {hit['hit'] or 'nothing'}")
            b = await self.box(ident)
            x, y = b["x"] + x, b["y"] + y
        view = (await self.cdp("Page.getLayoutMetrics")).get("cssVisualViewport") or {}
        wide, high = float(view.get("clientWidth") or 0), float(view.get("clientHeight") or 0)
        if not (0 <= x < wide and 0 <= y < high):
            raise RuntimeError(f"{round(x)},{round(y)} is outside the view, which is {round(wide)}x{round(high)}: "
                               f"give the point from the top left of a ref, which is scrolled to, or scroll first")
        return {"x": x, "y": y}

    async def click_point(self, x: float, y: float) -> str:
        """A click on a point of the view as a picture shows it (a canvas has no parts to name)."""
        async def body() -> str:
            p = await self.at(None, x, y)
            await self._click_at(p["x"], p["y"])
            return f" at {round(x)},{round(y)}"
        return await self._act("click", None, body)

    async def _refuse_secret(self, ident: int) -> None:
        """Refused for a secret field: it is for the person to fill."""
        if await self.secret(ident):
            raise Refused(f"[refused] {self.describe(ident)} is a secret field (password, payment or code): "
                          f"it is for the person to fill")

    async def select_text(self, ident: int, words: str = "") -> str:
        """Playwright's selectText: the element's text selected, or only `words` in it; never in a secret field
        (Refused). Nothing goes to the clipboard."""
        await self._refuse_secret(ident)

        async def body() -> str:
            await self._point(ident, True)
            got = await self.on_node(ident, SELECT_TEXT_JS, words)
            if got is None:
                raise RuntimeError(f"it does not show {quote(clip(words, 60))}")
            return f" = {quote(clip(got, 80))}" + (f" ({len(got)} characters)" if len(got) > 80 else "")
        return await self._act("select", ident, body)

    async def type(self, ident: int, text: str, append: bool = False) -> str:
        """Replace the field's text with `text` (with `append`, add it at the end of what the field holds): a list's
        option (several, commas between, where several can be chosen), a date, time, colour or range field's value,
        else typed keys; never into a secret field (Refused)."""
        await self._refuse_secret(ident)

        async def body() -> str:
            kind = await self.on_node(ident, KIND_JS)
            if kind["tag"] == "SELECT":
                return f" = {quote(await self.on_node(ident, SELECT_JS, text))}"
            if kind["tag"] == "INPUT" and kind["type"] in SET_BY_VALUE:
                return await self._set_value(ident, kind, text)
            await self._type_keys(ident, text, append)
            try:
                actual = await self.value(ident)
            except Exception:
                actual = None
            return (f" {'+=' if append else '='} {quote(clip(text, 60))}"
                    + (f" (field now shows {quote(clip(actual, 60) if not append or len(actual) <= 60 else '…' + actual[-60:])})"
                       if actual is not None and actual != text else "")
                    + (" — it did not take the text: a field like this is set by its picker or list; click it"
                       if actual is not None and text.strip() and fold(text).strip() not in fold(actual) else ""))
        return await self._act("type", ident, body)

    async def _set_value(self, ident: int, kind: dict, text: str) -> str:
        """A date, time, colour or range field: its value set straight, as Playwright fills it, from what was
        written in the form the field takes (as_value)."""
        form = SET_BY_VALUE[kind["type"]]
        if kind["type"] == "range":
            form = f"a number from {kind['min'] or 0} to {kind['max'] or 100}"
        want = as_value(kind, text)
        got = await self.on_node(ident, SET_JS, want)
        if got is None:
            raise RuntimeError(f"it does not take {quote(clip(text, 40))}; type it as {form}")
        return (f" = {quote(got)}" + (f" (from {quote(clip(text, 40))})" if want != norm(text) else "")
                + (f" (it takes {form})" if got != want else ""))

    async def _type_keys(self, ident: int, text: str, append: bool) -> None:
        """The field clicked, its text selected (or the caret put at its end), then the text by insertText and its
        last character as a real key; Refused when the click moved the focus to another field."""
        p = await self._point(ident, True)
        await self._click_at(p["x"], p["y"])
        try:
            moved = bool(await self.on_node(ident, MOVED_JS))
        except Exception:
            moved = False
        if moved:
            raise Refused(f"[refused] typing into {self.describe(ident)} moved to another field; look again")
        with contextlib.suppress(Exception):
            await self.focus(ident)
        if append:
            await self.on_node(ident, END_JS)
        else:
            a = {"key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "modifiers": 2}
            await self.cdp("Input.dispatchKeyEvent", type="rawKeyDown", **a, commands=["selectAll"])
            await self.cdp("Input.dispatchKeyEvent", type="keyUp", **a)
        if text == "" and not append:
            await self.key("Backspace")
            return
        *chars, last = text
        if not last.isprintable():
            # A line break sent as the last real key is Enter: it would submit or send past the gate.
            chars, last = list(text), ""
        if chars:
            await self.cdp("Input.insertText", text="".join(chars))
        if last:
            await self.cdp("Input.dispatchKeyEvent", type="keyDown", key=last, text=last)
            await self.cdp("Input.dispatchKeyEvent", type="keyUp", key=last)

    async def key(self, key: str, modifiers: int = 0) -> None:
        """One key (a name of KEYS, a letter, digit or sign) with the modifier mask held, as Playwright presses it:
        the character it types goes with it only when no Control, Alt or Meta is held."""
        if key in KEYS:
            code, name = KEYS[key], "Space" if key == " " else key
        elif key in SIGNS:
            code, name = SIGNS[key], ""
        else:
            code, name = ord(key.upper()), ("Key" if key.isalpha() else "Digit") + key.upper()
        text = "" if modifiers & 7 else "\r" if key == "Enter" else (key.upper() if modifiers & 8 else key) \
            if len(key) == 1 else ""
        k = {"key": text if text and key != "Enter" else key, "code": name, "windowsVirtualKeyCode": code,
             "nativeVirtualKeyCode": code, "modifiers": modifiers}
        await self.cdp("Input.dispatchKeyEvent", type="rawKeyDown", **k)
        if text:
            await self.cdp("Input.dispatchKeyEvent", type="char", **k, text=text, unmodifiedText=text)
        await self.cdp("Input.dispatchKeyEvent", type="keyUp", **k)

    async def press(self, keys: str) -> str:
        """A key or a chord ("Control+Enter"), as chord() reads it."""
        spelled, modifiers, key = chord(keys)

        async def body() -> str:
            await self.key(key, modifiers)
            return f" {spelled}"
        return await self._act("press", None, body)

    async def scroll(self, down: bool = True, ident: int | None = None, until: str = "") -> str:
        """A wheel over the box `ident` (or the page's middle), as a person scrolls; with `until`, on wheel by wheel
        until those words are on the screen, waiting at the end of a list for more to load."""
        want = fold(until).strip()

        async def body() -> str:
            x, y, step = await self._wheel_at(ident)
            wheels = 0
            for wheels in range(1, (UNTIL_WHEELS if want else 1) + 1):
                if want and want in await self.screen_text():
                    return f" until {quote(clip(until, 40))}: it shows after {wheels - 1} wheels"
                before = await self._scrolled(ident)
                await self.cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0,
                               deltaY=step * (1 if down else -1))
                await self.settle(cap_ms=1500)
                after = await self._scrolled(ident)
                if (after["top"] == before["top"] and after["height"] == before["height"]
                        and await self._ended(ident, before)):
                    if want:
                        return f" until {quote(clip(until, 40))}: not found, the list ended after {wheels} wheels"
                    return " — it did not move: the end, or not the box that scrolls"
            if want:
                if want in await self.screen_text():
                    return f" until {quote(clip(until, 40))}: it shows after {wheels} wheels"
                return f" until {quote(clip(until, 40))}: not found in {wheels} wheels"
            return " down" if down else " up"
        return await self._act("scroll", ident, body)

    async def _scrolled(self, ident: int | None) -> dict:
        """How far the box (or the page) is scrolled, and how tall what it scrolls is."""
        if ident is None:
            return await self._evaluate("() => {const el = document.scrollingElement || document.documentElement;"
                                        " return {top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight};}")
        return await self.on_node(ident, SCROLLER_JS)

    async def _wheel_at(self, ident: int | None) -> tuple[float, float, float]:
        """Where a wheel turns and how far: the middle of what of the box is on screen, else the view's middle."""
        view = (await self.cdp("Page.getLayoutMetrics")).get("cssVisualViewport") or {}
        wide, high = float(view.get("clientWidth") or 800), float(view.get("clientHeight") or 600)
        if ident is None:
            return wide / 2, high / 2, high * 0.8
        b = await self.box(ident)
        top, bottom = max(b["y"], 0), min(b["y"] + b["h"], high)
        return (min(max(b["x"], 0) + min(b["w"], wide) / 2, wide - 2), (top + bottom) / 2 if bottom > top else high / 2,
                max(80.0, min(b["h"], high) * 0.8))

    async def _ended(self, ident: int | None, before: dict) -> bool:
        """A wheel that moved nothing is at the end, unless a feed loads more within MORE_S."""
        began = time.monotonic()
        while time.monotonic() - began < MORE_S and (await self._scrolled(ident))["height"] == before["height"]:
            await asyncio.sleep(0.3)
        return (await self._scrolled(ident))["height"] == before["height"]

    async def hover(self, ident: int | None, x: float | None = None, y: float | None = None) -> str:
        """The pointer over the element (or a point, as `at` takes one) and left there: a menu that opens on hover
        opens."""
        async def body() -> str:
            # A ref alone is waited for as a click's target is (its centre after the actionability checks).
            p = await self.at(ident, x, y, press=x is None)
            await self.cdp("Input.dispatchMouseEvent", type="mouseMoved", x=p["x"], y=p["y"])
            return "" if x is None else f" at {round(x)},{round(y)}" + (" from its top left" if ident is not None else "")
        return await self._act("hover", ident, body)

    async def wait(self, until: str = "", gone: str = "") -> str:
        """A few seconds for a page that is loading or answering; with `until` (or `gone`), up to WAIT_S until those
        words show on the page (or no longer do), as Playwright MCP's wait_for."""
        words = until or gone
        want = fold(words).strip()

        async def body() -> str:
            if not want:
                await asyncio.sleep(1.0)
                await self.settle(cap_ms=6000, quiet_ms=800)
                return ""
            began = time.monotonic()
            while (want in await self.visible_text()) != bool(until):
                if time.monotonic() - began > WAIT_S:
                    return f" until {quote(clip(words, 40))} {'shows' if until else 'is gone'}: still not after {WAIT_S:.0f} s"
                await asyncio.sleep(0.3)
            return (f" until {quote(clip(words, 40))} {'shows' if until else 'is gone'}: "
                    f"{'it shows' if until else 'gone'} after {time.monotonic() - began:.1f} s")
        return await self._act("wait", None, body)

    async def drag(self, start: dict, end: dict, route: list | None = None) -> str:
        """The button pressed at `start`, moved and let go at `end`, as Playwright drags (mouse down, moves, up)
        and Stagehand's dragAndDrop takes a route. Each end is {"id"} (its centre), {"id", "x", "y"} (that far
        from its top left) or {"x", "y"} (a point of the view); an end given as an id alone is let go a quarter
        past its middle along the way, so in a list the dragged item takes its place. `route`: [x, y] points
        passed through on the way, from where `start`'s are; else DRAG_STEPS moves along the line, so a list or a
        slider that follows the mouse sees it go by. A drag the page starts with the browser's own drag and drop
        is caught (Input.setInterceptDrags) and dropped there. The line says where a dragged item now sits."""
        if not self._drag_heard:
            await self.tab.events("Input.dragIntercepted", lambda params: setattr(self, "_dragged", params["data"]))
            self._drag_heard = True
        ident = start.get("id")

        async def body() -> str:
            a, b, path = await self._drag_path(start, end, route)
            # Where the dragged element stands among its own and on the page, to say after where it went; a drag from
            # a point in it (a line drawn on a canvas) moves something inside it, which this cannot tell.
            was, stood = await self._placed(ident) if ident is not None and start.get("x") is None else (None, None)
            await self._drag_moves(a, b, path)
            await asyncio.sleep(0.2)
            after, stands = await self._placed(ident) if was is not None else (None, None)
            return ((f" from {self._end_said(start)}" if ident is None or start.get("x") is not None else "")
                    + f" onto {self._end_said(end)}" + (f" through {len(route)} points" if route else "")
                    + _moved(was, stood, after, stands))
        return await self._act("drag", ident, body)

    def _end_said(self, at: dict) -> str:
        """An end of a drag as its line names it."""
        point = f"{round(at['x'])},{round(at['y'])}" if at.get("x") is not None else ""
        if at.get("id") is None:
            return f"the point {point}"
        return self.describe(at["id"]) + (f" at {point} from its top left" if point else "")

    async def _drag_path(self, start: dict, end: dict, route: list | None) -> tuple[dict, dict, list[dict]]:
        """Where a drag goes down, where it is let go, and the points the mouse passes on the way there; both ends
        brought into view before the button goes down."""
        ident, to = start.get("id"), end.get("id")
        await self.at(ident, start.get("x"), start.get("y"))
        b = await self.at(to, end.get("x"), end.get("y"), press=False)
        a = await self.at(ident, start.get("x"), start.get("y"))
        if to is not None and end.get("x") is None:
            # Past the middle along the way it goes: above it when going up, left of it when going left.
            box = await self.box(to)
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            b = ({"x": b["x"], "y": b["y"] + math.copysign(box["h"] / 4, dy)} if abs(dy) >= abs(dx) else
                 {"x": b["x"] + math.copysign(box["w"] / 4, dx), "y": b["y"]})
        if route:
            # Where the route's points are measured from: the start's element, else the view.
            base = await self.box(ident) if ident is not None else {"x": 0.0, "y": 0.0}
            return a, b, [{"x": base["x"] + float(p[0]), "y": base["y"] + float(p[1])} for p in route] + [b]
        return a, b, [{"x": a["x"] + (b["x"] - a["x"]) * n / DRAG_STEPS, "y": a["y"] + (b["y"] - a["y"]) * n / DRAG_STEPS}
                      for n in range(1, DRAG_STEPS + 1)]

    async def _placed(self, ident: int) -> tuple[dict | None, dict | None]:
        """Where an element stands among its own (PLACE_JS) and on the page; (None, None) once it is gone."""
        try:
            return await self.on_node(ident, PLACE_JS), await self.box(ident)
        except Exception:
            return None, None

    async def _drag_moves(self, a: dict, b: dict, path: list[dict]) -> None:
        """The button down at `a`, the first move with the browser's own drag and drop caught, the moves on along
        `path` (as drag events when the page started such a drag), and the button let go (or the drop) at `b`."""
        await self.cdp("Input.dispatchMouseEvent", type="mouseMoved", x=a["x"], y=a["y"])
        await self.cdp("Input.dispatchMouseEvent", type="mousePressed", x=a["x"], y=a["y"], button="left",
                       buttons=1, clickCount=1)
        self._dragged = None
        await self.cdp("Input.setInterceptDrags", enabled=True)
        try:
            first = path[0]
            await self.cdp("Input.dispatchMouseEvent", type="mouseMoved", x=first["x"], y=first["y"], button="left",
                           buttons=1)
            await asyncio.sleep(0.2)
        finally:
            await self.cdp("Input.setInterceptDrags", enabled=False)
        data, self._dragged = self._dragged, None
        if data is not None:
            await self.cdp("Input.dispatchDragEvent", type="dragEnter", x=first["x"], y=first["y"], data=data)
        for p in path[1:]:
            if data is not None:
                await self.cdp("Input.dispatchDragEvent", type="dragOver", x=p["x"], y=p["y"], data=data)
            else:
                await self.cdp("Input.dispatchMouseEvent", type="mouseMoved", x=p["x"], y=p["y"], button="left",
                               buttons=1)
                await asyncio.sleep(0.03)
        if data is not None:
            await self.cdp("Input.dispatchDragEvent", type="drop", x=b["x"], y=b["y"], data=data)
        else:
            await self.cdp("Input.dispatchMouseEvent", type="mouseReleased", x=b["x"], y=b["y"], button="left",
                           clickCount=1)

    async def goto(self, url: str) -> str:
        async def body() -> str:
            await self.cdp("Page.navigate", url=url)
            return f" {url}"
        return await self._act("navigate", None, body)

    async def back(self) -> str:
        async def body() -> str:
            history = await self.cdp("Page.getNavigationHistory")
            index = history.get("currentIndex", 0)
            if index <= 0:
                raise RuntimeError("no page before this one")
            await self.cdp("Page.navigateToHistoryEntry", entryId=history["entries"][index - 1]["id"])
            return ""
        return await self._act("back", None, body)
