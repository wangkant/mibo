"""The feed's routes: the 推荐记录 list, the pet's card, the first run's topics, platforms and sample finds, the
person's reactions and their undo, and the situation table's view (feed.py holds the events and the ranking)."""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import Request

from .. import activity, langs, life, profile, situation
from .. import taste as model
from . import feed

ERRORS: frozenset[str] = frozenset({"feed_action", "feed_cursor", "feed_topics", "feed_platforms", "feed_no_source",
                                    "situation_invalid", "feed_format", "feed_snooze"})
PLAY_MAX_S = 24 * 3600
# How long the first run's round of sample finds waits for a sources round still out (onboard.js says so while
# it waits).
FIRST_WAIT_S = 30
# An earlier find's title in a reason, at most this many characters.
REASON_TITLE = 32


class Feed:
    def __init__(self, workspace):
        self.ws = workspace

    def _events(self) -> list:
        return feed.events(self.ws._runtime())

    def page(self, limit: int, before: str, kept: bool) -> dict:
        """One page of `feed.shown` (`kept`: of the liked) for the app's 推荐记录, each thing as the main chat draws
        it, at the time it was shown or liked: with the chip and the topic it had in the chat or on the pet's
        card, else with those it would have now, its place for the list's reactions, and the sentence of why it
        was shown (`reason`): what its showing kept (recommend.facts), or for one shown before that was kept,
        the same read from its showing's event, the ranking's terms in the shown table, the character's line in
        the chat and the person's history until then."""
        from .. import recommend
        runtime, events = self.ws._runtime(), self._events()
        library = self.ws._library()
        got = feed.shown(library, events, kept, limit, before)
        chat = {m["card"]["id"]: m for m in self.ws._main.shared()}
        leans = profile.load(runtime, False)["leans"]
        name, _, lang = profile.character(self.ws.home, self.ws.config())
        why = recommend.Why(runtime, feed.load_topics(runtime), events, life.clock(), lang)
        # Each thing's showing: its first "seen", else its first event (a page opened in the app's browser).
        showing: dict[str, list] = {}
        for event in events:
            if event[1] not in showing or (event[2] == "seen" and showing[event[1]][2] != "seen"):
                showing[event[1]] = event
        tops = {ident: row.get("top") or [] for ident, row in model.first_shown(
            runtime, [item.id for _, _, item in got["rows"]]).items()}

        def title_of(ident: str) -> str:
            found = library.get(ident)
            title = " ".join(found.title.split()) if found else ""
            return title if len(title) <= REASON_TITLE else title[:REASON_TITLE - 1] + "…"

        cards = []
        for at, rank, item in got["rows"]:
            card = life.said(item).get("card")
            if card is None:
                continue
            shaped = feed.shape(item, {})
            message = chat.get(item.id, {})
            had = message.get("card") or feed.on_card.get(item.id) or {}
            now = why.of(shaped, item)
            topic = had.get("topic") or now["topic"]
            chip = had.get("why") or now["why"]
            if chip and chip.get("key"):
                chip = {**chip, "lean": leans.get(chip["key"])}
            event = showing.get(item.id)
            extra = event[5] if event and len(event) > 5 else {}
            said = extra.get("why")
            if said is None:
                snap = extra.get("f") or {}
                # The chat's line, unless it is only the title the message falls back to.
                line = message.get("text") or ""
                line = "" if item.title.startswith(line.rstrip("…")) else line
                said = recommend.facts(item, snap, extra.get("p", ""), extra.get("s", ""),
                                       recommend.term_of(tops.get(item.id, []), bool(snap.get("guess"))), line,
                                       model.history(events, event[0] - 0.001) if event else {})
            card.update(why=chip, topic=topic, rank=rank, slot=had.get("slot", ""), surface="list",
                        reason=why.told(said, item, shaped, name, title_of),
                        at=datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds"))
            cards.append(card)
        return {"items": cards, "next": got["next"]}

    async def next(self, now: bool = False) -> dict:
        """The character's choice for the card (`recommend`), when the pacing says this is a moment for one
        (pacing.py), or `now` as the pet's menu and the card's "Another" ask: then the ranking's next comes
        at once when no choice waits, its sentence after it (`line`). Otherwise nothing while one is being
        chosen, and the pet is told to look again once it is (news)."""
        if not now and not await self.ws.pace.due("card"):
            return {"item": None}
        chosen = await self.ws.chooser.take("card", now)
        if chosen is None:
            return {"item": None}
        feed.on_card[chosen[0]["id"]] = chosen[0]
        return {"item": chosen[0]}

    def numbers(self) -> dict:
        runtime = self.ws._runtime()
        return {**model.numbers(runtime), "calls": profile.calls(runtime)}

    def situation(self) -> dict:
        return situation.view(self.ws._runtime())

    def set_situation(self, payload: dict) -> dict:
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("situation_invalid")
        situation.set_value(self.ws._runtime(), name, payload.get("value"))
        return self.situation()

    def first(self) -> dict:
        runtime = self.ws._runtime()
        return {"items": feed.first_round(self.ws._library(), self._events(), life.clock(), feed.load_topics(runtime),
                                          feed.load_platforms(runtime))}

    def _paced(self, ident: str, action: str, surface: str, end: str) -> None:
        """What the pacing hears: the card brought something, or how the last thing brought ended."""
        if surface == "card" and action == "seen":
            self.ws.pace.shown("card", ident)
        elif surface in ("card", "chat") and action == "end":
            self.ws.pace.ended(ident, end, surface)
        elif surface == "chat" and action in ("open", "like", "play", "read", "skip", "hide_source"):
            how = "close" if action in ("skip", "hide_source") else "like" if action == "like" else "open"
            self.ws.pace.ended(ident, how, "chat")

    def interests(self, lang: str) -> dict:
        """The topics and platforms chosen, and those offered in `lang` (platformsOffered: feed.offered_platforms)."""
        runtime = self.ws._runtime()
        lang = langs.normalize(lang) or langs.normalize(self.ws.config().get("AGENT_LANG")) or "en"
        return {"topics": feed.load_topics(runtime), "suggested": feed.suggested(lang),
                "platforms": feed.load_platforms(runtime), "platformsOffered": feed.offered_platforms(runtime, lang)}

    def choose(self, payload: dict) -> dict:
        """The topics, and the platforms when the page sent them (none sent leaves those chosen before)."""
        runtime = self.ws._runtime()
        topics = feed.clean_topics(payload.get("topics"))
        chosen = feed.clean_platforms(payload["platforms"]) if "platforms" in payload else None
        feed.keep_topics(runtime, topics)
        if chosen is not None:
            feed.keep_platforms(runtime, chosen)
        return self.interests(payload.get("lang") or "")

    async def react(self, payload: dict) -> dict:
        action = payload.get("action")
        if action not in feed.ACTIONS:
            raise ValueError("feed_action")
        item = self.ws._item(payload)
        if action == "hide_source" and not item.source:
            raise ValueError("feed_no_source")
        surface, rank, slot = payload.get("surface") or "", payload.get("rank"), payload.get("slot") or ""
        # Seconds: played, read in the app's browser, or how long the card was out.
        seconds = payload.get({"read": "read_s", "end": "shown_s"}.get(action, "play_s")) or 0
        end = payload.get("end") if action == "end" else ""
        # "Not interested" with what it was about: a skip that says so, which counts as more than a plain one.
        # About its topic, `key` is the feature that then leans to less (topic:, like: or subj:).
        said = payload.get("said")
        if said is not None:
            if action != "skip" or not isinstance(said, dict) or said.get("about") not in feed.SAID_ABOUT:
                raise ValueError("feed_action")
            key = said.get("key") if said["about"] == "topic" else None
            if said["about"] == "topic" and not (isinstance(key, str) and len(key) <= 120
                                                 and key.partition(":")[0] in ("topic", "like", "subj")):
                raise ValueError("feed_action")
            said = {"about": said["about"], "words": ""}
            if key:
                # What the lean was before, for an undo to put back.
                was = await asyncio.to_thread(lambda: profile.load(self.ws._runtime(), False)["leans"].get(key))
                said.update(key=key, was=was)
        if ((surface not in model.SURFACES and surface != "") or slot not in ("", "model", "explore", "character")
                or (rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank < 0))
                or not isinstance(seconds, (int, float)) or isinstance(seconds, bool)
                or not 0 <= seconds <= PLAY_MAX_S or (action in ("play", "read") and not seconds)
                or (action == "end" and end not in feed.ENDS)):
            raise ValueError("feed_action")
        if end == "close" and seconds < feed.QUICK_S:
            end = "quick"
        elif end == "timeout" and await asyncio.to_thread(activity.idle) >= seconds:
            # No key or mouse input the whole time it was out: the person was away, and it says nothing.
            end = "away"
        played = 0.0 if action == "end" else float(seconds)
        kept = await asyncio.to_thread(feed.remember, self.ws._runtime(), item, action, surface=surface, rank=rank,
                                       play_s=played, slot=slot, end=end, shown_s=float(seconds) - played,
                                       said=said, line=feed.on_card.get(item.id, {}).get("line", ""))
        await asyncio.to_thread(self._paced, item.id, action, surface, end)
        if action == "seen" and surface == "card":
            self.ws.chooser.shown(item.id)
        elif action in ("like", "unlike"):
            # A liked thing is a kept one: the days and the chat see the same choice.
            await self.ws.mark_item(item.id, "keep", action == "like")
        elif action in ("skip", "hide_source"):
            topical = bool(said) and said["about"] == "topic"
            # The chat's card stays folded to the line that says which no it was.
            self.ws.fold_card(item.id, "topic" if topical else action)
            if kept and topical:
                await asyncio.to_thread(profile.edit, self.ws._runtime(), {"leans": {said["key"]: -1}})
            if kept and (topical or action == "hide_source"):
                self.ws.chooser.again()
        elif end == "known":
            self.ws.fold_card(item.id, end)
        return {"ok": True}

    async def undo(self, payload: dict) -> dict:
        """Take back a no said on a card (the pet's, within a few seconds; the chat's folded line): the thing
        is as it was before it, and a card of it in the chat unfolds."""
        item = self.ws._item(payload)
        await asyncio.to_thread(feed.take_back, self.ws._runtime(), item)
        self.ws.fold_card(item.id, "")
        self.ws.chooser.again()
        return {"ok": True}

    async def lean(self, payload: dict) -> dict:
        """More or less of what a card's reason names, from the chip under its site: the lean on that
        feature (profile "leans", as Settings sets it), `to` 1, -1, or None for neither."""
        await asyncio.to_thread(profile.edit, self.ws._runtime(), {"leans": {payload.get("key"): payload.get("to")}})
        self.ws.chooser.again()
        return {"ok": True}


