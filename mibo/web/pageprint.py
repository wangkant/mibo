"""A look at a page (Page.state): its documents captured (the accessibility trees of the page and of every frame,
a frame from another site in its own session, a DOM snapshot of each for pagelayout) and printed as one list in page
order, one line per control with the id the model acts by; and a part of such a print (view_of), as the snapshot
tools give one. A mixin of pageops.Page: it uses the page's own probes (settle, _evaluate, visible_text)."""
from __future__ import annotations

import asyncio
import bisect
import re
import time
from typing import Any
from urllib.parse import urlsplit

from ..browsed import secret as secret_address
from .pagelayout import STYLES, empty, layout
from .pagewords import (
    CONTROLS,
    FRAME_IDS,
    SECRET_LABEL,
    SECRET_SELECTOR,
    SET_BY_VALUE,
    clip,
    fold,
    is_context_loss,
    norm,
    quote,
    well_formed,
)

# Text inside these is one line; text across them is not joined.
BLOCKS = {"paragraph", "listitem", "row", "LabelText"}
CELLS = {"cell", "gridcell", "columnheader", "rowheader"}
NATIVE_INPUTS = {"Date", "DateTime", "InputTime", "ColorWell"}
# How much of a field's value and how many of a list's options a line shows.
VALUE_MAX = 400
# A text area's text is shown whole up to this many characters: it is there to be read or typed again.
AREA_MAX = 3000
OPTIONS_MAX = 40
# What a state the model sees may hold, characters: for the least able model, and the most for one whose context
# window has room, as browser-use gives tens of thousands.
STATE_MAX = 6000
STATE_MOST = 20_000
# A line with an id on it, and how many lines a look's find returns (read_page's find: up to 20).
ID_LINE = re.compile(r"\*?\[\d+\]")
FIND_MAX = 20
SECRET_MASK = "•••"
# A name that says nothing by itself: empty, a count, a sign; and a count with its unit (1.2万, 11.8K).
NAMELESS = re.compile(r"^[\W\d_]{0,6}$")
COUNT = re.compile(r"^\d[\d.,]*\s*[万萬亿億千kKmMbBwW]?\+?$")
# How long a blank page is given to draw.
BLANK_S = 8.0
# Frames the person fills in themselves, beside browsed.secret's sign-in and payment addresses: card fields of the
# payment services and bot checks, by host or path.
PERSON_FRAME = re.compile(r"(^|\.)(stripe\.com|stripe\.network|braintreegateway\.com|braintree-api\.com|adyen\.com|"
                          r"checkout\.com|klarna\.com|paypalobjects\.com|hcaptcha\.com|recaptcha\.net|"
                          r"challenges\.cloudflare\.com|arkoselabs\.com|geetest\.com)(/|$)|/recaptcha/", re.I)


def for_person(url: str) -> bool:
    """A frame never read or acted in: payment, sign-in or a bot check."""
    parts = urlsplit(url)
    return secret_address(url) or bool(PERSON_FRAME.search(f"{parts.hostname or ''}{parts.path}"))


def val(o: Any) -> Any:
    return o.get("value") if isinstance(o, dict) else None


def prop(n: dict, name: str) -> Any:
    return next(((p.get("value") or {}).get("value") for p in n.get("properties") or [] if p.get("name") == name),
                None)


def view_of(lines: list[str], spans: dict, *, ref: int | None = None, interactive: bool = False, find: str = "",
            start: int = 0, most: int = STATE_MAX) -> tuple[str, str]:
    """A part of a print's uncut lines, a page's or a window's (desk/uia.py prints windows in the same grammar), as
    the snapshot tools give one: `ref` the lines of one id and under it (`spans`), `interactive` only the lines of
    ids, `find` the id lines holding these words (FIND_MAX, as read_page's find), `start` the lines from that one
    (1 for the first). (the lines, what was left out)."""
    numbered = list(enumerate(lines, 1))
    if ref is not None:
        if ref not in spans:
            return "", f"no ref {ref} in the last look; look again for the refs now"
        a, b = spans[ref]
        numbered = numbered[a:b]
    if interactive:
        numbered = [(n, x) for n, x in numbered if ID_LINE.match(x)]
    if find:
        want = [w for w in fold(find).split() if w]
        # Words are looked for in what a line says, not in its ref.
        hits = [(n, x) for n, x in numbered if want and all(w in fold(ID_LINE.sub("", x, 1)) for w in want)]
        ids = [(n, x) for n, x in hits if ID_LINE.match(x)]
        numbered = (ids or hits)[:FIND_MAX]
        more = len(ids or hits) - len(numbered)
        if not numbered:
            return "", f"no line holds “{clip(find, 60)}”"
    numbered = [(n, x) for n, x in numbered if n >= start]
    shown, size = [], 0
    for n, x in numbered:
        size += len(x) + 1
        if size > most:
            break
        shown.append((n, x))
    left = []
    if find and more > 0:
        left.append(f"{more} more lines hold these words (report_limit)")
    if len(shown) < len(numbered):
        left.append(f"lines {numbered[len(shown)][0]}-{numbered[-1][0]} are not shown (report_limit): look "
                    f"from {numbered[len(shown)][0]} goes on")
    return well_formed("\n".join(x for _, x in shown)), "; ".join(left)


