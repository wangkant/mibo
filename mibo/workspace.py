"""What the app page works on: the home's setup, the chats and what the character finds. The character lives in
this process; the page reaches it through character.py."""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from . import __version__, channels, db, langs, life, pacing, recommend, settingsfile, setupform, updates
from . import setup_wizard as sw
from .character import PERSON_ACTIONS, Character, NotReady
from .chatfinds import ChatFinds
from .chatmedia import ChatMedia, read_attachments
from .pagechat import MAIN_CHAT, TITLE_FIRST, TITLE_MAX, PageChat, memories, now_iso

# Another assistant's memory list pasted into Settings › 记忆: characters read, items kept at most (person.FACTS_MAX).
PERSON_PASTE_MAX = 8_000
PERSON_IMPORT_MAX = 200
# What the character shared since the person last spoke, quoted in their next message so it knows.
SHARE_QUOTED = 5
# Seconds a reply may take before the page stops waiting: a turn may work in the browser, waiting on
# the person's press.
REPLY_WITHIN_S = 900
# Seconds a stop waits for the reply it is for to begin: the page presses stop only while a message of its own is
# on the way, and on a slow computer the press can arrive before that message has been taken in. Shorter than the
# page waits for the stop's answer (chat.js), so the next message cannot be the one stopped.
STOP_AWAITS_S = 4
# The steps a reply in progress names above the chat (loop.ChatLookups.doing), and those that may wait minutes on
# the person's press: a step in the browser, a command or a program.
DOING_TOOLS = ("recall", "search", "read", "pick", "write", "look", "pages", "operate", "shell", "desk", "mcp")
DOING_LONG = ("operate", "shell", "desk", "mcp")


class _CommandReader:
    """The character's own reading of a memory command, without the character:
    its name, the nicknames on its card and the language it speaks."""

    def __init__(self) -> None:
        from .memory import Memory
        self._parse = functools.partial(Memory._parse_memory_command, self)
        self._memory_cmd_patterns = functools.partial(Memory._memory_cmd_patterns, self)
        self.persona_name, self.persona_aliases, self.chat_lang = "", (), "en"

    def read(self, text: str, name: str, aliases: tuple, lang: str):
        self.persona_name, self.persona_aliases, self.chat_lang = name, aliases, lang
        return self._parse(text)


