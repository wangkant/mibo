"""Reading a whole page for a question (Page's read steps): what its document holds now with nothing scrolled, one
step on where a feed loads more, the whole of it as far down as it goes, and a row not drawn yet scrolled to. A box
that scrolls by itself and draws only the rows in view is read step by step, what each step shows merged in order.
A mixin of pageops.Page: it uses the page's own probes (_evaluate, on_node, settle, locate)."""
from __future__ import annotations

import asyncio
import difflib
import json
import time
from typing import Any

from .pagejs import DRAWN_JS, SCROLL_JS, TEXT_JS
from .pagewords import FRAME_IDS, clip, quote, well_formed

# How long a scroller is waited on at its end for more to load.
MORE_S = 2.5
# Reading the whole page: steps down each scroller at most, and characters at most.
WHOLE_STEPS = 60
TEXT_MOST = 400_000


def merge(merged: list[str], last: list[str], now: list[str]) -> list[str]:
    """What a scroller shows after a step (`now`) put after what it showed before it (`last`, already in `merged`):
    the lines after the part the two have in common; all of `now` when they share none (a page that only grew
    keeps its first lines and adds the rest)."""
    if not last:
        return list(now)
    blocks = [b for b in difflib.SequenceMatcher(None, last, now, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return merged + now
    end = blocks[-1]
    return merged + now[end.b + end.size:]


class Reading:
    """The read steps of pageops.Page."""

    async def _scroller(self, box: int | None, to: Any) -> Any:
        """SCROLL_JS on a box that scrolls by itself, or with None on the page."""
        if box is None:
            return await self._evaluate(f"function(){{return ({SCROLL_JS}).call(null, {json.dumps(to)})}}")
        return await self.on_node(box, SCROLL_JS, to)

    def _boxes(self) -> list[int]:
        """The boxes of the last look that scroll by themselves, in the page itself."""
        return [i for i, (role, _) in self.last.items() if role == "scrollable" and i < FRAME_IDS]

    async def _text(self, box: int | None = None) -> str:
        """TEXT_JS over the document, or over a box that scrolls by itself."""
        got = await (self._evaluate(f"function(){{return ({TEXT_JS}).call(null, {TEXT_MOST})}}")
                     if box is None else self.on_node(box, TEXT_JS, TEXT_MOST))
        return str(got or "")

    async def document(self) -> tuple[str, bool]:
        """What the document holds now (TEXT_JS), past what the window shows and with nothing scrolled, as the
        leaders read a page; and whether the page or a box goes on below what it shows. A box whose words fill
        less than half its height draws only the rows in view: its rows are not in the document until scrolled to,
        so it is read through now, as `whole` reads it, and is not counted as going on."""
        parts, goes_on = [await self._text()], False
        for box in self._boxes():
            try:
                drawn = await self.on_node(box, DRAWN_JS)
                if drawn["below"] > 40 and drawn["words"] < drawn["height"] / 2:
                    parts.append(self._all_of(box, await self._through(box)))
                else:
                    goes_on = goes_on or drawn["below"] > 40
            except Exception:
                # A box gone since the look.
                continue
        goes_on = goes_on or (await self._scroller(None, "where"))["below"] > 40
        return well_formed("\n".join(parts))[:TEXT_MOST], goes_on

    async def step(self, at: dict) -> tuple[str, bool]:
        """One step on, for a question what was read does not answer: the page taken to its end, where a feed loads
        more, and waited on up to MORE_S for it; each box that scrolls by itself one screen down from where the
        last step left it (`at`, by box, kept between steps). The document's words then, with what each box showed
        there, and whether any of them goes on still. Each is put back where it was."""
        began = (await self._scroller(None, "where"))["top"]
        height = (await self._scroller(None, "end"))["height"]
        waited = time.monotonic()
        while time.monotonic() - waited < MORE_S and (await self._scroller(None, "where"))["height"] == height:
            await asyncio.sleep(0.3)
        await self.settle(cap_ms=1500)
        now = await self._scroller(None, "where")
        goes_on = now["height"] > height or now["below"] > 40
        parts = [await self._text()]
        for box in self._boxes():
            try:
                was = (await self._scroller(box, "where"))["top"]
                await self._scroller(box, at.get(box, was))
                moved = await self._scroller(box, "down")
                at[box] = moved["top"]
                await self.settle(cap_ms=1500)
                parts.append(await self._text(box))
                goes_on = goes_on or moved["below"] > 40
                await self._scroller(box, was)
            except Exception:
                # A box gone since the look.
                continue
        await self._scroller(None, began)
        return well_formed("\n".join(parts))[:TEXT_MOST], goes_on

    async def whole(self) -> str:
        """The whole page's words (TEXT_JS), as far down as it goes, for a question about a whole list (its
        largest, a count): the page and each box that scrolls by itself read through (`_through`). At most
        TEXT_MOST characters."""
        parts = ["\n".join(await self._through(None))]
        for box in self._boxes():
            try:
                parts.append(self._all_of(box, await self._through(box)))
            except Exception:
                # Gone since the look.
                continue
        return well_formed("\n".join(parts))[:TEXT_MOST]

    async def _through(self, box: int | None) -> list[str]:
        """The lines of a scroller (a box, or the page with None) as far down as it goes: taken to its end (again
        while a feed loads more there); one that no longer holds what it showed at its top (a list that draws only
        the rows in view) is read step by step from the top, what each step shows merged in order. Put back where
        it was. At most WHOLE_STEPS steps."""
        async def capture() -> list[str]:
            return [x for x in (await self._text(box)).split("\n") if x]

        began = (await self._scroller(box, "where"))["top"]
        first = await capture()
        for _ in range(WHOLE_STEPS):
            height = (await self._scroller(box, "end"))["height"]
            waited = time.monotonic()
            while (time.monotonic() - waited < MORE_S
                   and (await self._scroller(box, "where"))["height"] == height):
                await asyncio.sleep(0.3)
            if (await self._scroller(box, "where"))["height"] == height:
                break
            await self.settle(cap_ms=1500)
        lines = await capture()
        kept = set(lines)
        if sum(1 for x in first if x in kept) < 0.8 * len(first):
            await self._scroller(box, 0)
            await self.settle(cap_ms=1500)
            lines, last = [], []
            for _ in range(WHOLE_STEPS):
                now_lines = await capture()
                lines, last = merge(lines, last, now_lines), now_lines
                if not (await self._scroller(box, "down"))["moved"]:
                    break
                await self.settle(cap_ms=1500)
            else:
                lines.append("... it goes on past what was read")
        await self._scroller(box, began)
        return lines

    def _all_of(self, box: int, rows: list[str]) -> str:
        """A box's rows read through, under a line that names the box."""
        name = self.last[box][1]
        return (f"--- the box{' ' + quote(clip(name, 40)) if name else ''} that scrolls by itself, all of it:\n"
                + "\n".join(rows))

    async def seek(self, words: str) -> int | None:
        """Something showing these words that is not drawn yet (a row far down a list that draws only the rows in
        view): each box that scrolls by itself, then the page, scrolled from its top until the words are there;
        its id, or None with each put back where it was."""
        for box in [*self._boxes(), None]:
            try:
                began = (await self._scroller(box, "where"))["top"]
            except Exception:
                continue
            await self._scroller(box, 0)
            for _ in range(WHOLE_STEPS):
                await self.settle(cap_ms=1500)
                found = await self.locate(words)
                if found is not None:
                    return found
                if not (await self._scroller(box, "down"))["moved"]:
                    break
            await self._scroller(box, began)
        return None