def _fit(lines: list[str], budget: float) -> int:
    """How many of the lines, from the first, fit in `budget` characters."""
    size = 0
    for i, line in enumerate(lines):
        size += len(line) + 1
        if size > budget:
            return i
    return len(lines)


def _child_frames(tree: dict) -> list[tuple[str, str]]:
    """Every frame under a frame tree, as (address, frame id), in order."""
    found = []
    for child in tree.get("childFrames") or []:
        found.append((child["frame"].get("url", ""), child["frame"]["id"]))
        found += _child_frames(child)
    return found


class Lines(list):
    """The state's lines, each with where it stands down the page (`at`, from the last node the walk passed that
    has a place: `y`), so a page too long for one look shows what is on the screen."""

    def __init__(self) -> None:
        super().__init__()
        self.at: list[float | None] = []
        self.y: float | None = None

    def append(self, line: str) -> None:
        super().append(line)
        self.at.append(self.y)

    def insert(self, i: int, line: str) -> None:
        super().insert(i, line)
        self.at.insert(i, self.y)

    def pop(self, i: int = -1) -> str:
        self.at.pop(i)
        return super().pop(i)


class Looking:
    """The look of pageops.Page."""

    async def _capture(self, session: str = "") -> list[dict]:
        """AX trees of a document (the page's, or with `session` a frame's from another site) and of every child
        frame in its process; a payment or sign-in frame among those is left to the person. A frame from another
        site is not listed here: `_layout` finds where it sits."""
        for i in range(21):
            try:
                return await self._capture_once(session)
            except Exception as e:
                if i >= 20 or not is_context_loss(e):
                    raise
                await asyncio.sleep(0.05)
        raise AssertionError("unreachable")

    async def _capture_once(self, session: str) -> list[dict]:
        """One try of `_capture`; a child frame that cannot be read is listed empty."""
        nodes = (await self._in(session, "Accessibility.getFullAXTree"))["nodes"]
        children = _child_frames((await self._in(session, "Page.getFrameTree"))["frameTree"])
        frames = [{"url": "", "nodes": nodes}]
        for url, ident in children:
            if for_person(url):
                frames.append({"url": url, "nodes": [], "person": True})
                continue
            try:
                frames.append({"url": url, "nodes": (await self._in(session, "Accessibility.getFullAXTree",
                                                                    frameId=ident))["nodes"]})
            except Exception:
                frames.append({"url": url, "nodes": []})
        return frames

    async def _secret_ids(self, session: str = "") -> set[int]:
        """Fields secret by their type or autocomplete, wherever they are in a document."""
        root = (await self._in(session, "DOM.getDocument", depth=0))["root"]
        found = set()
        for node in (await self._in(session, "DOM.querySelectorAll", nodeId=root["nodeId"],
                                     selector=SECRET_SELECTOR))["nodeIds"]:
            found.add((await self._in(session, "DOM.describeNode", nodeId=node))["node"]["backendNodeId"])
        return found

    async def _layout(self, session: str = "") -> dict:
        """pagelayout.layout of one DOM snapshot of a document."""
        return layout(await self._in(session, "DOMSnapshot.captureSnapshot", computedStyles=STYLES,
                                     includeDOMRects=True))

    async def _frames(self, url: str, frames: list[dict]) -> list[dict]:
        """The documents of a look: the page's (`url`, its `frames` as captured) and each frame's from another
        site, with its owner and its number; a payment or sign-in frame is named and not read. Each comes with
        what `_layout`, the visible text and the secret fields give of it."""
        docs = [{"session": "", "url": url, "k": 0, "frames": frames}]
        found = []
        for session in await self.tab.frames():
            try:
                top = (await self._in(session, "Page.getFrameTree"))["frameTree"]["frame"]
            except Exception:
                # Gone since it was listed.
                continue
            found.append((session, top["id"], top.get("url", "")))
        self.frames = {}
        for session, frame, address in found:
            owner = None
            for where in ["", *(s for s, _, _ in found if s != session)]:
                try:
                    owner = (where, (await self._in(where, "DOM.getFrameOwner", frameId=frame))["backendNodeId"])
                    break
                except Exception:
                    # Its frame element is in another document.
                    continue
            if owner is None:
                continue
            k = self._numbers.setdefault(frame, len(self._numbers) + 1)
            doc = {"session": session, "url": address, "k": k, "owner": owner, "person": for_person(address)}
            if not doc["person"]:
                try:
                    doc["frames"] = await self._capture(session)
                except Exception:
                    continue
                self.frames[k] = {"session": session, "url": address, "owner": owner}
            docs.append(doc)
        for doc in docs:
            if not doc.get("person"):
                await self._read_doc(doc)
        return docs

    async def _read_doc(self, doc: dict) -> None:
        """What a look needs of one document beside its tree: its layout, its visible text and its secret fields."""
        try:
            doc["layout"] = await self._layout(doc["session"])
        except Exception:
            doc["layout"] = empty()
        try:
            doc["visible"] = await self.visible_text(doc["session"])
        except Exception:
            doc["visible"] = None
        try:
            doc["secret"] = await self._secret_ids(doc["session"])
        except Exception:
            doc["secret"] = set()

    async def _loaded(self) -> tuple[dict, list[dict]]:
        """The page settled and its trees captured; a blank page still drawing (its script comes late) is given
        BLANK_S once per document. (the probe, the trees)."""
        settled = await self.settle()
        probe = settled.get("probe") or await self._evaluate("() => ({url: location.href, title: document.title})")
        frames = await self._capture()
        began = time.monotonic()
        while self._waited != probe.get("doc") and (not any(len(f["nodes"]) > 3 for f in frames) or not await self._evaluate(
                "() => !!(document.body && document.body.innerText.trim())")) and time.monotonic() - began < BLANK_S:
            await asyncio.sleep(0.5)
            settled = await self.settle()
            probe = settled.get("probe") or probe
            frames = await self._capture()
        self._waited = probe.get("doc")
        return probe, frames

    async def state(self, most: int = STATE_MAX) -> str:
        """The page as one list in page order: `[id] role "name" = value states`, `## headings` and visible
        text, with `*` on ids new since the last look and secret fields masked. `[id] clickable "words"` is
        shown as clickable with no control named there; `[id] scrollable (…)` is a box that scrolls by itself;
        `{words}` after a control with no name is its tooltip, icon or class; `(form)` after a date, time, colour,
        range or several-choice field is what to type into it; a frame from another site is printed where it sits,
        between `--- frame <host> (another site) ---` and `--- end of frame`, or named in one line when it is for
        the person (payment, sign-in) or cannot be read. At most `most` characters: see `_body`."""
        probe, frames = await self._loaded()
        docs = await self._frames(probe.get("url", ""), frames)
        previous = self.last
        self.before = (self.last, self.near)
        self.last, self.secrets, self.interactive, self.near, self.values = {}, set(), 0, {}, {}
        self.outer = {}
        self.spans, self.cut = {}, []
        self.looks += 1
        printed = _Print(self, docs, previous)
        printed.emit(docs[0])
        self.lines = printed.lines
        header = f"[state] {probe.get('title', '')} | {probe.get('url', '')}"
        if probe.get("sh") and probe.get("vh") and probe["sh"] > probe["vh"] + 40:
            # How much of the page is above and below the screen.
            down = probe.get("sy", 0) / (probe["sh"] - probe["vh"])
            header += (" | page at the top, more below" if down < 0.02 else " | page at the end" if down > 0.98
                       else f" | page {round(down * 100)}% down")
        body = self._body(printed.lines, probe, most)
        return well_formed(f"{header}\n" + "\n".join(body) + "\n[/state]")

    def _body(self, lines: Lines, probe: dict, most: int) -> list[str]:
        """The lines a state shows. Over `most` characters: the top of the page (its title and menu), the last lines
        (a dialog's Send is usually its last line), and between them what stands on the screen now, as browser-use
        shows what is in view; scrolling shows the rest. The stretches left out go to `cut`."""
        if _fit(lines, most) >= len(lines):
            return list(lines) or ["(nothing in the accessibility tree: the page is blank or still loading)"]
        head, tail = _fit(lines, most * 0.15), _fit(lines[::-1], most * 0.1)
        end = len(lines) - tail
        room = most * 0.75
        sy, vh, at = probe.get("sy", 0), probe.get("vh", 0), lines.at
        # The lines on the screen (a box scrolled inside the page included); the window holding most of them
        # starts at the first of these.
        seen = [i for i in range(head, end) if at[i] is not None and sy - 40 <= at[i] <= sy + vh]
        shown = next((i for i in range(head, end) if at[i] is not None and at[i] >= sy), end)
        if seen:
            shown = max(seen, key=lambda c: bisect.bisect_left(seen, c + _fit(lines[c:end], room))
                        - bisect.bisect_left(seen, c))
        # A few lines over the screen's first, then on down as far as there is room.
        start = max(shown - _fit(lines[head:shown][::-1], room * 0.15), head)
        stop = start + _fit(lines[start:end], room)
        if stop == end:
            start = max(end - _fit(lines[head:end][::-1], room), head)
        self.cut = [(a, b) for a, b in ((head, start), (stop, end)) if b > a]
        return [*lines[:head],
                *([f"... {start - head} lines above cut here: scroll up to see them, or find or read them"]
                  if start > head else []),
                *lines[start:stop],
                *([f"... {end - stop} lines below cut here: scroll down to see them, or find or read them"]
                  if stop < end else []),
                *lines[end:]]


