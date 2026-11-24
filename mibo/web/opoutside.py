"""A press with an effect outside, for operate.Hands: what it is judged by (the strictest of everything it could be
a press on), the person's card or the reviewer before it, exactly one press, and a look for its result; a bare
submission or a choice watched for what it sends. A mixin of operate.Hands: its state is set in Hands.__init__."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable

from . import gate
from .opcarry import shape, squeeze
from .pagewords import clip, fold

logger = logging.getLogger("mibo.web")

# The roles a look gives drawn parts (pageops drawn_lines), whose words are colours and shapes, never a name.
DRAWN = ("shape", "box", "drawing")
# How long after an action a request it set off is waited for; after a confirmed press, how long its own
# requests are let out.
HEAR_S = 0.4
PRESS_TAIL_S = 1.0
# How long a press is watched for its result.
PROOF_S = 12.0

# A field typed into, given back what it held before, unless someone changed it since: (typed, before).
RESTORE_JS = r"""function(pair) {
  const [typed, before] = pair;
  const e = this.nodeType === 1 ? this : this.parentElement;
  if (!e || !e.isConnected || ((e.isContentEditable ? e.innerText : e.value) || '').trim() !== typed) return false;
  if (e.isContentEditable) e.innerText = before;
  else Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e), 'value').set.call(e, before);
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}"""


def item(facts: dict) -> str:
    """The item a control acts on as the card quotes it, with its counts and spaces aside."""
    return re.sub(r"[\d\s.,]+", "", str(facts.get("row") or ""))


def strictness(judged: dict) -> int:
    """How strictly a press is held, for the strictest of what it is a press on to decide: a floor kind (order,
    delete, account, grant), then a press in another site's frame, then outward, watch and free."""
    from .. import acting
    kind = judged["kind"]
    if kind in acting.HARD:
        return 4
    if judged["why"] == gate.FRAME_WHY:
        return 3
    return 2 if kind not in ("", "watch") else 1 if kind == "watch" else 0


def reading(kind: str, does: str) -> str:
    """The card's word for an act: the reviewer's reading of an outward act, else the gate's own ("press" for an
    outward act nothing read)."""
    if does in ("send", "comment", "like", "post", "submit"):
        return does
    if does == "follow":
        return "like"
    return "press" if kind == "outward" else kind


