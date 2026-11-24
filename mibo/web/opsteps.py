"""The steps operate.Hands takes on a page: each verb made (click, type, select, press, hover, drag, scroll, find,
read, wait, go and back), named to the person before it happens, refused when its id names another control than the
one the model names, and ended with what it changed (the control's own state, the words that came up). A mixin of
operate.Hands: its state is set in Hands.__init__."""
from __future__ import annotations

import contextlib
import functools
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from . import gate, signin
from .opcarry import words_carried
from .opheld import FOLLOW_S, TYPED_WATCHED
from .opoutside import DRAWN, HEAR_S, PRESS_TAIL_S, strictness
from .opsaid import SAID
from .pageact import Refused
from .pageinput import chord
from .pagewords import clip, fold, quote

# Presses of one control in one click (`times`): a stepper's +, a calendar's next-month arrow.
TIMES_MAX = 24
# Points a drag passes through on its way (a circle drawn, a path traced), at most.
ROUTE_MAX = 40
# Controls that make a choice; a post one sets off is held as a setting saved (Hands._choosing).
CHOICES = ("checkbox", "radio", "menuitemcheckbox", "menuitemradio", "option", "combobox", "listbox")

# A native list's options, for the select (or its label) clicked: a click opens a list no page can show.
OPTIONS_JS = """function(){const e = this.nodeType === 1 ? this : this.parentElement;
  const s = e.tagName === 'SELECT' ? e : e.control && e.control.tagName === 'SELECT' ? e.control : null;
  return s ? [...s.options].map((o) => o.text.trim()).filter(Boolean).slice(0, 40) : null;}"""

# A link that opens a new tab: its address, to open in this one (the run works in one page).
BLANK_JS = """function(){const a = (this.nodeType === 1 ? this : this.parentElement).closest('a[href]');
  return a && a.target === '_blank' && /^https?:/.test(a.href) ? a.href : null;}"""

# The words the page shows, one entry a text node, through same-site frames and shadow roots (pagejs.VISIBLE_JS
# keeps them as one string): what an action brought up is what was not there before it.
LINES_JS = r"""() => {
  const out = [], shown = new Map(), roots = [document];
  for (let i = 0; i < roots.length; i++) {
    const walk = document.createTreeWalker(roots[i], NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n && out.length < 4000; n = walk.nextNode()) {
      if (n.nodeType === Node.ELEMENT_NODE) {
        if (n.shadowRoot) roots.push(n.shadowRoot);
        if (n.contentDocument) roots.push(n.contentDocument);
        continue;
      }
      const text = n.textContent.replace(/\s+/g, ' ').trim(), e = n.parentElement;
      if (!e || !text) continue;
      if (!shown.has(e)) shown.set(e, e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}));
      if (shown.get(e)) out.push(text.slice(0, 120));
    }
  }
  return out;
}"""

# A control before and after an action: what it says of itself (checked, pressed, expanded, selected; "on" where
# only its class says so, as pageops reads a filled star) and the words the page shows.
SEEN_JS = r"""function() {
  const e = this.nodeType === 1 ? this : this.parentElement;
  const said = (name) => e.getAttribute(name) === null ? null : e.getAttribute(name) === 'true';
  return {lines: (""" + LINES_JS + r""")(), state: {
    checked: e.matches('input[type=checkbox],input[type=radio]') ? e.checked : said('aria-checked'),
    pressed: said('aria-pressed'), expanded: said('aria-expanded'),
    selected: e.tagName === 'OPTION' ? e.selected : said('aria-selected'),
    on: /(^|\s)(on|active|is-active|is-on|liked|starred|selected|checked|pressed|faved)(\s|$)/.test(
      typeof e.className === 'string' ? e.className : '')}};
}"""
# How many of the words an action brought up its line holds: a click's, and a hover's (a menu's entries).
CAME_UP = 2
CAME_UP_HOVER = 8

# What a role is called, beside its own word: a control named only by its kind ("输入框", "the button") is not
# taken for another one.
KINDS = {"textbox": "input field box 输入框 文本框", "searchbox": "search box 搜索框", "button": "btn 按钮",
         "link": "链接", "checkbox": "check 复选框 勾选", "radio": "单选", "combobox": "dropdown select list 下拉 选择 列表",
         "select": "dropdown list 下拉 选择 列表", "listbox": "list 列表", "option": "选项", "tab": "标签 选项卡",
         "menuitem": "menu item 菜单", "switch": "toggle 开关", "slider": "滑块", "clickable": "", "text": ""}
CJK = "぀-ヿ㐀-鿿가-힯"
CJK_RUN = re.compile(rf"[{CJK}]+")
WORD_RUN = re.compile(rf"[^\W_{CJK}]+")