class _Tree:
    """One accessibility tree being printed, with what its document's look gives of it: its ids are numbered by
    the document's frame (`base`), and `away` are the frames from another site it holds, by their frame element."""

    def __init__(self, doc: dict, base: int, frame: dict, away: dict) -> None:
        self.doc, self.base, self.frame, self.away = doc, base, frame, away
        self.layout, self.visible, self.secret = doc["layout"], doc["visible"], doc["secret"]
        self.by_id = {n["nodeId"]: n for n in frame["nodes"]}


class _Print:
    """One print of a look: its lines as the walk makes them, and the look's records it fills on the page (last,
    near, spans, secrets, values, outer, interactive)."""

    def __init__(self, page: Any, docs: list[dict], previous: dict) -> None:
        self.page, self.docs, self.previous = page, docs, previous
        self.lines = Lines()
        # Words met since the last line ended: they are one line when it ends.
        self.text: list[str] = []
        self.tops = docs[0]["layout"]["y"]

    def new(self, ident: int) -> str:
        """`*` before an id the look before this one did not have."""
        return "*" if self.previous and ident not in self.previous else ""

    def flush(self) -> None:
        if self.text:
            self.lines.append(" ".join(self.text))
            self.text.clear()

    def context(self) -> str:
        """The text just before a control, digits out, to find it again once the page draws it anew."""
        here = " ".join(self.text) if self.text else next(
            (x for x in reversed(self.lines) if not x.startswith(("[", "*["))), "")
        return re.sub(r"[\d\s.,:%+-]+", " ", here).strip()[-60:]

    def emit(self, doc: dict) -> None:
        """The lines of one document, the page's or a frame's from another site, its ids numbered by its frame."""
        base = doc["k"] * FRAME_IDS
        self.page.outer.update({base + part: base + whole for part, whole in doc["layout"]["outer"].items()})
        here = urlsplit(doc["url"]).hostname
        away = {k: host for k, host in doc["layout"]["frame"].items() if host != here}
        for frame in doc["frames"]:
            if frame.get("person"):
                self.flush()
                self.lines.append(f"--- frame {urlsplit(frame['url']).hostname}: payment or sign-in, for the person; "
                                  f"it is not read")
                continue
            self.tree(_Tree(doc, base, frame, away))

    def tree(self, tree: _Tree) -> None:
        """The lines of one accessibility tree; a child frame's under a line naming it, and the page's own drawn
        parts put in by where they stand."""
        start = len(self.lines)
        nodes, url = tree.frame["nodes"], tree.frame["url"]
        self.walk(tree, nodes[0] if nodes else None, "")
        self.flush()
        if not url:
            self.drawn_lines(tree.doc, tree.base, start)
        if url and len(self.lines) > start:
            self.lines.insert(start, f"--- frame {url} ---")
            self.page.spans = {k: (a + (a >= start), b + (b > start)) for k, (a, b) in self.page.spans.items()}

    def drawn_lines(self, doc: dict, base: int, start: int) -> None:
        """What the document draws, each put in by where it stands down the page (after `start`, its first
        line): a drawing with its name and size, then its shapes, each with its colour and centre from the
        drawing's top left, so a point given from there lands; a colour box with its colour, name and size. Each
        has an id. The colour and shape words are the model's; the gate judges a drawn part by its own name."""
        page, lines = self.page, self.lines
        for local, item in sorted(doc["layout"]["drawn"].items(), key=lambda kv: kv[1]["y"]):
            ident = base + local
            size = f"{round(item['w'])}x{round(item['h'])}"
            name = item.get("name", "")
            named = f" {quote(clip(name, 60))}" if name else ""
            if item["kind"] == "box":
                page.last[ident] = ("box", name or item["colour"].split(" ")[0])
                block = [f"{self.new(ident)}[{ident}] box {item['colour']}{named} {size}"]
            else:
                page.last[ident] = ("drawing", name or item["kind"])
                block = [f"{self.new(ident)}[{ident}] drawing {item['kind']}{named} {size}: a picture shows it; give "
                         f"a point in it as x,y from its top left with this ref"]
                block += [self.shape_line(base + shape["id"], shape, ident) for shape in item["shapes"]]
            page.near[ident] = ""
            at = next((i for i in range(start, len(lines)) if lines.at[i] is not None and lines.at[i] > item["y"]),
                      len(lines))
            was, lines.y = lines.y, item["y"]
            for k, line in enumerate(block):
                lines.insert(at + k, line)
            lines.y = was
            n = len(block)
            page.spans = {k: (a + n * (a >= at), b + n * (b > at)) for k, (a, b) in page.spans.items()}
            page.spans[ident] = (at, at + n)

    def shape_line(self, sid: int, shape: dict, drawing: int) -> str:
        """A shape of a drawing: its kind, words and colour, its size and its centre from the drawing's top left."""
        self.page.last[sid] = ("shape", " ".join(x for x in (shape["kind"], shape["words"],
                                                             shape["colour"].split(" ")[0]) if x))
        self.page.near[sid] = ""
        return (f"{self.new(sid)}[{sid}] {shape['kind']}"
                + (f" {quote(clip(shape['words'], 60))}" if shape["words"] else "")
                + (f" {shape['colour']}" if shape["colour"] else "")
                + f" {round(shape['w'])}x{round(shape['h'])}, its centre at"
                f" {round(shape['x'])},{round(shape['y'])} of [{drawing}]")

    def words_in(self, tree: _Tree, n: dict | None, out: list[str], depth: int = 0) -> bool:
        """The shown words under n into out; whether a control is under it."""
        if not n or depth > 40:
            return False
        role = str(val(n.get("role")) or "")
        if role == "StaticText":
            t = norm(val(n.get("name")))
            if t and (tree.visible is None or fold(t) in tree.visible):
                out.append(t)
            return False
        found = False
        for c in n.get("childIds") or []:
            child = tree.by_id.get(c)
            if child and not child.get("ignored") and (
                    str(val(child.get("role")) or "") in CONTROLS or child.get("backendDOMNodeId") in tree.layout["click"]):
                found = True
            found = self.words_in(tree, child, out, depth + 1) or found
        return found

    def walk(self, tree: _Tree, n: dict | None, inside: str) -> None:
        """A node's lines, and for an id the span of them: from its own line to the last line under it."""
        start = len(self.lines)
        self.node(tree, n, inside)
        local = (n or {}).get("backendDOMNodeId")
        ident = tree.base + local if local else local
        if ident in self.page.last and ident not in self.page.spans:
            own = (f"[{ident}]", f"*[{ident}]")
            at = next((i for i in range(start, len(self.lines)) if self.lines[i].startswith(own)), start)
            self.page.spans[ident] = (at, len(self.lines))

    def walk_kids(self, tree: _Tree, kids: list, inside: str) -> None:
        for c in kids:
            self.walk(tree, tree.by_id.get(c), inside)

    def node(self, tree: _Tree, n: dict | None, inside: str) -> None:
        """One node of the tree: a drawn part kept for drawn_lines, a box that scrolls by itself, a frame from
        another site, something shown as clickable, words, a heading, a control; else what is under it. `inside`
        are the words of the control or heading it is in, not said again."""
        if not n:
            return
        role = val(n.get("role"))
        role = "" if role is None else str(role)
        name = norm(val(n.get("name")))
        kids = n.get("childIds") or []
        local = n.get("backendDOMNodeId")
        ident = tree.base + local if local else local
        if not tree.base and local in self.tops:
            self.lines.y = self.tops[local]
        if local in tree.layout["drawn"]:
            # Drawn: its lines go in by where it stands (drawn_lines), with the name the tree gives it; its own
            # tree is not read.
            tree.layout["drawn"][local]["name"] = name
            return
        if role in CELLS and self.text:
            # The cells of a table's row stay apart, so its columns can be compared.
            self.text.append("|")
        if local in tree.layout["scroll"] and ident not in self.page.last:
            self.scrollable(tree, local, ident, name)
        if local in tree.away:
            self.frame(tree, local)
            return
        if (local in tree.layout["click"] and ident not in self.page.last and role not in CONTROLS
                and not (prop(n, "focusable") and role != "RootWebArea") and self.clickable(tree, n, ident, inside)):
            return
        if n.get("ignored"):
            self.walk_kids(tree, kids, inside)
            return
        if role == "StaticText":
            t = fold(name)
            if t and t not in inside and (tree.visible is None or t in tree.visible):
                self.text.append(name)
            return
        if role == "heading" and name:
            self.flush()
            self.lines.append(f"## {name}")
            self.walk_kids(tree, kids, fold(name))
            return
        # A slider's knob or an icon with no name that takes the focus is shown by its hint.
        focusable = (prop(n, "focusable") and role != "RootWebArea"
                     and (name or val(n.get("value")) or prop(n, "editable")
                          or (local in tree.layout["small"] and tree.layout["hint"].get(local))))
        if ident and (role in CONTROLS or role in NATIVE_INPUTS or focusable):
            self.control(tree, n, role, name, inside)
        elif role in BLOCKS:
            self.flush()
            self.walk_kids(tree, kids, inside)
            self.flush()
        else:
            self.walk_kids(tree, kids, inside)

    def scrollable(self, tree: _Tree, local: int, ident: int, name: str) -> None:
        """A box that scrolls by itself: a conversation list, a feed in a column."""
        self.flush()
        self.page.near[ident] = self.context()
        self.page.last[ident] = ("scrollable", name)
        self.lines.append(f"{self.new(ident)}[{ident}] scrollable" + (f' "{clip(name, 60)}"' if name else "")
                          + f" ({tree.layout['scroll'][local]}; scroll it by this id)")

    def frame(self, tree: _Tree, local: int) -> None:
        """A frame from another site (a chat widget, a comment box), printed where it sits."""
        self.flush()
        inner = next((d for d in self.docs if d.get("owner") == (tree.doc["session"], local)), None)
        host = urlsplit(inner["url"]).hostname if inner else tree.away[local]
        if inner is None:
            self.lines.append(f"--- frame {host}: from another site, cannot be read")
        elif inner.get("person"):
            self.lines.append(f"--- frame {host}: payment or sign-in, for the person; it is not read")
        else:
            self.lines.append(f"--- frame {host} (another site) ---")
            self.emit(inner)
            self.flush()
            self.lines.append("--- end of frame")

    def clickable(self, tree: _Tree, n: dict, ident: int, inside: str) -> bool:
        """Shown as clickable though the tree names no control: a row, a menu entry, a day. Its line, and what is
        under it when it holds a control; False when it shows nothing to name it by."""
        local, name = n.get("backendDOMNodeId"), norm(val(n.get("name")))
        said: list[str] = []
        holds = self.words_in(tree, n, said)
        shown = clip(name or norm(" ".join(said)), 40 if holds else 100)
        # An icon with no words (a trash can, a heart), or only its count, is named by its tooltip, drawing or class.
        hint = "" if shown and not COUNT.match(shown) else tree.layout["hint"].get(local, "")
        if not (shown or holds or hint):
            return False
        self.flush()
        self.page.near[ident] = self.context()
        self.page.last[ident] = ("clickable", shown)
        self.page.interactive += 1
        self.lines.append(f"{self.new(ident)}[{ident}] clickable" + (f' "{shown}"' if shown else "")
                          + (f" {{{hint}}}" if hint else ""))
        if holds:
            self.walk_kids(tree, n.get("childIds") or [], fold(f"{inside} {shown}"))
            self.flush()
        return True

    def control(self, tree: _Tree, n: dict, role: str, name: str, inside: str) -> None:
        """A control's line: `[id] kind [secret] "name" {hint} (form) = value states  options: …`, then what is
        under it, unless it is a list, a native field or a secret one."""
        page, layout = self.page, tree.layout
        local, kids = n["backendDOMNodeId"], n.get("childIds") or []
        ident = tree.base + local
        near = self.context()
        self.flush()
        if self.lines and self.lines[-1].lower() == name.lower():
            self.lines.pop()
        value = norm(val(n.get("value")))
        is_secret = local in tree.secret or (role in ("textbox", "searchbox", "generic") and bool(
            SECRET_LABEL.search(name)))
        states = _states(n)
        popup = next((c for c in map(tree.by_id.get, kids) if c and val(c.get("role")) == "MenuListPopup"), None)
        options = _options(tree, popup)
        kind = layout["type"].get(local, "")
        shown = ("select" if popup else "file" if role == "button" and value
                 else "textbox" if role == "generic" and prop(n, "editable")
                 else kind if kind not in ("", "range", "multiple") else role)
        # What to type into a field set by value, or into a list where several can be chosen.
        form = (f"a number from {prop(n, 'valuemin')} to {prop(n, 'valuemax')}" if kind == "range"
                else SET_BY_VALUE.get(kind) or ('several: "a, b"' if kind == "multiple" else ""))
        page.last[ident] = (shown, name)
        page.near[ident] = near
        page.interactive += 1
        hints = layout["hint"]
        hint = hints.get(local, "") if NAMELESS.match(name) and shown in ("button", "link", "generic") else ""
        if not hint and hints.get(local, "").endswith("· on") and shown in ("button", "link", "generic"):
            states = [*states, "on"]
        if is_secret:
            page.secrets.add(ident)
            value = SECRET_MASK if value else ""
        most = AREA_MAX if local in layout["area"] else VALUE_MAX
        if not is_secret and len(value) > most:
            page.values[ident] = value
        more = f" | … {len(options) - OPTIONS_MAX} more" if len(options) > OPTIONS_MAX else ""
        self.lines.append(f"{self.new(ident)}[{ident}] {shown}"
                          + (" [secret]" if is_secret else "")
                          + (f' "{clip(name, 150)}"' if name else "")
                          + (f" {{{hint}}}" if hint and fold(hint) != fold(name) else "")
                          + (f" ({form})" if form else "")
                          + (f" = {quote(clip(value, most))}" if value else "")
                          + (" " + " ".join(states) if states else "")
                          + ("  options: " + " | ".join(options[:OPTIONS_MAX]) + more if options else ""))
        if popup or role in NATIVE_INPUTS or is_secret:
            return
        self.walk_kids(tree, kids, fold(f"{inside} {clip(name, 150)} {value}"))
        self.flush()


def _states(n: dict) -> list[str]:
    """What a control says of itself: checked, expanded, a menu it opens, selected, turned off, focused."""
    checked, expanded = prop(n, "checked"), prop(n, "expanded")
    return [s for s in [
        "" if checked is None else "unchecked" if checked == "false" else "checked",
        "" if expanded is None else "expanded" if expanded else "collapsed",
        # aria-haspopup: a menu or a list opens from it, on a click or under the pointer.
        "has menu" if prop(n, "hasPopup") not in (None, False, "false") else "",
        "selected" if prop(n, "selected") else "",
        "disabled" if prop(n, "disabled") and not prop(n, "focusable") else "",
        "focused" if prop(n, "focused") else ""] if s]


def _options(tree: _Tree, popup: dict | None) -> list[str]:
    """The options of a native list's popup, in order."""
    options: list[str] = []

    def collect(c: dict | None) -> None:
        if not c:
            return
        if val(c.get("role")) == "option":
            options.append(norm(val(c.get("name"))))
        else:
            for k in c.get("childIds") or []:
                collect(tree.by_id.get(k))
    collect(popup)
    return options