class Outside:
    """Presses with an effect outside, for operate.Hands."""

    async def _choosing(self, act: Callable[[], Awaitable[str]], field: str, url: str, value: str = "") -> str:
        """A box ticked, a radio or an option chosen: a post it sets off (a settings page that saves as it
        changes) is held as an account change, for the card."""
        self._choice = {"text": f"{field}：{value}" if value else field, "field": field, "site": gate.site_of(url),
                        "out": False, "choice": True}
        try:
            line = await act()
            await asyncio.sleep(HEAR_S)
        finally:
            self._choice = None
        return line

    def _fields(self, facts: dict) -> str:
        """The filled fields a press sends, one a line, as the card lists them: 就诊日期：2026-12-05."""
        colon = "：" if self.lang == "zh" else ": "
        return "\n".join(f"{c}{colon}{v}" if c else v for c, v in facts.get("fields") or [])

    async def _watched(self, act: Callable[[], Awaitable[str]], button: str, facts: dict,
                       tail: float = PRESS_TAIL_S) -> str:
        """A press code could not sort, or a bare submission (gate's "watch": a form sent by GET, a shortcut, a
        drag): what leaves on it within `tail` and is its act (`_submits`: a DELETE, or a request to the page's own
        site that is not a GET) is held for its card, which act shows next with the fields it sends; nothing of the
        kind leaves, no card. Once the page's own question about it had a
        yes on its card, the press is the person's."""
        if self._again is not None:
            return await act()
        sites = {gate.site_of(await self._url()), *([gate.site_of(facts["form"]["action"])]
                                                    if (facts.get("form") or {}).get("action") else [])}
        self._watching = {"watch": True, "button": clip(" ".join(button.split()), 40), "field": "", "out": False,
                          "text": self._fields(facts), "sites": sites}
        try:
            line = await act()
            await asyncio.sleep(tail)
        finally:
            self._watching = None
        return line

    async def _judged(self, ident: int, role: str, name: str, facts: dict, url: str) -> tuple[str, str]:
        """The gate's kind for a press on one control the last look lists, by the control itself: its role, its name
        and its facts. A drawn part is judged by its own name and label, never by the colour and shape words the
        look gives the model, and one with none that hears a press asks as a press nothing reads."""
        if role in DRAWN:
            kind, why = gate.classify("click", "", role, facts, url)
            if not kind and not (facts.get("label") or facts.get("tip")) and await self.page.handled(ident):
                return "outward", "a drawn part with no name that answers a press"
            return kind, why
        return gate.classify("click", "" if role == "text" and facts.get("text") else name, role, facts, url)

    async def _pressed(self, ident: int | None, x: float | None, y: float | None, url: str,
                       release: bool = False) -> dict:
        """What a press is judged by: the strictest of everything it could be a press on. That is the ref, and with
        a point (x, y from the ref's top left, or of the view with no ref; a drag's release always has one) every
        control the last look lists from the element there up to the body (pageops.under), a drawn part with the
        control it is drawn in; a part of a split clickable brings the clickable round it. A point in another
        site's frame is held for the card (gate.FRAME_WHY); one on nothing listed asks as a press nothing reads when
        something there hears a press, and is free when nothing does. {"id", "facts", "role", "name", "kind",
        "why"} of the one that decides (strictness); raises why the point cannot land."""
        listed = [] if ident is None else [ident]
        found = []
        if x is not None or release:
            p = await self.page.at(ident, x, y, press=not release)
            hit, frame, path = await self.page.under(p["x"], p["y"])
            if hit is None:
                raise RuntimeError("nothing is there to press")
            if frame:
                found.append({"id": hit, "facts": await self.page.facts(hit), "role": "", "name": "",
                              "kind": "outward", "why": gate.FRAME_WHY})
            elif not path:
                heard = await self.page.handled(hit)
                found.append({"id": hit, "facts": await self.page.facts(hit), "role": "", "name": "",
                              "kind": "outward" if heard else "",
                              "why": "a press on what the look does not list, which answers a press" if heard
                              else "nothing there answers a press"})
            listed = path + [i for i in listed if i not in path]
        for i in listed:
            role, name = self.page.last.get(i, ("", ""))
            facts = await self.page.facts(i)
            kind, why = await self._judged(i, role, name, facts, url)
            found.append({"id": i, "facts": facts, "role": role, "name": name, "kind": kind, "why": why})
            if i in self.page.outer:
                # A part of a clickable split into parts: the press is the clickable's too, by its words and facts.
                whole = await self.page.facts(self.page.outer[i])
                kind, why = gate.classify("click", "", "clickable", whole, url)
                found.append({"id": i, "facts": facts, "role": role, "name": whole.get("text") or name,
                              "kind": kind, "why": f"a part of a clickable: {why}"})
        return max(found, key=strictness)

    async def _outside(self, kind: str, why: str, ident: int, button: str, facts: dict, url: str, element: str,
                       press: Callable[[], Awaitable[str]]) -> dict:
        """An action with an effect outside: the person's press on a card first (unless they let this kind
        through on this site, at the app, or the reviewer passed it), then exactly one press, then a look
        for its result. In read only nothing is pressed."""
        from .. import acting
        said = str(facts.get("said") or "")
        if acting.decide(self.mode(), kind, url) == "refuse":
            return {"status": "failed", "kind": kind,
                    "line": f"[read-only] {kind} ({button[:40]}): the person set the browser to read only, so nothing "
                            f"was pressed; read and tell them, or ask_person"}
        once = (kind, shape(url), button, said, self.page.near.get(ident, ""))
        words = (kind, shape(url), str(facts.get("to") or ""), squeeze(said))
        done = await self._done_before(once, words, kind, button, said)
        if done:
            return done
        # A form that still wants their password, card or code goes to them before any card.
        missing = await self.page.secret_unfilled(ident)
        if missing is not None:
            return {"status": "refused", "kind": kind,
                    "line": f"[handover] the form needs their own {missing or 'password'} first, a secret field "
                            f"never typed for them; it has the focus now, and they say 继续 once it is in"}
        card, typed = self._outside_card(kind, why, button, facts, url, element)
        kind = card["kind"]
        kept = self.kept.get(card["act"])
        if kept is not None and not kept.get("yes"):
            return {"status": "declined", "kind": kind, "line": f"[declined] the person said no to {kind} "
                                                                f"({button[:40]}) before in this turn; nothing was pressed"}
        skipped, decision, passed = await self._decide_outside(card, kept, why, facts, typed)
        kind = card["kind"]
        if decision == "turned":
            return {"status": "declined", "kind": kind, "line": f"[declined] {kind} ({button[:40]}): {passed}; "
                                                                "nothing was pressed"}
        if not skipped and decision not in ("go", "kept"):
            ended, ident = await self._asked_outside(card, ident, facts)
            if ended:
                return ended
        seen_before = await self._count(said)
        line = await self._let_out(press, ident, url, said, kind)
        if not line.startswith("[ok]"):
            return {"status": "failed", "kind": kind, "line": line}
        self.confirmed = True
        # What was typed before this press went with it: the person confirmed the form it sits in.
        for t in self.typed:
            t["out"] = True
        proof = await self._proof(ident, said, seen_before) if said else ""
        if kind == "like":
            proof += "; a like is a toggle: pressing it again would undo it"
        self.pressed[once] = await self._shown()
        if said:
            self.sent.add(words)
        how = ("let through by the person's setting for this site" if skipped else passed if decision == "go"
               else "confirmed by the person" + (" before in this turn" if decision == "kept" else ""))
        return {"status": "ok", "kind": kind, "outside": True,
                "line": f"{line} ({kind}, {how}; pressed once){proof}"}

    async def _done_before(self, once: tuple, words: tuple, kind: str, button: str, said: str) -> dict | None:
        """A press made once in this run on the person's word, on a page that has not changed since (a like at
        all), or the same words to the same place: not made again. The result, or None for a press not made yet."""
        if once in self.pressed and (kind == "like" or self.pressed[once] == await self._shown()):
            return {"status": "ok", "kind": kind, "proven": True,
                    "line": f"[already] {kind} on {button[:40]!r} was pressed once in "
                    f"this run, on the person's word, and nothing on the page has changed since; pressing it again "
                    f"would {'undo it' if kind == 'like' else 'do it twice'}. It is done: say done, or go on with "
                    f"what is left of the task"}
        if not (said and words in self.sent):
            return None
        # The same words to the same place a second time: they went once, on the person's yes. What was typed again
        # goes back out of the box, so nothing is left there to send by itself.
        for t in [t for t in self.typed if not t["out"] and squeeze(t["text"]) == squeeze(said)]:
            try:
                await self.page.on_node(t["node"], RESTORE_JS, [t.get("shows", t["text"]), t["before"]])
            except Exception:
                logger.debug("[Agent] operate: a field typed into twice was gone before it could be put back")
            self.typed.remove(t)
        return {"status": "ok", "kind": kind, "proven": True,
                "line": f"[already] {clip(said, 60)!r} went out once in this run ({kind}), on the person's word; "
                f"sending it again would put it there twice, so nothing was pressed and the box was put back. "
                f"It is done: say done, or go on with what is left of the task"}

    def _outside_card(self, kind: str, why: str, button: str, facts: dict, url: str,
                      element: str) -> tuple[dict, list[str]]:
        """The card for a press with an effect outside, with the act it is (one question for it in this turn), and
        whatever else typed on this site may leave with it, as "field: text" lines."""
        from .. import acting
        site = gate.site_of(url)
        said = str(facts.get("said") or "")
        card = {"id": secrets.token_urlsafe(8), "kind": kind, "site": site, "url": url, "button": button[:120],
                "to": str(facts.get("to") or "")[:80], "label": element[:120], "why": why[:200],
                # A like or a delete has no words of its own: the card quotes the item it acts on; a form, the filled
                # fields it sends.
                "text": (said or (str(facts.get("row") or "") if kind in ("like", "delete") else
                                  self._fields(facts) if kind in ("submit", "account", "order") else ""))[:2000],
                "skippable": kind in gate.SKIPPABLE and not acting.sensitive(url) and why != gate.FRAME_WHY}
        # Whatever was typed on this site in this run and not let out yet may leave with the press, not only the
        # box beside the button: the reviewer and code's floor (an address or number they never gave) see it all.
        typed = [f"{t['field']}: {t['text']}" for t in self.typed if not t["out"] and t["site"] == site
                 and squeeze(t["text"]) not in squeeze(card["text"])]
        if kind not in acting.HARD and gate.hands_over("\n".join([card["text"], *typed])):
            # Handing over an identity number, a home address or a bank account is costly, whatever the button says.
            card["kind"], card["skippable"] = "grant", False
        if card["kind"] == "order" and facts.get("money"):
            card["amount"] = str(facts["money"])[:40]
        # The act, for its one question in this turn: the person's answer to it before stands.
        card["act"] = ("outside", card["kind"], site, button[:120], said, card["to"])
        return card, typed

    async def _decide_outside(self, card: dict, kept: dict | None, why: str, facts: dict,
                              typed: list[str]) -> tuple[bool, str, str]:
        """Whether the person lets this kind through on this site with no card, and what decides the press: "kept"
        (their yes before in this turn), "ask" (the card), or the reviewer's "go" or "turned" with its words. Unless
        let through, the card is set to the act as the reviewer read it."""
        from .. import acting
        kind, site, button = card["kind"], card["site"], card["button"]
        skipped = card["skippable"] and self.attended() and self.allowed.skips(site, kind)
        # A press or Enter in another site's frame is the floor: the card, never the reviewer. A yes to a costly act
        # before carries no second one (cardwait.reaches).
        decision, passed, does = ("kept", "", "") if kept and kind not in acting.HARD else ("ask", "", "") if (
            skipped or why == gate.FRAME_WHY) else await self._decided(
            kind, site, {"target": [card["to"]] if card["to"] else [],
                         "text": "\n".join([card["text"], *typed]).strip()[:2000], "page_says": button[:120],
                         "fields": ["password"] if (facts.get("form") or {}).get("password") else []},
            where=card["url"])
        if not skipped:
            # The card names the act as the reviewer read it; 始终允许 is offered for that reading.
            kind = card["kind"] = reading(kind, does)
            card["skippable"] = kind in gate.SKIPPABLE and not acting.sensitive(card["url"]) and why != gate.FRAME_WHY
        return skipped, decision, passed

    async def _asked_outside(self, card: dict, ident: int, facts: dict) -> tuple[dict | None, int]:
        """The card put to the person, and on their yes what it showed checked again on the page: (the result when
        the press is not made, else None; the control's id now, a control drawn again being found again)."""
        kind, button, said = card["kind"], card["button"], str(facts.get("said") or "")
        try:
            card["picture"] = await self.page.screenshot()
        except Exception:
            card["picture"] = ""
        # The control, for a ring that stays on it while the card waits.
        card["node"] = ident
        answer = await self.ask(card)
        if answer is None:
            return {"status": "declined", "kind": kind,
                    "line": f"[declined] nobody answered the card for {kind} ({button[:40]}); nothing was pressed"}, ident
        if answer.get("waiting"):
            # Its time ran out with the card up: the act waits on it, and the card stays answerable.
            return {"status": "waiting", "kind": kind, "result": answer["waiting"],
                    "line": f"[waiting] the card for {kind} ({button[:40]}) waits for the person's answer; "
                            f"nothing was pressed"}, ident
        self.kept[card["act"]] = {"yes": bool(answer.get("yes"))}
        if not answer.get("yes"):
            # What was typed for it stays unsent: the run puts it back when it ends.
            for t in self.typed:
                if not t["out"]:
                    t["no"] = True
            return {"status": "declined", "kind": kind,
                    "line": f"[declined] the person said no to {kind} ({button[:40]}); nothing was pressed"}, ident
        if answer.get("never") and card["skippable"]:
            self.allowed.set(card["site"], kind, True)
        # What the card showed must still be what is pressed (a control drawn again is found again).
        again = None
        with contextlib.suppress(Exception):
            ident = await self._fresh(ident) or ident
            again = await self.page.facts(ident)
        # The words, the recipient and the item it acts on (its numbers aside: a live count moves) all as shown.
        if again is None or str(again.get("said") or "") != said or str(again.get("to") or "") != str(
                facts.get("to") or "") or (kind in ("like", "delete") and item(again) != item(facts)) or (
                not said and kind in ("submit", "account", "order") and self._fields(again) != self._fields(facts)):
            return {"status": "failed", "kind": kind,
                    "line": "[changed] the page changed since the card; nothing was pressed, look again"}, ident
        return None, ident

    async def _let_out(self, press: Callable[[], Awaitable[str]], ident: int, url: str, said: str, kind: str) -> str:
        """The one press, and what the person let out goes out: this press's own site's requests, a post once one
        carries the card's words (a page that swaps them as the button goes down sends nothing). A press in a frame
        from another site sends to that frame's site. The press's line, or a [changed] line when what it sent was
        stopped."""
        self._pressing = {"site": gate.site_of(self.page.frame_url(ident) or url), "said": said, "matched": False,
                          "aside": [], "kind": kind}
        try:
            line = await press()
            await asyncio.sleep(PRESS_TAIL_S)
        finally:
            pressed, self._pressing = self._pressing, None
        swapped = bool(said and not pressed["matched"] and pressed["aside"])
        for params in pressed["aside"]:
            await self.tab.cdp("Fetch.failRequest" if swapped else "Fetch.continueRequest",
                               {"requestId": params["requestId"], **({"errorReason": "BlockedByClient"} if swapped else {})})
        if swapped:
            return ("[changed] what the page sent on the press did not carry the words the card showed; it was "
                    "stopped and nothing went. Look again")
        return line

    async def _shown(self) -> int:
        try:
            return hash(await self.page.visible_text())
        except Exception:
            return 0

    async def _count(self, said: str) -> int:
        if not said:
            return 0
        try:
            return (await self.page.visible_text()).count(fold(said).strip()[:200])
        except Exception:
            return 0

    async def _proof(self, ident: int, said: str, seen_before: int) -> str:
        """Sent is not done: the box emptied, or the words showing once more on the page."""
        start = time.monotonic()
        while time.monotonic() - start < PROOF_S:
            if await self._count(said) > seen_before:
                return f"; the page now shows {said[:60]!r}"
            try:
                if not str((await self.page.facts(ident)).get("said") or ""):
                    return "; the box is empty again"
            except Exception:
                pass
            await asyncio.sleep(1.0)
        return "; not seen on the page yet: look before saying it went through, and never press again"