def words_of(text: str) -> tuple[set[str], set[str]]:
    """A name's words, for telling one control from another: runs of letters and digits and pairs of CJK
    characters (a CJK character alone where it stands alone), and its CJK characters one by one."""
    low = fold(text)
    runs = CJK_RUN.findall(low)
    return (set(WORD_RUN.findall(low)) | {run[i:i + 2] for run in runs for i in range(max(len(run) - 1, 1))},
            {c for run in runs for c in run})


def shown_name(name: str, facts: dict) -> str:
    """A control as the person sees it: an icon is named on the card by its tooltip, as it shows on hover."""
    shown = name or facts.get("text") or facts.get("label") or ""
    if gate.NO_WORDS.match(shown) and facts.get("tip"):
        shown = f"{shown} {facts['tip']}".strip()
    return shown


class Steps:
    """The steps of operate.Hands."""

    def _said(self, action: dict, name: str = "") -> str:
        """The step as a person names it: 点「发送」, 在搜索框输入「猫」."""
        say, do = SAID[self.lang], action.get("do")
        name = clip(" ".join(str(name or action.get("element") or action.get("text") or "").split()), 30)
        if do == "click":
            how = "double" if action.get("double") is True else "right" if action.get("button") == "right" else "click"
            return say[how].format(name=name or say["point"])
        if do == "drag":
            return say["drag"].format(name=name, to=clip(" ".join(str(action.get("target") or action.get("to_text")
                                                                       or "").split()), 30))
        if do == "type":
            return say["type"].format(name=name or say["box"], text=clip(str(action.get("text") or ""), 40))
        if do == "press":
            return say["press"].format(key=action.get("key") or "")
        if do == "hover":
            return say["hover"].format(name=name)
        if do == "scroll":
            return (say["up" if action.get("direction") == "up" else "down"]
                    + (say["in"].format(name=name) if action.get("id") is not None and name else "")
                    + (say["until"].format(text=clip(str(action["until"]), 30)) if action.get("until") else ""))
        if do == "navigate":
            return say["navigate"].format(host=urlsplit(str(action.get("url") or "")).hostname or "")
        if do == "wait" and (action.get("until") or action.get("gone")):
            return say["shows" if action.get("until") else "gone"].format(
                text=clip(str(action.get("until") or action.get("gone")), 30))
        if do in ("back", "wait"):
            return say[do]
        if do == "find":
            return say["find"].format(text=clip(str(action.get("text") or ""), 30))
        if do == "read":
            return say["more" if action.get("more") else "read"].format(text=clip(str(action.get("question") or ""), 30))
        if do == "select":
            words = clip(" ".join(str(action.get("text") or "").split()), 30)
            return say["select"].format(name=clip(" ".join(str(name or action.get("element") or "").split()), 30),
                                        text=(f"「{words}」" if self.lang == "zh" else f" “{words}”") if words else "")
        return ""

    async def _act(self, action: dict) -> dict:
        do = action.get("do")
        if "id" in action and action["id"] in (None, ""):
            # {"id": null, "text": "保存"}: the words are the target.
            action = {k: v for k, v in action.items() if k != "id"}
        point = isinstance(action.get("x"), (int, float)) and isinstance(action.get("y"), (int, float))
        if do in ("click", "type", "hover", "select") and "id" not in action:
            if do in ("click", "hover", "select") and str(action.get("text") or "").strip():
                # Something shown with no id, by the words it shows.
                found = await self.page.locate(str(action["text"])) or await self.page.seek(str(action["text"]))
                if found is None:
                    return {"status": "missing", "line": f"[missing] nothing on the page shows "
                                                         f"{clip(str(action['text']), 60)!r}; look again"}
                action = {**action, "id": found, "element": action.get("element") or action["text"]}
            elif not (do in ("click", "hover") and point):
                return {"status": "failed", "line": f"[failed] {do} needs a ref from the latest look"}
        step = {"click": self._click_step, "select": self._select_step, "type": self._type_step, "drag": self._drag,
                "hover": self._hover, "press": self._press_step, "scroll": self._scroll, "find": self._find,
                "read": self._read, "wait": self._wait, "navigate": self._navigate, "back": self._back}.get(do)
        if step is None:
            return {"status": "failed", "line": f"[failed] no action {str(do)[:20]!r}"}
        try:
            return await step(action)
        except Refused as refused:
            return {"status": "refused", "line": str(refused)}
        except (KeyError, ValueError, TypeError):
            return {"status": "failed", "line": f"[failed] {do} needs an id from the latest page"}
        except RuntimeError as error:
            return {"status": "failed", "line": f"[failed] {do}: {clip(str(error), 160)}; look again"}

    async def _click_step(self, action: dict) -> dict:
        element = str(action.get("element") or "")
        if "id" not in action:
            return await self._click_point(float(action["x"]), float(action["y"]), element)
        times = int(action["times"]) if str(action.get("times", "")).isdigit() else 1
        how = "double" if action.get("double") is True else "right" if action.get("button") == "right" else ""
        point = isinstance(action.get("x"), (int, float)) and isinstance(action.get("y"), (int, float))
        return await self._click(int(action["id"]), element, max(1, min(times, TIMES_MAX)), how,
                                 (float(action["x"]), float(action["y"])) if point else None)

    async def _select_step(self, action: dict) -> dict:
        return await self._select(int(action["id"]), str(action.get("text") or ""), str(action.get("element") or ""))

    async def _type_step(self, action: dict) -> dict:
        return await self._type(int(action["id"]), str(action.get("text") or ""), action.get("enter") is True,
                                str(action.get("element") or ""), action.get("append") is True)

    async def _press_step(self, action: dict) -> dict:
        try:
            keys = chord(str(action.get("key") or ""))[0]
        except ValueError as error:
            return {"status": "failed", "line": f"[failed] {error}"}
        return await self._press(keys)

    async def _hover(self, action: dict) -> dict:
        point = isinstance(action.get("x"), (int, float)) and isinstance(action.get("y"), (int, float))
        ident = await self._fresh(int(action["id"])) if "id" in action else None
        if "id" in action and ident is None:
            return {"status": "failed", "line": f"[failed] [{action['id']}] is not on the page now; look again"}
        said = self._said(action, self.page.last.get(ident, ("", ""))[1] or SAID[self.lang]["point"])
        self.tell(said)
        before = await self._seen(ident)
        line = await (self.page.hover(ident, float(action["x"]), float(action["y"])) if point
                      else self.page.hover(ident))
        # A menu opened by a style alone changes nothing the page counts: what came up says it opened.
        return {"status": "ok" if line.startswith("[ok]") else "failed", "said": said,
                "line": line + await self._changed(ident, before, line, CAME_UP_HOVER)}

    async def _scroll(self, action: dict) -> dict:
        ident = action.get("id")
        ident = await self._fresh(int(ident)) if ident is not None else None
        said = self._said(action, self.page.last.get(ident, ("", ""))[1] if ident else "")
        self.tell(said)
        line = await self.page.scroll(action.get("direction") != "up", ident, str(action.get("until") or ""))
        return {"status": "ok", "line": line, "said": said}

    async def _find(self, action: dict) -> dict:
        words = str(action.get("text") or "")
        found = self.page.grep(words)
        return {"status": "ok", "said": self._said(action), "found": found,
                "line": f"[ok] find {clip(words, 40)!r}: " + (f"{found.count(chr(10)) + 1} lines" if found
                                                              else "not on this page")}

    async def _read(self, action: dict) -> dict:
        """The page's words for the loop's reader (read_page): what the document holds now, the page not scrolled
        (a list that draws only the rows in view read through); with "more", one step on ("step") or the rest of a
        list ("all")."""
        said = self._said(action)
        self.tell(said)
        how = action.get("more")
        if how == "all":
            text, goes_on = await self.page.whole(), False
        elif how == "step":
            text, goes_on = await self.page.step(self._read_at)
        else:
            self._read_at = {}
            text, goes_on = await self.page.document()
        return {"status": "ok", "said": said, "text": text, "goes_on": goes_on,
                "line": f"[ok] read the page: {len(text)} characters" + (" after loading more" if how else "")}

    async def _wait(self, action: dict) -> dict:
        self.tell(self._said(action))
        return {"status": "ok", "said": self._said(action), "line": await self.page.wait(
            str(action.get("until") or ""), str(action.get("gone") or ""))}

    async def _navigate(self, action: dict) -> dict:
        """Going to an address: free, unless the person turned off this site, or the address carries to another
        site words read on a page that the person did not say."""
        url = str(action.get("url") or "")
        if urlsplit(url).scheme not in ("http", "https"):
            return {"status": "failed", "line": "[failed] only http and https addresses"}
        site = gate.site_of(url)
        if not signin.chose(self.allowed.path.parent, url, "task"):
            # Settings › 连接: the person turned off the character opening this site by itself.
            return {"status": "failed", "line": f"[refused] the person turned off opening {site} on your own "
                                                f"(connect/sites, which the settings tool opens); nothing "
                                                f"was opened. Ask them"}
        carried = words_carried(url, "\n".join(self.read), self.said()) if site not in self.sites else ""
        if carried:
            # A page's words in an address to another site: what a page said would leave by the address.
            return {"status": "refused", "line": f"[refused] the address to {site} carries words read on a "
                                                 f"page ({carried!r}) that the person did not say; "
                                                 f"nothing was opened"}
        self.sites.add(site)
        self._follow_until = time.monotonic() + FOLLOW_S
        self.tell(self._said(action))
        return {"status": "ok", "line": await self.page.goto(url), "said": self._said(action)}

    async def _back(self, action: dict) -> dict:
        self.tell(self._said(action))
        return {"status": "ok", "line": await self.page.back(), "said": self._said(action)}

    async def _fresh(self, ident: int) -> int | None:
        """The id itself while it is on the page; a control drawn again since the look, found again (in one
        step in the page, else by a fresh look); or None."""
        if ident in self.page.last and await self.page.alive(ident):
            return ident
        return await self.page.again(ident) or await self.page.relocate(ident)

    async def _seen(self, ident: int | None) -> dict:
        """What a control says of itself and the words the page shows, read before an action and after it."""
        try:
            if ident is not None:
                return await self.page.on_node(ident, SEEN_JS)
        except Exception:
            pass
        try:
            return {"state": {}, "lines": await self.page._evaluate(LINES_JS) or []}
        except Exception:
            return {"state": {}, "lines": []}

    async def _changed(self, ident: int | None, before: dict, line: str, most: int = CAME_UP) -> str:
        """What an action that went through changed, to end its line: the control's own state (now on, no longer
        checked), then the words that came up on the page, `most` of them. "" for an action that failed or left
        the page: the next look shows a new page whole."""
        if not line.startswith("[ok]") or "navigated to" in line:
            return ""
        after = await self._seen(ident)
        said = [f"{'now' if now else 'no longer'} {key}" for key, now in after["state"].items()
                if now is not None and now != before["state"].get(key) and (now or before["state"].get(key))]
        left, new = Counter(before["lines"]), []
        for text in after["lines"]:
            if left[text] > 0:
                left[text] -= 1
            elif text not in new:
                new.append(text)
        if new:
            said.append("came up on the page: " + " | ".join(quote(clip(text, 60)) for text in new[:most])
                        + (f" and {len(new) - most} more" if len(new) > most else ""))
        return "".join(f"; {s}" for s in said)

    def _other(self, ident: int, element: str, role: str, name: str, facts: dict) -> str:
        """The refusal for an id whose control is not the one the model names: `element` shares no word with this
        control (its name, tooltip, label, class, kind, the text before it; for one with no words of its own, the
        item it sits in), while those words do stand elsewhere on the page. "" when it may go on: a control
        named loosely, by its kind or in another language, is none of the page's other words."""
        nameless = bool(gate.NO_WORDS.match(name))
        # Its own words share by a single CJK character too (收藏 for 藏品); what stands round it, by whole words.
        own = " ".join(str(x or "") for x in (name, facts.get("text"), facts.get("label"), facts.get("tip"), role,
                                              KINDS.get(role, "")))
        round_it = " ".join(str(x or "") for x in (facts.get("hint"), facts.get("classes"), self.page.near.get(ident, ""),
                                                   facts.get("row") if nameless else ""))
        wanted, wanted_chars = words_of(element)
        mine, mine_chars = words_of(own)
        mine |= words_of(round_it)[0]
        if not wanted or wanted & mine or wanted_chars & mine_chars or any(
                len(w) > 2 and (w in m or m in w) for w in wanted for m in mine if len(m) > 2):
            return ""
        here = self.page.describe(ident)
        elsewhere = [x for x in self.page.lines if not x.lstrip("*").startswith(f"[{ident}] ") and wanted & words_of(x)[0]]
        if not elsewhere:
            return ""
        # The line that holds most of the words named, when it is a control's.
        best = max(elsewhere, key=lambda x: len(wanted & words_of(x)[0]))
        there = re.match(r"\*?(\[\d+\] \S+(?: \"[^\"]*\")?)", best)
        return (f"[failed] {here} is not {quote(clip(element, 60))}: nothing was done. "
                + (f"{there.group(1)} holds those words" if there else
                   f"Those words are shown with no id ({quote(clip(best, 60))}): click or hover them by their text")
                + "; look again")

    async def _click(self, ident: int, element: str, times: int = 1, how: str = "",
                     at: tuple[float, float] | None = None) -> dict:
        """A click; `how` "double" or "right"; `at` a point from its top left to press it at; judged by the strictest
        of what it is a press on (_pressed). A double click on a control with an effect outside would press it twice
        and is refused; a right click presses nothing but opens the page's menu, so what it sends is watched as a
        bare submission's press is."""
        fresh = await self._fresh(ident)
        if fresh is None:
            return {"status": "failed", "line": f"[failed] [{ident}] is not on the latest page; look again"}
        ident = fresh
        role, name = self.page.last.get(ident, ("", ""))
        facts = await self.page.facts(ident)
        other = self._other(ident, element, role, name, facts)
        if other:
            return {"status": "failed", "line": other}
        url = await self._url()
        try:
            judged = await self._pressed(ident, *(at or (None, None)), url)
        except RuntimeError as error:
            return {"status": "failed", "line": f"[failed] click {self.page.describe(ident)}: {clip(str(error), 160)}; "
                                                f"look again"}
        kind, why = judged["kind"], judged["why"]
        if how == "right":
            kind, why, times = "watch", "a right click opens the page's own menu", 1
        elif how == "double" and kind and kind != "watch":
            return {"status": "failed", "line": f"[failed] double click {self.page.describe(ident)}: it is {kind}, and a "
                                                f"double click would press it twice; nothing was done. Click it once"}
        elif how == "double":
            times = 1
        shown = shown_name(name, facts)
        said =self._said({"do": "click", "double": how == "double", "button": how}, shown or element)
        if facts.get("tag") in ("select", "label") and not how:
            options = await self.page.on_node(ident, OPTIONS_JS)
            if options is not None:
                return {"status": "ok", "said": said, "line": f"[ok] {self.page.describe(ident)} is a list to choose "
                        f"from, not to click: type the option's words into its id; its options: {' | '.join(options)}"}
        # The control pressed and what it and the page showed just before, to say after what the press changed.
        seen: dict = {}
        press = functools.partial(self._press_control, ident, how, at, self._named_more(role, name, shown, facts), seen)
        if kind and kind != "watch":
            # A press that cannot land (covered, hidden, turned off) is not put to the person on a card; a point
            # was checked as it was judged.
            stuck = None if at else await self._cannot_land(ident, said)
            if stuck:
                return stuck
            # The card names what decided: a control under the point, or the clickable a part is of.
            on = judged["facts"]
            button = shown if (judged["id"], judged["name"]) == (ident, name) else (
                judged["name"] or on.get("text") or on.get("label") or shown)
            result = await self._outside(kind, why, judged["id"], button, on, url, element, lambda: press(said))
            if result.get("outside"):
                result["line"] += await self._changed(seen["target"], seen, result["line"])
            return {**result, "said": said}
        line, said = await self._click_free(ident, role, facts, kind, how, times, said, shown or element, url, press)
        line, still = await self._landed(line, seen)
        return {"status": "ok" if line.startswith("[ok]") else "failed", "line": line, "said": said, "still": still}

    async def _click_free(self, ident: int, role: str, facts: dict, kind: str, how: str, times: int, said: str,
                          label: str, url: str, press: Callable[..., Awaitable[str]]) -> tuple[str, str]:
        """A click with no effect outside the page, and the step as the person was told it: a link opening a new
        tab opened here, a right click or a press the gate watches watched, a choice held as a setting saved, any
        other pressed `times` times."""
        if (facts.get("link") or facts.get("away")) and how != "right":
            # A link the person could see: where it leads (and its redirects) is one of the run's sites.
            self._follow_until = time.monotonic() + FOLLOW_S
        away = await self.page.on_node(ident, BLANK_JS) if facts.get("link") and not how else None
        if away:
            self.tell(said)
            return f"{await self.page.goto(away)} (the link opens a new tab; opened here instead)", said
        choice = role in CHOICES or facts.get("type") in ("checkbox", "radio")
        if how == "right" or (kind == "watch" and not choice):
            return await self._watched(lambda: press(said), label, facts), said
        if choice:
            return await self._choosing(lambda: press(said), label, url), said
        if times > 1:
            said += SAID[self.lang]["times"].format(n=times)
        # A link or a tab leads somewhere; any other control's press is watched for what it saves to the page's
        # own site and a DELETE, never for the page's traffic to its other hosts.
        if facts.get("link") or facts.get("away") or role in ("link", "tab"):
            return await self._press_times(press, said, times), said
        return await self._watched(lambda: self._press_times(press, said, times), label, facts, HEAR_S), said

    async def _cannot_land(self, ident: int, said: str) -> dict | None:
        """Why a press on a control still on the page cannot land (covered, hidden, turned off), as the step's
        result; None when it can."""
        if not await self.page.alive(ident):
            return None
        try:
            await self.page._point(ident)
        except RuntimeError as error:
            self.tell(said)
            return {"status": "failed", "said": said,
                    "line": f"[failed] click {self.page.describe(ident)}: {clip(str(error), 160)}; look again"}
        return None

    async def _landed(self, line: str, seen: dict) -> tuple[str, bool]:
        """A click's line ended with what it changed, and whether the press landed and the page did not move: said
        so in a way that ends the pressing."""
        if not seen:
            return line, False
        line += await self._changed(seen["target"], seen, line)
        if not (line.startswith("[ok]") and line.endswith("-> no change")):
            return line, False
        chosen = any(seen.get("state", {}).get(k) for k in ("selected", "pressed", "checked", "on"))
        return line + ("; it was already chosen before the press, so what it shows is on the page now: read it there "
                       "(or read the whole page), never press it again" if chosen else
                       "; the press landed and nothing on the page changed: pressing it again will not help"), True

    def _named_more(self, role: str, name: str, shown: str, facts: dict) -> str:
        """What a click's line adds to the control: one with no name is named as the card names it, and one of
        several with the same name by the item it sits in."""
        twins = sum(1 for r, n in self.page.last.values() if r == role and fold(n) == fold(name)) > 1
        return (f" {{{clip(shown, 40)}}}" if not name and shown else "") + (
            f" (in {quote(clip(str(facts['row']), 50))})" if twins and facts.get("row") else "")

    async def _press_control(self, ident: int, how: str, at: tuple[float, float] | None, more: str, seen: dict,
                             said: str, again: bool = False) -> str:
        """One press of a clicked control, found again where the page drew it anew; the first tells the person
        `said` and keeps in `seen` what the control and the page showed before it."""
        target = await self._fresh(ident) or ident
        if not again:
            self.tell(said)
            seen.update(await self._seen(target), target=target)
        if not how and not at and (target != ident or not await self.page.alive(target)):
            # The page keeps drawing this control anew: found and pressed in one step, never by a point another
            # row may have moved under.
            line = await self.page.click_again(target)
        else:
            line = await self.page.click(target, how, *(at or (None, None)))
        here = self.page.describe(target)
        return line.replace(here, here + more, 1)

    async def _press_times(self, press: Callable[..., Awaitable[str]], said: str, times: int) -> str:
        """The same control pressed `times` times (a stepper or a calendar's arrow), found again where the page drew
        it anew; none more once a press failed or the page went elsewhere."""
        line = await press(said)
        pressed = 1
        while pressed < times and line.startswith("[ok]") and "navigated to" not in line:
            again = await press(said, again=True)
            if not again.startswith("[ok]"):
                line += f"; press {pressed + 1} did not work: {clip(again, 120)}"
                break
            pressed += 1
        return line + (f"; pressed {pressed} times" if times > 1 else "")

    async def _click_point(self, x: float, y: float, element: str) -> dict:
        """A click on a point of the view as a picture shows it, judged by the strictest of what it is a press on
        (_pressed)."""
        url = await self._url()
        try:
            judged = await self._pressed(None, x, y, url)
        except RuntimeError as error:
            return {"status": "failed", "line": f"[failed] click at {round(x)},{round(y)}: {clip(str(error), 200)}; "
                                                f"nothing was pressed"}
        kind, why, facts, role, name = (judged[k] for k in ("kind", "why", "facts", "role", "name"))
        said = self._said({"do": "click"}, (name if role not in DRAWN else "") or facts.get("text") or element)

        async def press() -> str:
            self.tell(said)
            return await self.page.click_point(x, y)
        if kind and kind != "watch":
            return {**await self._outside(kind, why, judged["id"], (name if role not in DRAWN else "")
                                          or facts.get("text") or facts.get("label") or "", facts, url, "", press),
                    "said": said}
        before = await self._seen(None)
        line = await self._watched(press, str(facts.get("text") or element), facts,
                                   PRESS_TAIL_S if kind == "watch" else HEAR_S)
        return {"status": "ok" if line.startswith("[ok]") else "failed", "line": line + await self._changed(
            None, before, line), "said": said}

    async def _drag(self, action: dict) -> dict:
        """A drag as Playwright and Stagehand take one: from a control (its id or the words it shows, `text`) or a
        point (x, y: from the control's top left, or of the view) to another control (`to`, `to_text`) or point
        (to_x, to_y), through `route` points on the way (Page.drag). Its press is judged as a click on what it
        goes down on would be, so a drag that starts on a send button asks first; any other is watched as a bare
        submission's press is, so a page that saves the move asks on a card first."""
        ends = await self._drag_ends(action)
        if isinstance(ends, dict):
            return ends
        (start, start_name), (end, end_name) = ends
        if "id" not in end and "id" in start and "x" in start:
            # to_x, to_y with no `to` are measured as x, y are: a line drawn across one drawing.
            end, end_name = {**end, "id": start["id"]}, start_name
        route = [p for p in action.get("route") or [] if isinstance(p, (list, tuple)) and len(p) == 2
                 and all(isinstance(v, (int, float)) for v in p)][:ROUTE_MAX]
        said = self._said({"do": "drag", "target": end_name}, start_name)
        url = await self._url()
        try:
            # Judged at the press and at the release alike, the strictest of the two deciding.
            judged = max([await self._pressed(start.get("id"), start.get("x"), start.get("y"), url),
                          await self._pressed(end.get("id"), end.get("x"), end.get("y"), url, release=True)],
                         key=strictness)
        except RuntimeError as error:
            return {"status": "failed", "line": f"[failed] drag: {clip(str(error), 200)}; nothing was pressed"}
        kind, why, facts = judged["kind"], judged["why"], judged["facts"]

        async def press() -> str:
            self.tell(said)
            return await self.page.drag(start, end, route)
        if kind and kind != "watch":
            return {**await self._outside(kind, why, judged["id"], (judged["name"] if judged["role"] not in DRAWN
                                                                     else "") or facts.get("text") or facts.get("label")
                                          or start_name, facts, url, "", press), "said": said}
        before = await self._seen(None)
        line = await self._watched(press, said, facts)
        return {"status": "ok" if line.startswith("[ok]") else "failed", "said": said,
                "line": line + await self._changed(None, before, line)}

    async def _drag_ends(self, action: dict) -> list[tuple[dict, str]] | dict:
        """A drag's two ends, each as Page.drag takes it ({"id"}, {"id", "x", "y"} or {"x", "y"}) with its name for
        the person; or the result when one cannot be found or is not the control named."""
        ends = []
        for ident, words, element, x, y in (
                (action.get("id"), action.get("text"), action.get("element"), action.get("x"), action.get("y")),
                (action.get("to"), action.get("to_text"), action.get("target"), action.get("to_x"), action.get("to_y"))):
            if isinstance(ident, str) and not ident.strip().isdigit():
                ident, words = None, words or ident
            at = {"x": float(x), "y": float(y)} if isinstance(x, (int, float)) and isinstance(y, (int, float)) else {}
            if ident in (None, "") and str(words or "").strip():
                found = await self.page.locate(str(words))
                if found is None:
                    return {"status": "missing", "line": f"[missing] nothing on the page shows "
                                                         f"{clip(str(words or ''), 60)!r}; look again"}
                ends.append(({"id": found, **at}, str(element or words)))
                continue
            if ident in (None, ""):
                if not at:
                    return {"status": "failed", "line": "[failed] drag needs each end as a ref, the words it shows, "
                                                        "or a point x, y (to_x, to_y)"}
                ends.append((at, SAID[self.lang]["point"]))
                continue
            fresh = await self._fresh(int(ident))
            if fresh is None:
                return {"status": "failed", "line": f"[failed] [{ident}] is not on the latest page; look again"}
            role, name = self.page.last.get(fresh, ("", ""))
            other = self._other(fresh, str(element or ""), role, name, await self.page.facts(fresh))
            if other:
                return {"status": "failed", "line": other}
            ends.append(({"id": fresh, **at}, name or str(element or "")))
        return ends

    def _theirs(self, text: str, site: str, url: str) -> bool:
        """What was typed is the person's own words of this turn (crossing.own_words), typed on a site their words
        name (crossing.named: DeepL for deepl.com), holding no identity number, address or account
        (gate.hands_over), on a page that is not a sensitive one: the page may take it to that site as the field's
        own content with no card while nothing is pressed (Holding._carries). A request a press or a choice sends is
        judged whatever it holds."""
        from .. import acting, crossing
        said = self.said()
        return (bool(site) and not acting.sensitive(url) and not gate.hands_over(text)
                and crossing.own_words(text, said) and crossing.named(site, said, site=True))

    async def _select(self, ident: int, words: str, element: str) -> dict:
        """Text selected in a control or a block of text (Page.select_text), for a page that acts on what is
        selected; it presses nothing and nothing reaches the clipboard."""
        fresh = await self._fresh(ident)
        if fresh is None:
            return {"status": "failed", "line": f"[failed] [{ident}] is not on the latest page; look again"}
        name = self.page.last.get(fresh, ("", ""))[1]
        said = self._said({"do": "select", "text": words}, name or element)
        self.tell(said)
        before = await self._seen(None)
        line = await self.page.select_text(fresh, words)
        return {"status": "ok" if line.startswith("[ok]") else "failed", "said": said,
                "line": line + await self._changed(None, before, line)}

    async def _type(self, ident: int, text: str, enter: bool, element: str, append: bool = False) -> dict:
        fresh = await self._fresh(ident)
        if fresh is None:
            return {"status": "failed", "line": f"[failed] [{ident}] is not on the latest page; look again"}
        ident = fresh
        role, name = self.page.last.get(ident, ("", ""))
        url = await self._url()
        said = self._said({"do": "type", "text": text}, name or element)
        if await self.page.secret(ident):
            # Theirs to type: the field gets the focus, and the page goes to them as for a form that wants it.
            with contextlib.suppress(Exception):
                await self.page.focus(ident)
            return {"status": "refused", "line": f"[handover] {self.page.describe(ident)} is a secret field, never "
                                                 f"typed for them; it has the focus now, and they say 继续 once it is in"}
        facts = await self.page.facts(ident)
        other = self._other(ident, element, role, name, facts)
        if other:
            return {"status": "failed", "line": other}
        self.tell(said)
        if text.strip() and not facts.get("search"):
            # What a request may not carry out of the page without the person's press; what the field held, to
            # put back if the run ends with it never let out.
            earlier = next((t for t in self.typed if t["node"] == ident and not t["out"]), None)
            before = earlier["before"] if earlier else await self.page.value(ident)
            if not self.typed:
                # From now on a picture or a script from another site could carry it out in its address.
                await self.tab.cdp("Fetch.enable", {"patterns": TYPED_WATCHED})
            site = gate.site_of(self.page.frame_url(ident) or url)
            self.typed.append({"text": text.strip(), "field": clip(name or str(facts.get("label") or ""), 40),
                               "site": site, "node": ident, "before": before, "out": False,
                               "asked": self._theirs(text, site, self.page.frame_url(ident) or url)})
        if facts.get("tag") == "select":
            line = await self._choosing(lambda: self.page.type(ident, text), name or str(facts.get("label") or ""), url,
                                        text)
        else:
            line = await self.page.type(ident, text, append=append)
            if append and self.typed and self.typed[-1]["node"] == ident:
                # What the field shows now, so the run's end can tell it is still as typed and put it back.
                self.typed[-1]["shows"] = (await self.page.value(ident)).strip()
        result = {"status": "ok" if line.startswith("[ok]") else "failed", "line": line, "said": said}
        if not enter or result["status"] != "ok":
            return result
        facts = await self.page.facts(ident)
        kind, why = gate.classify("enter", name, role, facts, url)
        if kind and kind != "watch":
            outside = await self._outside(kind, why, ident, f"Enter in {name or 'the field'}", facts, url, element,
                                          lambda: self.page.press("Enter"))
            outside["line"] = f"{line}\n{outside['line']}"
            return {**outside, "said": said}
        entered = await self._watched(lambda: self.page.press("Enter"), str((facts.get("form") or {}).get("button") or "")
                                      or f"Enter in {name or 'the field'}", facts, PRESS_TAIL_S if kind == "watch" else HEAR_S)
        return {**result, "line": f"{line}\n{entered}"}

    async def _press(self, key: str) -> dict:
        """A key or chord, as pageinput.chord spells it, through the gate's chord rule: one ending in Enter or Space is
        that key on the control with the focus, a shortcut is watched as a bare submission's press is, and the
        clipboard is refused."""
        said = self._said({"do": "press", "key": key})
        ident = await self.page.active()
        facts = await self.page.facts(ident) if ident is not None else {}
        mode, why = gate.chord(key, bool(facts.get("textEntry")))
        if mode == "refuse":
            return {"status": "failed", "line": f"[failed] press {key}: the clipboard is the person's own and is never "
                                                f"used; nothing was pressed. Type the words instead"}
        # A character keyed into a secret field is typing it: theirs, as for `type`.
        if (ident is not None and len(key.rsplit("+", 1)[-1]) == 1 and not re.match(r"(Control|Alt|Meta)\+", key)
                and await self.page.secret(ident)):
            return {"status": "refused", "line": f"[handover] {self.page.describe(ident)} is a secret field, never "
                                                 f"typed for them; they say 继续 once it is in"}
        kind = "watch" if mode == "watch" else ""
        if mode in ("enter", "click") and ident is not None:
            url = await self._url()
            role, name = self.page.last.get(ident, (facts.get("role") or facts.get("tag") or "", ""))
            kind, why = gate.classify(mode, name, role, facts, url)
            if kind and kind != "watch":
                async def press() -> str:
                    self.tell(said)
                    return await self.page.press(key)
                return {**await self._outside(kind, why, ident, f"{key} in {name or role}", facts, url, "", press),
                        "said": said}
        self.tell(said)
        before = await self._seen(None)
        line = await (self._watched(lambda: self.page.press(key), str((facts.get("form") or {}).get("button")
                                                                      or facts.get("text") or facts.get("label") or key),
                                    facts, PRESS_TAIL_S if kind == "watch" else HEAR_S)
                      if kind == "watch" or mode in ("enter", "click") else self.page.press(key))
        return {"status": "ok", "line": line + await self._changed(None, before, line), "said": said}
