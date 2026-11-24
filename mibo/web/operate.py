"""Doing something in a page of the person's browser for them, when they ask in chat.

Two halves, in two processes. `Hands` lives where the pane is (the app window's process): it looks at a tab's page
(pageops), sorts every step through the gate (gate.py) and, for anything with an effect outside, shows the person a
card built from the page itself and waits for their press. Nothing it is sent can get around that: the model's words
never count as consent. There is no loop of its own here: the reply model calls act (surface.py) with a few steps on
a place's tab, out of sight or in the middle, and decides itself from what comes back whether the task is done, as
the mature page tools leave it to the host's model (Playwright MCP, Chrome DevTools MCP, Claude in Chrome). One act
call is `Hands.steps`: each step's line, then what changed (the address, the title) and a Noticed line of what the
app saw meanwhile (what went out, the page's dialogs, text typed and not sent).

While it acts, Hands also hears the page's own requests that can change something (any that is not an image, a
script, a style or a font) and its navigations. What is judged is the act, as Claude in Chrome, ChatGPT agent and
Gemini's computer use judge it: the press and what it does for the person, by its name, its place (a 好的 in a box
that asks about deleting deletes: gate.py), the form it submits and what was typed. The page's own traffic counts
only where it carries the act: a request that carries text typed here (a form that saves by itself when a field
loses the focus) or a choice made here is held before it leaves and put to the person on the same card as a send;
so is what a press code could not sort sends to the page's own site (or its form's) that is not a GET (a save, a
submission), and a DELETE on any press. Every other request goes on untouched: a site's monitoring, beacons and
reads to its other hosts on every click and timer are not anyone's act, so a press that only moves about a site
never reaches a card or the reviewer. One act asks once: the requests one press holds share one card, and the answer
is kept (`kept`, shared across the turn's act calls). In automatic review the reviewer sees a held request (its
method, address and a summary of its body) and judges it. Once something was typed, images, scripts and styles are
heard too, so none carries it to another site. How much asks is the person's mode (acting.py), read at every step:
read only presses nothing that sends, automatic review puts sends and presses to the reviewer first, and paying,
deleting and accounts ask in every mode. Going to another site by an address the model wrote is free, unless the
address carries words read on a page (opcarry.words_carried): that is refused outright; the page going to another
site by its own script waits for the reviewer or a card (leave). Each step is shown before it happens, in the
person's words.

The step verbs are the converged page tools' (Playwright MCP's browser_click, browser_type, browser_select_option,
browser_press_key, browser_hover, browser_drag, browser_wait_for, browser_file_upload, browser_navigate and
browser_navigate_back; Claude in Chrome's scroll_to), each with a short line of what it does (Playwright MCP's
`element`, Claude's action_summary) that a gate card shows: `action_of` maps them to what Hands.act takes. A press
that changed nothing says so. A double click on a control with an effect outside is refused (it would press it
twice); a right click, a drag and a keyboard shortcut are watched as a bare 确认 is, so what they send waits for a
card; a chord ending in Enter is Enter; the clipboard is never used. `read` answers a question from what the page's
document holds, nothing scrolled, loading more only when the answer needs it (`read_page`, web/pagetext.py).

What the page asks for itself goes to the person on a card too (gate's upload, download and dialog), as Playwright's
file chooser, download and dialog events are handled: a file it wants goes into its field (DOM.setFileInputFiles)
once the person names or chooses it and says yes; a file it saves goes to the download folder on their yes; its own
confirm or prompt is answered Cancel at once and, on their yes, the step is done again with it answered OK. An alert
is closed and its words put on the step's line.

What a step says of itself is checked by code, never left to the model's word (tools/optruth.py measures it). A
click or a typing names its control, and an id whose control is another one is refused. A step's line names the
control and says what it changed: the control's own state and the words that came up on the page. A press that went
out once on the person's yes is not made again, nor the same words to the same place.

Hands is made of parts that share its state (set in Hands.__init__ here): the steps (opsteps.py), a press with an
effect outside (opoutside.py), the page's own requests held for a card (opheld.py, with what a request carries in
opcarry.py) and what the page asks for itself (opasks.py); the person's words for the steps are in opsaid.py.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from collections.abc import Awaitable, Callable

from . import gate, pagetext, signin
from .opasks import PageAsks
from .opheld import Holding
from .opoutside import HEAR_S, Outside
from .opsaid import reason
from .opsteps import Steps
from .pageops import Page
from .pageprint import STATE_MAX, STATE_MOST, view_of
from .pagewords import clip, quote

logger = logging.getLogger("mibo.web")

# Steps one act call takes (the reply model's act tool).
STEPS_MAX = 8
# How long a card waits for the person.
CARD_S = 170.0
# Requests an act's Noticed line names.
WENT_SHOWN = 6

# A sign-in form, a check, a payment page: the page goes back to the person (what pageops sees is not enough).
WALL_JS = r"""() => {
  const shown = (e) => e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
  const frames = [...document.querySelectorAll('iframe')].filter((f) => shown(f) && f.offsetWidth > 60 &&
    /captcha|challenge|turnstile|geetest|verify|hcaptcha|recaptcha\/api2\/anchor/i.test(f.src || ''));
  if (frames.length) return {kind: 'verification', evidence: (frames[0].src || '').slice(0, 80)};
  const body = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ');
  // A short page that only says to sign in first, whatever its title calls itself: a sign-in, with no check to pass.
  if (body.length < 1500 && /请先?登录|登录后(重试|继续|查看|访问)|(log|sign) ?in to (continue|view|see|access)|(must|need to) (be )?(log|sign)(ged|ed)? ?in/i.test(body))
    return {kind: 'sign_in', evidence: 'sign-in notice'};
  const top = document.title + ' ' + body.slice(0, 600);
  if (/just a moment|verify you are human|are you a robot|人机验证|安全验证|滑动验证|环境异常|ロボットではありません|자동입력 방지|проверка.{0,20}робот/i.test(top))
    return {kind: 'verification', evidence: top.slice(0, 80)};
  for (const form of document.querySelectorAll('form')) {
    if (!form.querySelector('input[type=password]') || !shown(form)) continue;
    const words = [...form.querySelectorAll('button,input[type=submit]')].map((b) => b.innerText || b.value || '').join(' ');
    if (/log\s?in|sign\s?in|登录|登入|ログイン|로그인|войти/i.test(words)) return {kind: 'sign_in', evidence: words.trim().slice(0, 80)};
  }
  // A canvas, map or game filling a fifth of the window or more: drawn, not written.
  const drawn = [...document.querySelectorAll('canvas,embed,object')].filter((e) => {
    const r = e.getBoundingClientRect();
    return shown(e) && r.width * r.height >= 0.2 * innerWidth * innerHeight;
  }).map((e) => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; });
  return {kind: '', evidence: '', drawn};
}"""


class Hands(Holding, PageAsks, Steps, Outside):
    """The pane's side: looks and acts on `tab`, every action through the gate. `ask(card)` shows the
    person a card and answers {"yes": bool, "never": bool}, {"waiting": the act in the person's words} when
    its time ran out with the card still up (the act ends waiting on it, and it stays answerable), or None
    when the person took the page or stopped; `kept` holds the answers to this turn's acts, by act, so one
    act asks once however often it comes (a card left waiting and answered later keeps its answer); `attended()`
    says the person is at the app (only then is a card's tick let to skip a card); `held()` says why the
    run may not go on ("" when it may: "stopped", "paused" when the person took the page); `tell(line)`
    shows the person the step about to happen, in `lang`.

    While it runs, a request the page makes that carries text typed in this run is held before it leaves (a
    form that saves itself when a field loses the focus, on a timer, by a beacon as the page is left; a GET
    only when it goes to another site, as a new tab or a fetch): the card is shown for it as for a send, and it
    goes on yes and is dropped on no. So is what a watched press sends to the page's own site that is not a GET,
    a DELETE on any press, and the page going to a site that is not the run's. A confirmed press lets out only its own site's requests,
    and only when what it sends carries the words the card showed. Requests that carry none of it pass
    untouched, so the site's own reads and telemetry go on as they would; images, scripts, styles and fonts
    are not paused at all. A file chooser, a download and the
    page's own dialogs are caught and put to the person on cards; `downloads()` gives the files the pane began
    to save since it was last asked, each held until its `answer(yes)`. `close()` ends that, and after a run the
    person said no to or stopped, puts back what was typed and never let out, so the page cannot send it later
    by itself.

    `mode()` is the person's mode for the browser (acting.py), read at every action; `review(action)` is the
    reviewer's verdict (review.decide) for what acting.decide sends it; `said()` is the person's own words of the
    turn under way (an address may carry what they said, never what a page showed); `page` is the tab's Page the
    looks read, so a look's refs are the steps' refs."""

    def __init__(self, tab, *, ask: Callable[[dict], Awaitable[dict | None]], allowed: gate.Allowed,
                 attended: Callable[[], bool], held: Callable[[], str] = lambda: "",
                 tell: Callable[[str], None] = lambda line: None, lang: str = "zh",
                 downloads: Callable[[], list[dict]] = list, mode: Callable[[], str] = lambda: "auto",
                 review: Callable[[dict], Awaitable] | None = None, kept: dict | None = None,
                 said: Callable[[], str] = lambda: "", page: Page | None = None):
        self.page = page or Page(tab)
        self.said = said
        self.kept = {} if kept is None else kept
        self.tab = tab
        # Every card carries the step's own line of what it does.
        self.ask = lambda card: ask({**card, "what": self._what})
        self.allowed = allowed
        self.attended = attended
        self.held = held
        self.tell = tell
        self.downloads = downloads
        self.mode = mode
        self.review = review
        self.lang = "zh" if str(lang).startswith("zh") else "en"
        self.confirmed = False
        # What was typed this run into fields that are not search boxes: {"text", "field", "site", "node",
        # "before", "out"}; "out" once the person let it out. Requests carrying one of these are held, all run long.
        self.typed: list[dict] = []
        # Outside actions pressed in this run, with what the page showed after: a like pressed twice is undone, and
        # anything pressed again on a page that has not changed since is done twice.
        self.pressed: dict[tuple, int] = {}
        # Words that went out in this run on the person's yes, by kind, page and recipient: the same again would
        # send them twice.
        self.sent: set[tuple] = set()
        # The run's sites: where it began, those the person named or said yes to, those a link led to. Until
        # `_follow_until` the page may go on to others by itself (a link's redirects).
        self.sites: set[str] = set()
        self._follow_until = 0.0
        # The reviewer's verdicts in this run, by action: the same control and request is not asked about twice.
        self._verdicts: dict[str, object] = {}
        # The queries each address was asked with while no typed text waited (Holding._covert).
        self._queries: dict[tuple[str, str], set[str]] = {}
        # Where each box that scrolls by itself stood after a read's last step on.
        self._read_at: dict = {}
        # Every page's words the model was shown from this tab: no address to another site carries them
        # (opcarry.words_carried).
        self.read: list[str] = []
        # The verb of the last step, and the sign-in prompt the last look saw at its address: a prompt that comes
        # back after a press is a wall (signin.judge).
        self._last_do = ""
        self._prompt_seen: tuple[str, str | None] = ("", None)
        # The step under way's own line of what it does, for its card; while an act call runs, the requests let out
        # and the page's dialogs, for its Noticed line.
        self._what = ""
        self._noting = False
        self._went: list[tuple[str, str]] = []
        self._dialogs: list[str] = []
        self._heard_state()

    def _heard_state(self) -> None:
        """What the run hears of the page by itself: its requests held, its navigations, its dialogs, the
        file chooser it opened and the answers that came back."""
        self._paused: asyncio.Queue | None = None
        # Held requests, each with the typed entries it carried when it was held.
        self._holding: list[tuple[dict, list[dict]]] = []
        # A confirmed press under way: {"site", "said", "matched", "aside"}.
        self._pressing: dict | None = None
        # A choice being made (a box ticked, a radio, a list's option): {"text", "field", "site", "out", "choice"}.
        # A post it sets off is a setting saved the moment it changed, held as an account change.
        self._choice: dict | None = None
        # The file chooser the page opened (Page.fileChooserOpened), for the step that opened it.
        self._file: dict | None = None
        # The page's own dialogs: lines of what it said, a question a step opened and that waits for its card,
        # the question the person said yes to (answered OK when it comes again), whether a step is under way.
        self._told: list[str] = []
        self._asked: dict | None = None
        self._again: tuple[str, str] | None = None
        self._acting = False
        self._closed = False
        self._drain: asyncio.Task | None = None
        # The main frame, whose navigations are the page's own, and the address it last went to.
        self._frame = ""
        self._address = ""
        # A bare submission under way (gate's "watch"): what the card says if a request leaves on it.
        self._watching: dict | None = None
        # The page's own navigations held, each with its card under way; how the last one not let go ended
        # ({"status": "declined" or "waiting", "kind", "result"}).
        self._navs: list[tuple[asyncio.Task, dict]] = []
        self._turned: dict = {}
        # While the person signs in, the page is theirs: Fetch's settings as they were, to turn it on again after.
        self._released: dict | None = None
        # The task answering the page's last dialog, held so it runs to its end.
        self._answering: asyncio.Task | None = None
        # The answers' status codes, by the browser's request id, for what went out.
        self._status: dict[str, int] = {}

    # --- looking

    async def look(self, most: int = STATE_MAX) -> dict:
        """The page as the model reads it, at most `most` characters, and what the page did by itself since."""
        why = self.held()
        if why:
            return {"status": why}
        await self._listen()
        state = await self.page.state(min(max(int(most), STATE_MAX), STATE_MOST))
        self.read.append(state)
        url = await self.page._evaluate("() => location.href")
        try:
            wall = await self.page._evaluate(WALL_JS) or {}
            # A sign-in box over a page a visitor may read is a prompt to close, not a wall (web/signin.py).
            layer = await self.page._evaluate(signin.CHECK_JS) or {}
            seen = self._prompt_seen
            wall = signin.judge(wall, layer, seen[1] if seen[0] == url else None, self._last_do in ("click", "press"))
            self._prompt_seen = (url, wall["prompt"])
            if wall["prompt"]:
                state += signin.prompt_line(wall["prompt"], signin.key(url))
        except Exception:
            wall = {}
        found = {"status": "ok", "state": state, "url": url, "wall": wall.get("kind", ""),
                 "evidence": wall.get("evidence", ""), "controls": self.page.interactive,
                 "drawn": bool(wall.get("drawn"))}
        found.update(await self.since())
        return found

    async def since(self) -> dict:
        """What the page did by itself since the last step: its dialogs, its own navigations' cards, its downloads'
        cards and the held requests' cards, as {"held": lines} (and how a card that did not let one go ended);
        {} when it did nothing."""
        found: dict = {}
        lines = [await self._page_said()]
        if self._turned:
            found.update(self._turned)
            self._turned = {}
        if self._holding:
            held = await self._held_cards()
            lines.append(held.pop("line"))
            if held["status"] != "ok":
                found.update(held)
        if any(lines):
            found["held"] = "\n".join(x for x in lines if x)
        return found

    async def _where(self) -> dict:
        try:
            return await self.page._evaluate("() => ({url: location.href, title: document.title})") or {}
        except Exception:
            # Between two pages.
            return {}

    async def steps(self, actions: list[dict]) -> dict:
        """One act call: each action in turn until one ends it (stopped, paused, declined, waiting, refused; one
        that did not work, or that took the page elsewhere with steps left, whose refs would be another page's),
        then what changed and what the app noticed meanwhile. {"status", "lines", "noticed", "url", "title",
        "texts"}: `texts` are the page's words each read step took ({"text", "goes_on"}), for the reader the
        service runs (read_page); they join what opcarry.words_carried checks."""
        why = self.held() or ("stopped" if self.mode() == "off" else "")
        if why:
            return {"status": why, "lines": [f"[{why}]"], "noticed": "", "url": "", "title": "", "texts": []}
        await self._listen()
        before = await self._where()
        self._noting, self._went, self._dialogs, self._status = True, [], [], {}
        lines: list[str] = []
        texts: list[dict] = []
        status = "ok"
        try:
            for n, action in enumerate(actions):
                result = await self.act(action)
                line = str(result.get("line") or "")
                if action.get("do") == "read" and result.get("status") == "ok":
                    texts.append({"text": str(result.get("text") or ""), "goes_on": bool(result.get("goes_on"))})
                    self.read.append(texts[-1]["text"])
                lines.append(line)
                status = str(result.get("status") or "failed")
                left = len(actions) - n - 1
                if status in ("stopped", "paused", "declined", "waiting", "refused"):
                    break
                if left and status != "ok":
                    lines.append(f"[not done] the {left} step(s) after it: it did not work. Look again first")
                    break
                if left and "navigated to" in line:
                    lines.append(f"[not done] the {left} step(s) after it: the page changed, so its refs are gone. "
                                 f"Look again first")
                    break
            lines += [held for held in [(await self.since()).get("held", "")] if held]
        finally:
            self._noting = False
        after = await self._where()
        noticed = []
        if after.get("url") and after.get("url") != before.get("url"):
            noticed.append(f"the address is now {clip(after['url'], 200)}")
        if after.get("title") and after.get("title") != before.get("title"):
            noticed.append(f"the title is now {quote(clip(after['title'], 80))}")
        went = list(dict.fromkeys(f"{line} {self._status.get(ident) or 'no answer yet'}" for line, ident in self._went))
        if went:
            noticed.append("went out: " + "; ".join(went[:WENT_SHOWN]) + (f" and {len(went) - WENT_SHOWN} more"
                                                                           if len(went) > WENT_SHOWN else ""))
        if self._dialogs:
            noticed.append("the page's own dialogs: " + "; ".join(self._dialogs[:4]))
        unsent = [t["field"] or "a field" for t in self.typed if not t["out"]]
        if unsent:
            noticed.append(f"typed into {', '.join(dict.fromkeys(unsent))} and not sent or saved yet")
        self.read += lines
        return {"status": status, "lines": lines, "noticed": "; ".join(noticed), "url": after.get("url", ""),
                "title": after.get("title", ""), "texts": texts}

    async def picture(self) -> dict:
        return await picture_of(self.page)

    async def act(self, action: dict) -> dict:
        """One action: {"status", "line", "said"}."""
        why = self.held() or ("stopped" if self.mode() == "off" else "")
        if why:
            return {"status": why, "line": f"[{why}]"}
        self._last_do = action.get("do")
        self._what = clip(" ".join(str(action.get("what") or "").split()), 80)
        self._acting = True
        try:
            result = await self._act(action)
        finally:
            self._acting = False
        if result.get("status") == "failed":
            # Why, for the person watching the steps.
            result["why"] = reason(str(result.get("line") or ""), self.lang)
        if self.typed and action.get("do") in ("type", "press", "click"):
            # A field left (a click elsewhere, Tab) may be saving what was typed: its request is heard first.
            await asyncio.sleep(HEAR_S)
        if self._asked:
            result = await self._answered(action, result)
        if self._file:
            upload = await self._upload(action)
            result = {**result, **upload, "line": f"{result.get('line', '')}\n{upload['line']}".strip()}
        said = await self._page_said()
        if said:
            result = {**result, "line": f"{result.get('line', '')}\n{said}".strip()}
            if "[download]" in said or "[held]" in said:
                result["outside"] = True
        if self._turned:
            result.update(self._turned)
            self._turned = {}
        if self._holding and result.get("status") in ("ok", "failed"):
            held = await self._held_cards()
            line = held.pop("line")
            result = {**result, "line": f"{result.get('line', '')}\n{line}".strip()}
            if "[held]" in line:
                result["outside"] = True
            if held["status"] != "ok":
                result.update(held)
        self._what = ""
        return result

    async def _listen(self) -> None:
        """The page's requests looked at from the first look on, and again once the person is past a sign-in."""
        if self._released is not None:
            await self.tab.cdp("Fetch.enable", self._released)
            self._released = None
        await self._watch()

    async def _url(self) -> str:
        return str(await self.page._evaluate("() => location.href") or "")

    async def _decided(self, kind: str, site: str, action: dict, key: str = "",
                       where: str = "") -> tuple[str, str, str]:
        """What the person's mode makes of an outside action before any card: "read" (read only: nothing goes),
        "go" (the reviewer passed it), "turned" (the reviewer turned it down) or "ask" (the card), with the
        reviewer's line and its reading of an outward act (review.DOES, or ""). The reviewer sees only kinds and
        sites acting.decide sends it; a sensitive page is judged by its full address `where` (mail.google.com)."""
        from .. import acting
        decision = acting.decide(self.mode(), kind, where or site)
        if decision == "refuse":
            return "read", "", ""
        if decision != "review" or self.review is None:
            return "ask", "", ""
        key = key or json.dumps([kind, site, action], ensure_ascii=False, sort_keys=True, default=str)
        if key not in self._verdicts:
            self._verdicts[key] = await self.review({"kind": kind, "where": site, **action})
        verdict = self._verdicts[key]
        line = verdict.line(self.lang)
        if verdict.decision == "go":
            return "go", line, verdict.does
        if verdict.decision == "refuse":
            return "turned", verdict.declined() + ("; turned down three times in a row: stop and hand the task back "
                                                   "to the person" if verdict.stop else ""), verdict.does
        self.tell(line)
        return "ask", line, verdict.does


async def picture_of(page: Page) -> dict:
    """The page as it stands in its view, in its own pixels, with each control and clickable thing of the last
    look boxed under its id; nothing else drawn on it."""
    from PIL import Image, ImageDraw
    metrics = await page.cdp("Page.getLayoutMetrics")
    view = metrics.get("cssVisualViewport") or {}
    wide, high = float(view.get("clientWidth") or 1280), float(view.get("clientHeight") or 800)
    shot = await page.cdp("Page.captureScreenshot", format="png", clip={
        "x": float(view.get("pageX") or 0), "y": float(view.get("pageY") or 0), "width": wide, "height": high,
        "scale": 1})
    image = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
    if image.size != (round(wide), round(high)):
        # A scaled display gives device pixels: the picture is brought to the page's own pixels, so a point
        # read off it and a click mean the same place.
        image = image.resize((round(wide), round(high)), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    boxed = 0
    for ident, (role, _name) in list(page.last.items()):
        if role in ("scrollable", "text"):
            continue
        try:
            b = await page.box(ident)
        except Exception:
            continue
        if b["w"] < 4 or b["h"] < 4 or b["x"] + b["w"] < 0 or b["y"] + b["h"] < 0 or b["x"] > wide or b["y"] > high:
            continue
        boxed += 1
        draw.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=(255, 90, 0), width=2)
        draw.rectangle([b["x"], b["y"] - 13, b["x"] + 8 + 7 * len(str(ident)), b["y"]], fill=(255, 90, 0))
        draw.text((b["x"] + 3, b["y"] - 13), str(ident), fill=(255, 255, 255))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=80)
    return {"status": "ok", "picture": base64.b64encode(out.getvalue()).decode(), "boxed": boxed,
            "size": [round(wide), round(high)]}


async def look_at(page: Page, most: int, *, ref: int | None = None, interactive: bool = False, find: str = "",
                  start: int = 0, picture: bool = False) -> dict:
    """A look at a page (surface.py's look): its print or a part of it, what was left out
    and why, what the app noticed on it (hints from WALL_JS and signin.CHECK_JS, never a verdict), and with
    `picture` the page as it stands. Nothing on the page is pressed and no request of it is held."""
    # What the page's own script draws once it has loaded (a list, a table) is waited for.
    await page.settle()
    state = await page.state(min(max(int(most), STATE_MAX), STATE_MOST))
    probe = await page._evaluate("() => ({url: location.href, title: document.title})") or {}
    left = [f"lines {a + 1}-{b} are not shown (report_limit): look from {a + 1} goes on, or find" for a, b in page.cut]
    if ref is not None or interactive or find or start:
        state, part = view_of(page.lines, page.spans, ref=ref, interactive=interactive, find=find, start=start,
                              most=most)
        left = [part] if part else []
    if page.secrets:
        left.append(f"what {len(page.secrets)} secret fields hold is masked (private)")
    if any(line.startswith("--- frame") and "for the person" in line for line in page.lines):
        left.append("payment and sign-in frames are not read (private)")
    noticed = []
    try:
        wall = await page._evaluate(WALL_JS) or {}
        judged = signin.judge(wall, await page._evaluate(signin.CHECK_JS) or {}, None, False)
    except Exception:
        judged = {}
    if judged.get("kind") == "verification":
        noticed.append(f"a check for people is on the page ({clip(judged.get('evidence', ''), 80)})")
    elif judged.get("kind"):
        noticed.append(f"the page asks them to sign in ({clip(judged.get('evidence', ''), 80)})")
    if judged.get("prompt"):
        noticed.append(f"a sign-in box that can be closed is over the page (“{clip(judged['prompt'], 60)}”)")
    if page.secrets:
        noticed.append("a password field")
    if judged.get("drawn"):
        noticed.append("a drawn part (canvas, map or game) the lines cannot show: picture shows it")
    found = {"status": "ok", "state": state, "url": probe.get("url", ""), "title": probe.get("title", ""),
             "omitted": "; ".join(left), "noticed": "; ".join(noticed)}
    if picture:
        found["picture"] = (await picture_of(page))["picture"]
    return found


VERBS = ("click", "type", "select_option", "key", "hover", "drag", "select_text", "scroll_to", "wait_for",
         "upload_file", "go", "back", "read")


def action_of(step: dict) -> dict:
    """One step of the act tool (its converged verbs, Playwright's and the browser agents' names) as the Hands
    action it is: click {ref | text | x,y, ref with x,y from its top left, double, right}, type {ref, text,
    submit, add}, select_option {ref, values}, key {keys}, hover {ref | text | x,y}, drag {ref | text | x,y, to |
    to_text | to_x,to_y, route}, select_text {ref, text?}, scroll_to {ref?, text?, up}, wait_for {text | gone},
    upload_file {ref, file: the file chooser it opens is given that path}, go {url}, back, read {question,
    look_for?, section?}. Every step keeps its "what" line. ValueError for a verb it does not know."""
    verb = step.get("do")
    ref = step.get("ref")
    took = {"what": str(step.get("what") or "")}
    if ref is not None:
        took["id"] = ref
    if verb in ("click", "upload_file"):
        took.update(do="click", element=str(step.get("element") or ""))
        if verb == "upload_file":
            took["file"] = str(step.get("file") or "")
        for key in ("text", "x", "y"):
            if step.get(key) is not None:
                took[key] = step[key]
        if step.get("double") is True:
            took["double"] = True
        if step.get("right") is True:
            took["button"] = "right"
        return took
    if verb == "type":
        return {**took, "do": "type", "text": str(step.get("text") or ""), "enter": step.get("submit") is True,
                "append": step.get("add") is True}
    if verb == "select_option":
        values = step.get("values")
        values = values if isinstance(values, list) else [values]
        return {**took, "do": "type", "text": ", ".join(str(v) for v in values if v is not None)}
    if verb == "key":
        return {**took, "do": "press", "key": str(step.get("keys") or "")}
    point = {key: step[key] for key in ("x", "y") if isinstance(step.get(key), (int, float))}
    if verb == "hover":
        return {**took, "do": "hover", **point, **({"text": str(step["text"])} if step.get("text") else {})}
    if verb == "drag":
        return {**took, "do": "drag", "to": step.get("to"), **point,
                **{key: step[key] for key in ("to_x", "to_y") if isinstance(step.get(key), (int, float))},
                **({"text": str(step["text"])} if step.get("text") else {}),
                **({"to_text": str(step["to_text"])} if step.get("to_text") else {}),
                **({"route": step["route"]} if isinstance(step.get("route"), list) else {})}
    if verb == "select_text":
        return {**took, "do": "select", "text": str(step.get("text") or "")}
    if verb == "scroll_to":
        return {**took, "do": "scroll", "direction": "up" if step.get("up") is True else "down",
                "until": str(step.get("text") or "")}
    if verb == "wait_for":
        return {**took, "do": "wait", "until": str(step.get("text") or ""), "gone": str(step.get("gone") or "")}
    if verb == "go":
        return {**took, "do": "navigate", "url": str(step.get("url") or "")}
    if verb == "back":
        return {**took, "do": "back"}
    if verb == "read":
        return {**took, "do": "read", "question": str(step.get("question") or ""), **(
            {"more": step["more"]} if step.get("more") in ("step", "all") else {}),
                "look_for": str(step.get("look_for") or ""), **({"section": step["section"]}
                                                                if isinstance(step.get("section"), int) else {})}
    raise ValueError(str(verb))


async def read_page(ask_model, hands, action: dict, question: str, room: int) -> dict:
    """The `read` step made: the page's words from `hands` (what its document holds now, the page not scrolled; a
    list that draws only the rows in view read through), read for `question` by web/pagetext.py in `room` tokens
    (the reply model's page room), more of the page loaded through `hands` only when the answer needs it. The
    step's result with "answer", "found" (yes, no or partly), "calls" (the model calls the reading took), "read"
    (what was read and what was left), "sections" and "text" (the words the model saw)."""
    result = await hands.act(action)
    if result.get("status") != "ok":
        return {**result, "answer": "", "found": "", "calls": 0, "read": "", "sections": [], "text": ""}

    async def more(how: str) -> tuple[str, bool]:
        got = await hands.act({"do": "read", "more": how, "question": question})
        return str(got.get("text") or ""), bool(got.get("goes_on"))
    part = action.get("section")
    part = part if isinstance(part, int) and not isinstance(part, bool) else -1
    text = str(result.pop("text", "") or "")
    reading = await pagetext.answer(ask_model, question, text, room, more=more, goes_on=bool(result.get("goes_on")),
                                    look_for=str(action.get("look_for") or ""), part=part)
    return {**result, **reading}