def _card_aliases(home: Path, values: dict) -> tuple:
    from .agent import _card_aliases as aliases
    try:
        card = json.loads((home / (values.get("PERSONA_CARD_FILE") or "persona.card.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return aliases(card)


def chat_failure(error: BaseException) -> str:
    # The character itself could not be built: a different thing to fix than a reply that failed.
    if isinstance(error, NotReady):
        return "agent_failed"
    # No answer in time: not the model's setup.
    return "timeout" if isinstance(error, asyncio.TimeoutError) else "chat_failed"


def _trace(item: dict) -> list[dict]:
    """What the character looked up for a reply: each call's tool and what it was, with what the step log shows."""
    return [{k: str(t.get(k) or "")[:200] for k in ("tool", "what")}
            # A command keeps what was run and how it ended, for the step log (shell/tool.py).
            | ({k: str(t.get(k, ""))[:600] for k in ("cmd", "out", "status", "code")}
               if t.get("tool") in ("shell", "desk", "mcp") else {})
            # Work in the page keeps its steps (search.py); a plan of a computer task keeps its list of steps,
            # each marked ✓ done, → under way or · to do; a search of past chats keeps the chats it found
            # (pastchats.py).
            | ({k: str(t.get(k, ""))[:600] for k in ("out", "status")}
               if t.get("tool") in ("operate", "plan", "chats") else {})
            # At most 32 steps of a long task (loop.py allows up to 50 rounds).
            for t in item.get("trace") or [] if isinstance(t, dict)][:32]


def _quote(message: dict) -> dict:
    """One message that brought something, as a quote the character reads."""
    card = message["card"]
    # A thing it had no sentence for is said by its title: not twice.
    title = card.get("title") if card.get("title") != message.get("text") else ""
    facts = " · ".join(v for v in (card.get("kind"), title, card.get("site")) if v)
    return {"type": "quote", "of": message["seq"],
            "text": " ".join(v for v in (message.get("text"), f"[{facts}]", card.get("excerpt")) if v)}


def _quotes(room: PageChat) -> list[dict]:
    """What the character shared in this chat since the person last spoke, as
    the quoted messages of theirs that it reads: its sentence, then the card."""
    shared = []
    for message in reversed(room.history):
        if message.get("role") == "user" and not message.get("failed"):
            break
        if (message.get("card") or {}).get("id"):
            shared.append(_quote(message))
        elif (message.get("task") or {}).get("quote"):
            # A reminder or a failure line the page said for a scheduled task (panels/schedule.py).
            shared.append({"type": "quote", "of": message["seq"],
                           "text": f"[{message['task']['title']}] {message.get('text', '')}"})
    return shared[:SHARE_QUOTED][::-1]


class Workspace(ChatFinds):
    """One home as the page works on it: its setup, its chats with the character, and (ChatFinds) what the
    character found."""

    def __init__(self, home: Path):
        self.home = home.resolve()
        # The character this page talks to, started and stopped with the page (create_app's lifespan).
        self.character = Character(self.home, runtime=self._runtime, said=self.take_said,
                                   chats=lambda: [c.conversation for c in self._all_chats() if not c.private])
        self._lock = threading.RLock()
        self._chat_lock = asyncio.Lock()
        # (chat, message, ended) while a reply to it is on its way: what the stop button stops.
        self._replying: tuple | None = None
        # The questions said in a chat and not yet decided, by id: (chat, the question's message) (cardwait.py).
        self._asked: dict[str, tuple] = {}
        # The scheduled tasks, set when their panel is mounted (panels/schedule.py).
        self.schedule = None
        self._forgetting = False
        self._commands = None
        # Set when something new came in (found): the share step looks then.
        self._share_wake = asyncio.Event()
        self._closed = False
        self._desktop = self.home / "runtime" / "desktop"
        self.media = ChatMedia(self._desktop, self._messages)
        # The chats, from the runtime database: the main chat, where what the character finds arrives too,
        # and the plain chats.
        self.db = db.at(self._runtime())
        messages: dict[str, list] = {}
        for chat, seq, body in self.db.read(
                "SELECT chat, seq, body FROM page_messages WHERE kind = 'message' ORDER BY chat, seq"):
            messages.setdefault(chat, []).append((seq, body))
        rows = {r[0]: r[1:] for r in self.db.read("SELECT id, conversation, title, at, seq FROM page_chats")}
        self._main = PageChat(self.db, MAIN_CHAT, rows.pop(MAIN_CHAT, None), messages.get(MAIN_CHAT, ()))
        self._chats: dict[str, PageChat] = {ident: PageChat(self.db, ident, row, messages.get(ident, ()))
                                            for ident, row in sorted(rows.items())}
        self.media.prune()
        # The one thing the pet's card and the share step bring next, chosen by the character's model.
        self.chooser = recommend.Chooser(self)
        # When the card and the share step bring it (pacing.py).
        self.pace = pacing.Pacer(self)

    def _all_chats(self) -> list[PageChat]:
        return [self._main, *self._chats.values()]

    def _messages(self):
        return (m for chat in self._all_chats() for m in chat.history)

    def _chat(self, ident) -> PageChat:
        """The chat an id names: "main" or nothing for the main chat."""
        ident = str(ident or MAIN_CHAT)
        if ident == MAIN_CHAT:
            return self._main
        if ident not in self._chats:
            raise ValueError("invalid_chat")
        return self._chats[ident]

    def config(self) -> dict:
        return settingsfile.values(self.home)

    def _runtime(self) -> Path:
        # Where the character keeps its state: the home's settings over this
        # process's environment, else <home>/runtime.
        configured = settingsfile.values(self.home, keys=False).get("AGENT_RUNTIME_DIR")
        if configured is None:
            configured = os.environ.get("AGENT_RUNTIME_DIR", "")
        runtime = Path(configured.strip() or "runtime").expanduser()
        return runtime if runtime.is_absolute() else self.home / runtime

    # -- the home's setup

    def _origin(self) -> tuple[str, str, str] | None:
        """The shipped character persona.txt is, None for one written by hand or none."""
        card = self.home / "persona.txt"
        return sw.shipped_persona(card.read_text(encoding="utf-8")) if card.is_file() else None

    def summary(self) -> dict:
        with self._lock:
            values = self.config()
            known = sw.provider_for_base(values.get("LLM_BASE_URL", ""))
            origin = self._origin()
            updates.refresh_soon(self.home)
            avatar = values.get("PERSONA_AVATAR", "").strip()
            own_picture = sw.own_avatar(self.home)
            if avatar == sw.OWN_AVATAR and not own_picture:
                avatar = ""
            if avatar != sw.OWN_AVATAR and not sw.portrait(avatar):
                avatar = origin[0] if origin and sw.portrait(origin[0]) else ""
            return {"version": __version__, "update": updates.notice(self.home),
                    # The update the run before began, as this start found it: the chat says it in one line.
                    "updated": updates.outcome(self.home),
                    "configured": bool(values.get("LLM_API_KEY")),
                    "provider": known.key if known else ("other" if values.get("LLM_BASE_URL")
                                                          else "deepseek" if values.get("LLM_API_KEY")
                                                          else sw.PROVIDERS[0].key),
                    "model": values.get("LLM_MODEL", ""), "baseUrl": values.get("LLM_BASE_URL", ""),
                    "name": values.get("PERSONA_NAME", ""), "lang": langs.normalize(values.get("AGENT_LANG")),
                    # What the page calls the person at it, where a name is set.
                    "adminName": values.get("ADMIN_NAME", "").strip()[:64],
                    "character": (sw.default_character(origin) if origin
                                  else "custom" if (self.home / "persona.txt").is_file() else sw.CHARACTERS[0].key),
                    "avatar": avatar,
                    # Changes with the file, so the page fetches a replaced picture again.
                    "ownAvatar": self._own_avatar_version(own_picture)}

    @staticmethod
    def _own_avatar_version(path: Path | None) -> str:
        try:
            return str(path.stat().st_mtime_ns) if path else ""
        except OSError:
            return ""

    def save(self, payload: dict) -> dict:
        """The setup form's choice written, once its key answered (setupform.chosen); the summary after it."""
        with self._lock:
            old = self.config()
            values, character = setupform.chosen(self.home, old, payload)
            settingsfile.write(self.home, values)
            if character != "custom":
                # A persona.txt someone wrote is copied aside before a shipped one replaces it.
                sw.back_up_persona(self.home)
                sw.write_persona(self.home, character, name=values["PERSONA_NAME"], lang=values["AGENT_LANG"],
                                 admin_name=old.get("ADMIN_NAME", ""),
                                 admin_relationship=old.get("ADMIN_RELATIONSHIP", ""))
            self.character.reload()
            self.figure_changed()
            return self.summary()

    def persona(self) -> dict:
        """The persona the agent runs on: persona.txt, else the first shipped
        character, Mibo, as the agent takes it."""
        with self._lock:
            path = self.home / "persona.txt"
            if path.is_file():
                return {"text": path.read_text(encoding="utf-8").strip()}
            values = self.config()
            lang = langs.normalize(values.get("AGENT_LANG")) or "en"
            text = sw.persona_text(sw.CHARACTERS[0].key, name=values.get("PERSONA_NAME") or sw.DEFAULT_NAMES[lang],
                                   lang=lang, admin_name=values.get("ADMIN_NAME", ""),
                                   admin_relationship=values.get("ADMIN_RELATIONSHIP", ""))
            return {"text": text.strip()}

    def save_own_avatar(self, data: bytes) -> dict:
        """Keep `data` as the character's picture on this page and show it."""
        if len(data) > sw.MAX_OWN_AVATAR:
            raise ValueError("avatar_too_large")
        if not sw.own_avatar_kind(data):
            raise ValueError("avatar_type")
        with self._lock:
            sw.write_own_avatar(self.home, data)
            settingsfile.write(self.home, {"PERSONA_AVATAR": sw.OWN_AVATAR})
            self.figure_changed()
            return self.summary()

    def remove_own_avatar(self) -> dict:
        """Delete the picture; the character goes back to its portrait or initial."""
        with self._lock:
            for kind in sw.OWN_AVATAR_TYPES:
                path = self.home / f"avatar.{kind}"
                if path.is_file() and not path.is_symlink():
                    path.unlink(missing_ok=True)
            if self.config().get("PERSONA_AVATAR", "").strip() == sw.OWN_AVATAR:
                origin = self._origin()
                settingsfile.write(self.home, {"PERSONA_AVATAR": sw.avatar_for(origin[0]) if origin else ""})
                self.figure_changed()
            return self.summary()

    # -- the chats

    def history(self, after: int | None = None, chat: str = MAIN_CHAT) -> dict:
        room = self._chat(chat)
        view = room.view(after)
        # While a reply is on its way: the step it is on (loop.ChatLookups.doing).
        if self._chat_lock.locked():
            doing = sw._read_json(self._runtime() / "desktop" / "chat-doing.json")
            tool = doing.get("tool")
            if (doing.get("conversation") == room.conversation and tool in DOING_TOOLS
                    and time.time() - float(doing.get("at") or 0) < (300 if tool in DOING_LONG else 120)):
                view["doing"] = {"tool": tool, "what": str(doing.get("what") or "")[:120]}
        return view

    def reset_chat(self) -> None:
        self._main.reset()
        self._save_chat()
        self.db.scrubbed()

    def _append(self, entries: list[dict], chat: PageChat | None = None) -> list[dict]:
        return (chat or self._main).append(entries)

    def chats(self) -> dict:
        """The main chat and the plain chats, the latest first."""
        main = self._main
        listed = sorted(self._chats.values(), key=lambda c: datetime.fromisoformat(c.at), reverse=True)
        return {"main": {"id": MAIN_CHAT, "name": self.config().get("PERSONA_NAME", "").strip(),
                         "last": main.history[-1]["seq"] if main.history else 0},
                "chats": [chat.listed() for chat in listed]}

    async def new_chat(self, private: bool = False) -> dict:
        """A new plain chat, or with `private` a 无痕对话; one of that kind not written in yet is given again."""
        async with self._chat_lock:
            blank = next((c for c in self._chats.values() if not c.history and c.private == private), None)
            if blank is not None:
                return blank.listed()
            ident = secrets.token_hex(8)
            chat = PageChat(self.db, ident)
            if private:
                chat.conversation = channels.PRIVATE_CHAT + secrets.token_hex(12)
            chat.at = now_iso()
            self._chats[ident] = chat
            self._save_chat(chat)
            return chat.listed()

    async def rename_chat(self, payload: dict) -> dict:
        title = " ".join(str(payload.get("title") or "").split())
        if not title or len(title) > TITLE_MAX:
            raise ValueError("invalid_title")
        async with self._chat_lock:
            chat = self._chat(payload.get("id"))
            if chat is self._main:
                raise ValueError("invalid_chat")
            chat.title = title
            self._save_chat(chat)
        return {"ok": True}

    async def delete_chat(self, payload: dict) -> dict:
        async with self._chat_lock:
            chat = self._chat(payload.get("id"))
            if chat is self._main:
                raise ValueError("invalid_chat")
            del self._chats[chat.id]
            self.media.prune(chat.delete())
            # Its chat record goes with it (what was kept about them stays), so no search of past chats finds it.
            with contextlib.suppress(NotReady):
                await self.character.forget_chat(chat.conversation, [c.conversation for c in self._all_chats()])
        return {"ok": True}

    def _entry(self, item: dict) -> dict | None:
        """A reply item as a chat message: text, or a picture stored for the page
        to show; None for what the page cannot show."""
        kind = item.get("type")
        if kind == "text" and str(item.get("text") or "").strip():
            return self._text_entry(item)
        if kind == "memory" and memories(item.get("saved")):
            # What a fold kept from this chat: one quiet 已记住 line (character.py).
            return {"role": "memory", "saved": memories(item["saved"])}
        if kind == "image":
            name = self.media.keep_picture(item.get("b64"))
            if name:
                return {"role": "assistant", "picture": name}
        return None

    def _text_entry(self, item: dict) -> dict:
        card = life.clean_card(item.get("card"))
        # A find of the library's, brought by the reply: its card as the share step makes it.
        found = self._library().get(str(item["card"].get("id") or "")) if card else None
        if found is not None:
            card = life.said(found).get("card") or card
        # What the character looked up for this reply: its sources, links the page shows, and the calls.
        sources = [{k: str(s.get(k) or "")[:300] for k in ("title", "url", "site")}
                   for s in item.get("sources") or [] if isinstance(s, dict)
                   and str(s.get("url") or "").startswith(("https://", "http://"))][:4]
        trace = _trace(item)
        # The reply's reasoning where the model returned it: seconds and text (abilities.note_reasoning).
        thought = item.get("thinking") if isinstance(item.get("thinking"), dict) else {}
        thinking = {"s": int(thought["s"]) if isinstance(thought.get("s"), (int, float)) else 0,
                    "text": str(thought.get("text") or "")[:8000]} if thought.get("text") else None
        # The memories the reply drew on (dm.py), listed under it.
        used = memories((item.get("memory") or {}).get("used"))
        # One entry for each call the turn made (loop.ChatLookups.note).
        activity = [{k: str(a.get(k) or "")[:200] for k in ("place", "mark", "line", "status", "thumb")}
                    for a in item.get("activity") or [] if isinstance(a, dict)][:50]
        return {"role": "assistant", "text": str(item["text"]), **({"card": card} if card else {}),
                **({"sources": sources} if sources else {}), **({"trace": trace} if trace else {}),
                **({"activity": activity} if activity else {}),
                **({"thinking": thinking} if thinking else {}), **({"memory": {"used": used}} if used else {})}

    def _entries(self, items: list) -> list[dict]:
        return [entry for entry in map(self._entry, items) if entry]

    def _save_chat(self, chat: PageChat | None = None) -> None:
        left = (chat or self._main).save()
        if left:
            self.media.prune(left)
        self.chat_changed()

    # The window app replaces these to tell its pages at once (window.py); elsewhere nothing is told.
    def chat_changed(self) -> None:
        """A chat was saved: a reply, a remark, something shared or said unasked."""

    def figure_changed(self) -> None:
        """The character's figure may be another now."""

    def busy(self, doing: str) -> None:
        """The window app replaces this: a reply is on its way ("thinking"), or "" when it is in (window.py pet_busy)."""

    def take_said(self, conversation: str, items: list) -> None:
        """What the character said on its own (the follow-up of a plan) joins the chat it is for."""
        chat = next((c for c in self._all_chats() if c.conversation == conversation), None)
        # A chat replaced or deleted since, or one being forgotten: nothing is shown for it.
        if chat is None or self._forgetting:
            return
        entries = self._entries(items)
        if entries:
            chat.append(entries)
            self._save_chat(chat)

    async def stop_chat(self, chat: str = MAIN_CHAT, why: str = "stopped") -> dict:
        """The stop button, or the page done waiting (`why` "timeout"): the reply
        under way in `chat` is cancelled, and the message it was answering is
        kept, marked, to send again. Answers once the reply has ended, so the
        page then reads the message as kept. A press that arrives before its message's reply has begun waits
        for it (STOP_AWAITS_S)."""
        waited = time.monotonic() + STOP_AWAITS_S
        while self._replying is None and time.monotonic() < waited:
            await asyncio.sleep(0.05)
        if self._replying is None or self._replying[0] is not self._chat(chat):
            return {"stopped": False}
        room, said, ended = self._replying
        said["stopping"] = why if why in ("stopped", "timeout") else "stopped"
        stopped = self.character.stop(room.conversation)
        # Pressed before the reply has reached its model call, there is nothing to cancel yet: it is asked again
        # until there is, or until the reply has ended. A slow start is waited out, so no stop is lost.
        while not stopped and not ended.is_set():
            await asyncio.sleep(0.05)
            stopped = self.character.stop(room.conversation)
        if stopped:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(ended.wait(), 10)
        return {"stopped": stopped}

    async def forget_chat(self) -> dict:
        """Forget everything the main chat remembers, the chats it left behind
        included, then start it anew. The plain chats the page still lists keep
        theirs."""
        async with self._chat_lock:
            self._forgetting = True
            try:
                forgotten = await self.character.forget_chat(
                    self._main.conversation, [chat.conversation for chat in self._chats.values()])
            except NotReady:
                raise ValueError("activity_unavailable") from None
            finally:
                self._forgetting = False
            self.reset_chat()
            return {"ok": True, "forgotten": forgotten}

    # -- what the model reads of a chat (context design, stage S5): the gauge, 立即归纳 and 清空上下文

    def chat_context(self, chat: str = MAIN_CHAT) -> dict:
        return self.character.context(self._chat(chat).conversation)

    async def compact_chat(self, chat: str = MAIN_CHAT) -> dict:
        """The chat's older turns condensed now, between replies: {"compacted", "failed"}."""
        async with self._chat_lock:
            try:
                return await self.character.compact(self._chat(chat).conversation)
            except NotReady:
                raise ValueError("activity_unavailable") from None

    async def clear_context(self, chat: str = MAIN_CHAT) -> dict:
        """The model no longer reads the chat's turns before now; the page keeps every message."""
        async with self._chat_lock:
            room = self._chat(chat)
            try:
                mark = await self.character.clear_context(room.conversation)
            except NotReady:
                raise ValueError("activity_unavailable") from None
            if room.private:
                room.mark = mark
            return {"ok": True, "summary": room.summary()}

    # -- a message and its reply

    async def chat(self, text: str, after: int | None = None, retry: int | None = None,
                   chat: str = MAIN_CHAT, reply_to: str = "", attachments: list | None = None,
                   choices: list | None = None, answering: int | None = None) -> dict:
        """Send `text` in one chat; the reply, and every message since `after` in
        order, including what the character sent on its own meanwhile. `retry`
        names the unanswered message this one sends again, which then goes, and
        whose attachments go again when none come with it. `reply_to` names a thing
        the character brought that this message answers. `attachments`: pictures and
        text files, as chat.js sends them (chatmedia.read_attachments). `choices`: what the
        person chose under "+" for this message (turns.TURN_CHOICES), which the turn honours.
        `answering` names the person's message that was a no to a question (answer_said): its own
        words, where they stand in the chat, are the message answered now, once; `text` is not read."""
        from .turns import TURN_CHOICES
        picked = [c for c in TURN_CHOICES if c in (choices if isinstance(choices, list) else [])]
        if not self.config().get("LLM_API_KEY"):
            raise ValueError("key_required")
        if not text.strip() and not attachments and retry is None and answering is None:
            raise ValueError("generic")
        if len(text) > 8000:
            raise ValueError("invalid_message")
        taken = read_attachments(attachments or [])
        began = time.monotonic()
        asked_at = time.time()
        async with self._chat_lock:
            room = self._chat(chat)
            again, picked = self._take_retried(room, retry, picked)
            answer = None if answering is None else self._take_answer(room, answering)
            if answer is not None:
                text = answer["text"]
            # Stored and recorded with no wait between, so no save in between finds them unshown.
            records = self.media.keep(taken) if taken else again
            if not text.strip() and not records:
                raise ValueError("generic")
            if room is not self._main and not room.title:
                room.title = (" ".join(text.split())
                              or next((r["file"] for r in records if r["kind"] == "file"), ""))[:TITLE_FIRST]
            if answer is None:
                said, quotes = self._record_asked(room, text, records, picked, reply_to)
            else:
                said, quotes = answer, _quotes(room)
            items = await self._reply(room, said, quotes, text, records, picked)
            said.pop("pending", None)
            if any(item.get("type") == "cut" for item in items):
                # Longer than the model reads at once: the character took its head and tail (dm._cut_message).
                said["cut"] = True
            stopped = said.pop("stopping", "")
            # The cut's mark is no reply: a cut message that got no words waits to be sent again.
            shown = [item for item in items if item.get("type") != "cut"]
            if stopped and not shown:
                # Stopped from the page: nothing came, and the message waits to be sent again.
                self._unanswered(said, stopped, room)
                return {"reply": "", "stopped": True, **room.view(said["seq"] - 1 if after is None else after)}
            self._refuse_unanswered(room, said, items, shown, asked_at)
            entries, command = self._reply_entries(items, text, began)
            room.append(entries)
            scrub = next((i["scrub"] for i in items if isinstance(i.get("scrub"), dict)), None)
            # A memory command and its answer stay as they are; a turn not to keep goes whole.
            dropped = self._scrub_chats(scrub, room, {id(said), *map(id, entries)} if command else set()) if scrub else 0
            self._save_chat(room)
            if not room.private:
                # A 无痕对话 tells the recommender nothing.
                await self._chat_finds(items, entries, said.get("quote"))
            reply = "\n".join(str(i.get("text", "")) for i in items if i.get("type") == "text")
            if dropped:
                # Earlier messages went: the page draws the chat afresh.
                return {"reply": reply, "forgotLines": dropped, **room.view()}
            return {"reply": reply, **room.view(said["seq"] - 1 if after is None else after)}

    @staticmethod
    def _take_retried(room: PageChat, retry: int | None, picked: list) -> tuple[list, list]:
        """The unanswered message `retry` names leaves the chat: its attachments, and its choices unless the
        message sent again chose its own."""
        if retry is None:
            return [], picked
        failed = next((m for m in room.history if m.get("seq") == retry and m.get("failed")), {})
        room.history = [m for m in room.history if m is not failed]
        return failed.get("attachments") or [], picked or failed.get("choices") or []

    @staticmethod
    def _take_answer(room: PageChat, seq: int) -> dict:
        """The person's no to a question (answer_said), not yet answered as a message: kept where they typed it and
        marked pending again. Taken once: a message answered already is refused."""
        said = next((m for m in room.history if m.get("seq") == seq and m.get("role") == "user" and m.get("answers")
                     and (m.get("pending") or m.get("failed"))), None)
        if said is None:
            raise ValueError("generic")
        said.pop("failed", None)
        said["pending"] = True
        return said

    # -- a question of the reply under way, and its answer (cardwait.py)

    def question_said(self, conversation: str, entry: dict) -> None:
        """A question a step of the reply under way waits on joins that reply's chat as the character's message,
        after the request and before the reply; a picture the fold shows is stored as the chat's pictures are. Only
        into the chat of the reply under way, and only when its conversation is the asking step's."""
        if self._replying is None or self._replying[0].conversation != conversation:
            return
        room = self._replying[0]
        detail = entry["ask"]["detail"]
        if detail.get("picture"):
            detail["picture"] = self.media.keep_picture(detail["picture"])
            if not detail["picture"]:
                del detail["picture"]
        room.append([entry])
        self._asked[entry["ask"]["id"]] = (room, entry)
        with contextlib.suppress(sqlite3.Error):
            self._save_chat(room)

    def answer_said(self, ident: str, state: str, line: str = "", pending: bool = False) -> int | None:
        """How question `ident` was decided ("yes", "no", "unanswered", or "left": a browser act the next message
        beside the page may still answer), kept on it with the time; the person's words, when there are any, after
        it as their message, marked `pending` (a typed no) until they are answered as a message (chat
        `answering`). The number of that message, or None. A question decided already is not decided again."""
        held = self._asked.get(ident)
        if held is None or held[1]["ask"]["state"] not in ("waiting", "left"):
            return None
        room, question = held
        question["ask"].update(state=state, at=now_iso())
        if state != "left":
            del self._asked[ident]
        seq = None
        if line.strip():
            (said,) = room.append([{"role": "user", "text": line, "answers": ident,
                                    **({"pending": True} if pending else {})}])
            seq = said["seq"]
        with contextlib.suppress(sqlite3.Error):
            self._save_chat(room)
        return seq

    def _record_asked(self, room: PageChat, text: str, records: list[dict], picked: list,
                      reply_to: str) -> tuple[dict, list[dict]]:
        """The person's message recorded in `room` and kept marked as pending, so a page process that ends
        mid-reply leaves it to send again; the quotes it carries to the character."""
        # The character's own record of the chat holds only what was said in turns: what it
        # shared since the person last spoke reaches it as quotes in this message.
        quotes = _quotes(room)
        asked = {"role": "user", "text": text, **({"attachments": records} if records else {}),
                 **({"choices": picked} if picked else {})}
        # The thing answered is quoted last, nearest the words about it, and shown in the message.
        answered = next((m for m in reversed(room.history)
                         if reply_to and (m.get("card") or {}).get("id") == reply_to), None)
        if answered:
            quotes = [q for q in quotes if q["of"] != answered["seq"]]
            quotes.append(_quote(answered))
            card = answered["card"]
            asked["quote"] = {k: card.get(k) or "" for k in ("id", "title", "kind", "site", "picture")}
        # Recorded first, so what the character says on its own during the reply comes after it.
        (said,) = room.append([asked])
        said["pending"] = True
        with contextlib.suppress(sqlite3.Error):
            room.save()
        return said, quotes

    async def _reply(self, room: PageChat, said: dict, quotes: list[dict], text: str, records: list[dict],
                     picked: list) -> list:
        """The character's reply to `said`, which the stop button may cancel; a failure leaves it unanswered."""
        self._replying = (room, said, asyncio.Event())
        try:
            # Its own line, apart from what follows it.
            words = [{"type": "text", "text": f"{text}\n" if records else text}] if text.strip() else []
            return await asyncio.wait_for(self.character.reply(
                room.conversation, [*quotes, *words, *self.media.parts(records)], choices=picked), REPLY_WITHIN_S)
        except BaseException as error:
            self._unanswered(said, chat_failure(error), room)
            raise
        finally:
            self._replying[2].set()
            self._replying = None

    def _refuse_unanswered(self, room: PageChat, said: dict, items: list, shown: list, asked_at: float) -> None:
        """A reply the model failed, or one with no words, leaves the message unanswered to send again, and is
        reported: here the admin checks the setup, so it is not chatted about."""
        if any(item.get("reason") == "excuse" for item in items):
            # An account out of balance is named, with its console, and a window too small for the chat's
            # setup with its sentence (abilities.note_problem).
            from . import abilities
            problem = abilities.problem_since(self._runtime(), asked_at)
            if problem in ("no_balance", "window_small"):
                self._unanswered(said, f"model_{problem}", room)
                raise ValueError(f"model_{problem}")
            self._unanswered(said, "chat_failed", room)
            raise RuntimeError("the model did not answer")
        if not shown:
            # The character had no words for it: shown as not sent, to send again.
            self._unanswered(said, "generic", room)
            raise ValueError("generic")

    def _reply_entries(self, items: list, text: str, began: float) -> tuple[list[dict], bool]:
        """The reply as chat messages, and whether `text` was a memory command."""
        entries = self._entries(items)
        if self.schedule is not None:
            # What the reply did to scheduled tasks, under it (panels/schedule.py).
            self.schedule.attach(entries)
        command = self._memory_command(text) if entries and text.strip() else None
        for entry in entries:
            # An answer to a memory command is shown whole at once, not typed out.
            if command:
                entry["command"] = command[0]
            # How long the turn took, shown with its steps (activity.js).
            if entry.get("trace"):
                entry["took"] = round(time.monotonic() - began)
        if command:
            # Under its last line, the way to Settings › Memory (chat.js).
            entries[-1]["manage"] = True
        return entries, command is not None

    def _memory_command(self, text: str):
        """(kind, argument, chat language) when the character reads `text` as a
        memory command; None for conversation or when it cannot be told."""
        values = self.config()
        try:
            if self._commands is None:
                self._commands = _CommandReader()
            return self._commands.read(text, values.get("PERSONA_NAME", "").strip(),
                                       _card_aliases(self.home, values),
                                       langs.normalize(values.get("AGENT_LANG")) or "en")
        except Exception:
            return None

    def _scrub_chats(self, scrub: dict, room: PageChat, keep: frozenset | set = frozenset()) -> int:
        """What the character forgot, or was asked not to keep, leaves the chats'
        own copies. A forget (`mark`: its language) puts the forgotten mark in place
        of each sentence holding the words, in every chat, and of the lines it names
        in this one; a turn not to keep goes from this chat whole. The messages
        `keep` names stay. Every chat that changed is written in one transaction,
        and the database keeps no older copy of the words. How many changed."""
        from . import person
        lines = {" ".join(part.split()) for x in scrub.get("lines") or [] for part in [str(x), *str(x).split("\n")]}
        lines.discard("")
        said = person.forget_hit(scrub.get("words") or [], scrub.get("texts") or [])
        mark = scrub.get("mark")
        changed, touched = 0, []
        for chat in self._all_chats():

            def hit(text: str, chat=chat) -> bool:
                return said(text) or (chat is room and " ".join(text.split()) in lines)
            rows = []
            for m in chat.history:
                text = str(m.get("text") or "")
                if id(m) in keep or not hit(text):
                    rows.append(m)
                    continue
                changed += 1
                if mark:
                    rows.append({**m, "text": person.scrub(text, hit, mark)})
            if len(rows) != len(chat.history) or any(a is not b for a, b in zip(rows, chat.history)):
                chat.history = rows
                touched.append(chat)
        if touched:
            with self.db.write():
                for chat in touched:
                    self._save_chat(chat)
            self.db.scrubbed()
        return changed

    def _unanswered(self, said: dict, code: str, room: PageChat) -> None:
        """Kept, marked, so the person can see which message went unanswered and send it again."""
        said.pop("pending", None)
        said["failed"] = code
        with contextlib.suppress(sqlite3.Error):
            self._save_chat(room)

    # -- what the character knows of the one person (person.json)

    async def person_write(self, action: str, payload: dict) -> dict:
        """forget, edit or restore one item, forget all, add one, the two switches, or a pasted list read and its
        ticked items kept; the view after it."""
        item, text, lines = str(payload.get("id") or ""), str(payload.get("text") or ""), payload.get("lines")
        switches = {k: payload[k] for k in ("on", "health") if isinstance(payload.get(k), bool)}
        if (action not in PERSON_ACTIONS or len(item) > 64
                or len(text) > (PERSON_PASTE_MAX if action == "import_preview" else 400)
                or (action in ("forget", "forget_chats", "edit", "restore") and not item)
                or (action in ("edit", "add", "import_preview") and not text.strip())
                or (action == "settings" and not switches)
                or (action == "import" and not (isinstance(lines, list) and 0 < len(lines) <= PERSON_IMPORT_MAX
                                                and all(isinstance(x, str) and 0 < len(x) <= 400 for x in lines)))):
            raise ValueError("invalid_chat")
        try:
            raw = await self.character.person_write(action, self._main.conversation, item, text,
                                                    {**switches, "lines": lines})
        except NotReady:
            raise ValueError("activity_unavailable") from None
        scrub = raw.pop("scrub", None)
        if scrub:
            # The page's own copies of the chats lose the words too.
            async with self._chat_lock:
                self._scrub_chats(scrub, self._main)
                self._save_chat()
        return raw

    async def remark(self, text: str) -> bool:
        """A line of its own about what its person is doing, into the main chat; False while a chat is busy."""
        if self._chat_lock.locked():
            return False
        async with self._chat_lock:
            # The page draws a remark as a quiet aside, not a reply.
            self._append([{"role": "assistant", "text": text, "remark": True}])
            self._save_chat()
        return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