def mount(app, workspace, body) -> None:
    panel = Feed(workspace)

    @app.get("/api/feed")
    async def feed_page(limit: int = feed.LIMIT, before: str = "", kept: bool = False):
        return await asyncio.to_thread(panel.page, limit, before, kept)

    @app.get("/api/feed/next")
    async def feed_next(now: bool = False):
        return await panel.next(now)

    # Do not disturb, from the pet's menu: nothing is brought until it ends (pacing.py). In seconds left.
    @app.get("/api/feed/snooze")
    async def feed_snoozed():
        return {"left": max(0.0, workspace.pace.snoozed - life.clock())}

    @app.post("/api/feed/snooze")
    async def feed_snooze(request: Request):
        on = (await body(request)).get("on")
        if not isinstance(on, bool):
            raise ValueError("feed_snooze")
        return {"left": max(0.0, workspace.pace.snooze(on) - life.clock())}

    # The first run's round of sample finds, shown one at a time. On a fresh install the library is still
    # empty, or holds only the first round's language defaults, when the topics are chosen: while a sources
    # round is out (one was asked for as the topics were saved) its finds are waited for, FIRST_WAIT_S at most.
    @app.get("/api/feed/first")
    async def feed_first():
        started = life.clock()
        while app.state.sources.busy and life.clock() - started < FIRST_WAIT_S:
            await asyncio.sleep(1)
        return await asyncio.to_thread(panel.first)

    @app.get("/api/feed/numbers")
    async def feed_numbers():
        return await asyncio.to_thread(panel.numbers)

    # The situation table's view and the person's corrections (see `situation`).
    @app.get("/api/situation")
    async def situation_view():
        return await asyncio.to_thread(panel.situation)

    @app.post("/api/situation")
    async def situation_set(request: Request):
        return await asyncio.to_thread(panel.set_situation, await body(request))

    @app.post("/api/feed/react")
    async def feed_react(request: Request):
        return await panel.react(await body(request))

    @app.post("/api/feed/undo")
    async def feed_undo(request: Request):
        return await panel.undo(await body(request))

    @app.post("/api/feed/lean")
    async def feed_lean(request: Request):
        return await panel.lean(await body(request))

    # The sentence for a find the card showed before it was written ("more" on the item): "" with `wait`
    # while it is on its way.
    @app.get("/api/feed/line")
    async def feed_line(id: str = ""):
        return workspace.chooser.line(id)

    @app.get("/api/feed/interests")
    async def feed_interests(lang: str = ""):
        return await asyncio.to_thread(panel.interests, lang)

    @app.post("/api/feed/interests")
    async def feed_interests_choose(request: Request):
        chosen = await asyncio.to_thread(panel.choose, await body(request))
        # The sources go out for the topics at once, not at the next half hour: the first run's finds and
        # the first day's cards come from this round (catalog.pulls weighs the sources by the topics).
        app.state.sources.ask(even_if_running=True)
        return chosen
