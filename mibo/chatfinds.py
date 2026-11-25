"""What the character found, in the main chat: the share step that brings one at its own pace, a find a reply
brought or the person answered, and the cards that keep their choices. A part of the page's Workspace
(workspace.py), which gives it the main chat, the chat lock and the character."""
from __future__ import annotations

import asyncio
import contextlib
import re
import traceback
from datetime import datetime
from pathlib import Path

from . import life, quiet
from .library import Library

# What the character found comes into the main chat one at a time, the character's own choice
# (recommend), when the pacing says it is a moment for one (pacing.py, as for the pet's card).
# Seconds between the share loop's looks.
SHARE_EVERY_S = 300
# A thing the character saw, as the library names it.
ITEM_ID = re.compile(r"[0-9a-f]{16}")


class ChatFinds:
    """The finds' side of the Workspace, on its main chat (`_main`, `_save_chat`, `history`), its chat lock, its
    runtime folder, the character, the pacing and the chooser."""

    async def _chat_finds(self, items: list, entries: list, answered: dict | None = None) -> None:
        """What a reply did with finds: one it brought is seen in the feed and told, as the share step's
        are, and what the person said of one is kept as their reaction from the chat (feed.remember).
        `answered`: the find this message of theirs answers, which is a reaction to it by itself."""
        from .panels import feed
        runtime = self._runtime()
        item = self._library().get(answered["id"]) if answered else None
        if item is not None:
            await asyncio.to_thread(feed.remember, runtime, item, "talk", surface="chat")
        for entry in entries:
            ident = (entry.get("card") or {}).get("id")
            item = self._library().get(ident) if ident else None
            if item is not None:
                await asyncio.to_thread(self.pace.shown, "chat", item.id)
                # Why it was shown is what the reply said of it.
                await asyncio.to_thread(feed.remember, runtime, item, "seen", surface="chat", rank=0,
                                        line=str(entry.get("text") or ""))
                await self.mark_item(item.id, "told")
        for said in (f for i in items for f in i.get("feedback") or [] if isinstance(f, dict)):
            item = self._library().get(str(said.get("id") or ""))
            if item is not None:
                await self._reaction(runtime, item, said)

    async def _reaction(self, runtime: Path, item: life.Item, said: dict) -> None:
        """What the person said in the chat of one find, kept as their reaction to it."""
        from .panels import feed
        liked = said.get("liked") is True
        # "Not this source" is the feed's "less like this source".
        action = "like" if liked else "hide_source" if said.get("about") == "source" and item.source else "skip"
        words = {"about": str(said.get("about") or "")[:20], "words": str(said.get("words") or "")[:120]}
        await asyncio.to_thread(feed.remember, runtime, item, action, surface="chat", said=words)
        await asyncio.to_thread(self.pace.ended, item.id, "like" if liked else "close", "chat")
        if liked:
            await self.mark_item(item.id, "keep", True)
        else:
            self.fold_card(item.id, action)

    def _library(self) -> Library:
        return Library(self._runtime())

    def _item(self, payload) -> life.Item:
        ident = str((payload or {}).get("id") or "")
        item = self._library().get(ident) if ITEM_ID.fullmatch(ident) else None
        if item is None:
            raise ValueError("item_gone")
        return item

    def _main_cards(self, ident: str) -> list[dict]:
        """The cards of one find in the main chat."""
        return [m["card"] for m in self._main.shared() if m["card"]["id"] == ident]

    async def mark_item(self, ident: str, action: str, kept: bool = True) -> dict:
        """Keep, dismiss or mark told one thing the character saw."""
        done = await asyncio.to_thread(self.character.mark, ident, action, kept)
        if done is None:
            raise ValueError("item_gone")
        if action == "keep":
            # A card in the main chat shows the same choice the next time it is drawn.
            cards = self._main_cards(ident)
            for card in cards:
                card["liked"] = done
            if cards:
                self._save_chat()
        return {"ok": True, "kept": done}

    def fold_card(self, ident: str, action: str) -> None:
        """A card turned down in the main chat stays folded the next time it is drawn, to the line `action`
        names (skip, topic, hide_source, or known for seen already); "" unfolds it (the no was taken back)."""
        cards = self._main_cards(ident)
        for card in cards:
            card["skipped"] = action
        if cards:
            self._save_chat()

    async def _say(self, items: list, served: dict | None = None, unasked: bool = False) -> dict:
        """Bring things it saw into the main chat as its own messages, each with
        its card; each is then seen in the feed and told, so neither the pet's
        card nor this chat brings it again. `served`: the choice's fields by id: the
        character's line, said as the message, and the ranking's slot; its rank is its
        place in the batch. Without it, a find the pet's card showed keeps what the card was handed.
        `unasked`: the share step brought them on its own, so the person's next message reads them as an aside
        (workspace._quotes)."""
        from .panels import feed

        served = (feed.on_card if served is None else served) or {}
        since = self._main.seq
        if items:
            messages = [life.said(item) | ({"unasked": True} if unasked else {}) for item in items]
            for rank, (item, message) in enumerate(zip(items, messages)):
                shaped = served.get(item.id, {})
                if shaped.get("line"):
                    message["text"] = shaped["line"]
                if message.get("card"):
                    # The chip under its site and the topic a no may name, as the chooser dressed it (recommend.Why).
                    message["card"].update(rank=rank, slot=shaped.get("slot", ""), why=shaped.get("why"),
                                           topic=shaped.get("topic"))
            self._append(messages)
            self._save_chat()
            for rank, item in enumerate(items):
                shaped = served.get(item.id, {})
                await asyncio.to_thread(feed.remember, self._runtime(), item, "seen", surface="chat", rank=rank,
                                        slot=shaped.get("slot", ""), line=shaped.get("line", ""))
                await self.mark_item(item.id, "told")
        return {"count": len(items), **self.history(since)}

    async def _share_due(self) -> bool:
        """Whether the share step brings something now, as the pacing says; never before the first run is done."""
        from .welcome import app_settings
        if not app_settings(self._desktop).get("toured"):
            return False
        return await self.pace.due("chat")

    def exchange(self) -> dict:
        """The main chat as the share step's pacing reads it (pacing.decide): `talk`, when the person or the
        character last spoke there, other than in a find the share step brought; `held`, whether a message of theirs
        waits for its answer or a question waits on them. Both are no older than their last message."""
        talk, held = 0.0, False
        for message in reversed(self._main.history):
            held = held or bool(message.get("pending")) or (message.get("ask") or {}).get("state") == "waiting"
            if not talk and not message.get("unasked"):
                talk = datetime.fromisoformat(message["at"]).timestamp()
            if message.get("role") == "user":
                break
        return {"talk": talk, "held": held}

    async def share(self) -> int:
        """The share step: the character's choice comes into the main chat as its
        own message, once one is ready (the chooser wakes this step then). One at a
        time with the chats: skipped while one is busy."""
        if self._chat_lock.locked():
            return 0
        async with self._chat_lock:
            if not await self._share_due():
                return 0
            chosen = await self.chooser.take("chat")
            if chosen is None:
                return 0
            shaped, item = chosen
            await asyncio.to_thread(self.pace.shown, "chat", item.id)
            await self._say([item], {item.id: shaped}, unasked=True)
            return 1

    async def share_loop(self) -> None:
        """The share step every SHARE_EVERY_S, and at once when something new came in (found)."""
        while not self._closed:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._share_wake.wait(), SHARE_EVERY_S)
            self._share_wake.clear()
            await quiet.wait()
            try:
                await self.share()
            except Exception:
                traceback.print_exc()

    def found(self) -> None:
        """Something new came in (a sources round kept some, the tour ended): the
        share step looks now, and so does the pet (news)."""
        self._share_wake.set()
        self.news()

    def news(self) -> None:
        """The window app replaces this to have the pet look at once (window.py)."""

    async def bring(self, payload: dict) -> dict:
        """One thing into the main chat (the pet's card opens it there): the message
        that already carries it, else the character shares it now."""
        item = self._item(payload)
        async with self._chat_lock:
            here = [m for m in self._main.shared() if m["card"]["id"] == item.id]
            if not here:
                await self._say([item])
                here = [m for m in self._main.shared() if m["card"]["id"] == item.id]
            return {"seq": here[-1]["seq"]}

    def library_picture(self, ident: str) -> Path | None:
        return self._library().picture_path(ident) if ITEM_ID.fullmatch(str(ident or "")) else None
