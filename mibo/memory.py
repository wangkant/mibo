"""What the persona remembers: memory commands, auto memory and core memory."""
from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
import time
from collections.abc import Callable, Iterable

from . import (
    channels,
    chatlangs,
    chatlog,
    db,
    memgate,
    memstate,
    memstore,
    person,
    personsaid,
    personview,
    secretwords,
    timewords,
)
from .addressing import _HAS_CJK, names_regex
from .channels import PAGE_PLATFORM
from .context import CHECKPOINT
from .storage import num as _num
from .textproc import _FULL_STOP_RE, _focus_tokens

logger = logging.getLogger("agent")

# Plain text: the reply crosses the character policy like any other. One
# table per chat language, kept with the rest of it in `chatlangs`.
_COMMAND_REPLIES = {code: spec.replies for code, spec in chatlangs.SPECS.items()}

# Trimmed off a forget query, in every language.
_QUERY_TRIM = " \t.!?,;:。！？，、~～…¡¿«»„“”"


def _is_question(content: str, spec: chatlangs.Spec) -> bool:
    return bool(re.search(spec.question_end, content.strip(), re.IGNORECASE))


def _asks(content: str, spec: chatlangs.Spec) -> bool:
    """A question, whole or in its first clause: "记住了吗，别叫我鱼片"."""
    return _is_question(content, spec) or _is_question(re.split(r"[，,。;；]", content.strip(), maxsplit=1)[0], spec)


def _forget_query(content: str, spec: chatlangs.Spec) -> str:
    query = content.strip()
    if spec.query_lead:
        query = re.sub(spec.query_lead, "", query, flags=re.IGNORECASE)
    # "忘掉挂科的事": the thing is 挂科.
    query = re.sub(r"(?<=[一-鿿])(?:的|那|这|這)?件?(?:事情|事儿|事兒|事)$", "", query.strip(_QUERY_TRIM))
    return query.strip(_QUERY_TRIM)


def _without_sentences(text: str, hit: Callable[[str], bool]) -> str:
    """`text` without the sentences `hit` names, line by line, as person.forget leaves the talk summary; "" when
    what is left still holds it (spread over sentences that each hold a part), as it cannot be taken out alone."""
    lines = []
    for line in text.split("\n"):
        kept = "".join(p for p in re.split(r"(?<=[。！？；.!?;])", line) if not hit(p))
        if kept.strip() or not line.strip():
            lines.append(kept)
    left = "\n".join(lines).strip()
    return "" if hit(left) else left


def today_runtime(agent):
    """The runtime folder the profile lives in."""
    from . import today
    return today.runtime_of(agent)


# Where a summary may be cut by a forget; "3.5 hours" is one sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|(?<=[。！？；\n])\s*")

# Beside memory.json, so a home moved by MEMORY_FILE keeps them together.
STATE_FILE = "memory_state.json"


class Memory:
    # ---- the stores ---------------------------------------------------------

    @property
    def memory_state(self) -> memstate.MemoryState:
        return self._sidecar("_memory_state", memstate.MemoryState,
                             self.memory_file.with_name(STATE_FILE))

    @property
    def chat_log(self) -> chatlog.ChatLog:
        """The chats' logs; off with MEMORY_LOG_DAYS=0 or MEMORY_KEEP_RECENT=false."""
        s = getattr(self, "settings", None)
        days = int(getattr(s, "memory_log_days", 30) or 0) \
            if getattr(s, "memory_keep_recent", True) else 0
        runtime = self.memory_file.parent
        log = self.__dict__.get("_chat_log")
        if log is None or log.runtime != runtime:
            log = self.__dict__["_chat_log"] = chatlog.ChatLog(runtime, days)
        log.days = float(days)
        return log

    def _log_rows(self, conv: str) -> list[dict]:
        """The chat's held turns in the log's row shape; its checkpoint is no line of the chat."""
        reader = channels.dm_user(conv)
        out = []
        for row in (getattr(self, "dm_history", {}).get(reader) or [] if reader else []):
            if row.get("role") == CHECKPOINT:
                continue
            bot = row.get("role") != "user"
            out.append({"seq": row.get("seq"), "t": row.get("t"), "t1": row.get("t1"),
                        "user_id": "" if bot else reader,
                        "name": self.persona_name if bot else str(row.get("name") or ""),
                        "text": row.get("content"), "self": bot, "mid": row.get("mid")})
        return out

    def _log_chat(self, conv: str) -> int:
        """Append what the chat's log lacks; never raises, never waits long."""
        log = self.chat_log
        # A 无痕对话 is never logged: no fold and no search of past chats reads it.
        if not log.on or channels.private_chat(conv):
            return 0
        return log.take(conv, self._log_rows(conv))

    def _save_memory_state(self, force: bool = True) -> None:
        try:
            self.memory_state.save(force=force)
        except OSError as e:
            logger.warning("[Agent] memory state save failed: %s", e)

    def _memory_gen(self, conv: str) -> int:
        """How many forgets this chat has had since the start."""
        return self.__dict__.get("_forget_gens", {}).get(conv, 0)

    def _forgot(self, conv: str) -> None:
        """A consolidation of this chat already under way now keeps nothing."""
        gens = self.__dict__.setdefault("_forget_gens", {})
        gens[conv] = gens.get(conv, 0) + 1

    def _final_copies(self) -> None:
        """After a final forget the recent file is written now."""
        flush = getattr(self, "_maybe_flush_recent", None)
        if callable(flush) and getattr(self, "_recent", None) is not None:
            flush(force=True)

    # ---- hooks the turn and recall code fills in ---------------------------

    def _mark_used(self, conv: str, reply_text: str) -> list[dict]:
        """Count the remembered items a sent reply drew on, and return them (retrieval.py)."""
        return []

    def _tell_saved(self, rows: list[dict]) -> None:
        """What a fold newly kept, told to the page under the chat each came from (character.py sets
        `saved_told(conversation, items)`)."""
        told = getattr(self, "saved_told", None)
        by_conv: dict[str, list[dict]] = {}
        for row in rows:
            if row.get("conv"):
                by_conv.setdefault(row["conv"], []).append({"id": row["id"], "text": personview.shown(row)})
        for conv, items in by_conv.items():
            if told is not None:
                told(channels.dm_user(conv).split(":", 1)[-1], items)

    def _parse_memory_command(self, text: str) -> tuple[str, str, str] | None:
        """(kind, what follows the keyword, chat language) when `text` is a
        memory command: remember, forget or recall; a forget naming nothing
        ("把刚才那件事忘了") is "forget_that". None for conversation. The
        character's name may lead it or be left out. Every language is tried;
        when two read it, the one the message looks written in wins."""
        code = chatlangs.detect(text, self.chat_lang)
        if person.forget_that(text):
            return "forget_that", "", code
        for lang, spec, pats in self._memory_cmd_patterns():
            for pat in pats["forget"]:
                m = pat.search(text)
                if m and _forget_query(m.group(1), spec).lower() in spec.deictic:
                    return "forget_that", "", lang
        hit = None
        for lang, spec, pats in self._memory_cmd_patterns():
            for kind in ("remember", "forget"):
                for pat in pats[kind]:
                    m = pat.search(text)
                    if m and not _asks(m.group(1), spec) and (
                            kind == "remember" or not (spec.asking and re.search(spec.asking, m.group(1)))):
                        hit = hit or (kind, m.group(1), lang)
                        if lang == code:
                            return kind, m.group(1), lang
            if pats["recall"].search(text):
                hit = hit or ("recall", "", lang)
        return hit

    def _handle_memory_command(self, conv: str, text: str) -> str | None:
        """Carry out the memory command `text` in the chat `conv`; its answer,
        or None when it is not one."""
        parsed = self._parse_memory_command(text)
        if parsed is None:
            return None
        return self._person_command(conv, *parsed)

    def _own_line(self, row: dict) -> bool:
        """A line the character wrote, in the window's, the DM turns' or the log's shape."""
        if "role" in row:
            return row["role"] != "user"
        return bool(row.get("self")) or (
            not row.get("user_id") and row.get("name") == self.persona_name)

    def _purge_lines(self, conv: str, hit: Callable[[str], bool],
                     cut: Callable[[str], str] | None = None) -> int:
        """Delete matching recent lines of this chat (the DM turns, their copy
        on disk, the log), so no later consolidation reads them again; with
        `cut`, a matching line keeps cut(its words) instead. The chat's
        checkpoint loses the sentences that match, here and in the summary
        row of every chat the page keeps. How many lines changed."""
        uid = channels.dm_user(conv)

        def keep(row) -> bool:
            text = row.get("text", row.get("content", "")) if isinstance(row, dict) else None
            return not (isinstance(text, str) and hit(text))

        removed = 0

        def filtered(rows):
            nonlocal removed
            out = []
            for row in rows:
                if keep(row):
                    out.append(row)
                    continue
                removed += 1
                if row.get("role") == CHECKPOINT:
                    left = _without_sentences(row["content"], hit)
                    out += [{**row, "content": left}] if left else []
                elif cut is not None:
                    key = "text" if "text" in row else "content"
                    out.append({**row, key: cut(row[key])})
            return out

        history = getattr(self, "dm_history", {})
        if uid and uid in history:
            history[uid] = filtered(history[uid])
        unanswered = getattr(self, "_dm_unanswered", {})
        if uid and uid in unanswered:
            unanswered[uid] = [t for t in filtered(
                [{"role": "user", "user_id": uid, "content": t} for t in unanswered[uid]])
                for t in [t["content"]]]
        recent = getattr(self, "_recent", None)
        snap = recent.snapshot(conv) if recent is not None else None
        if snap:
            before = removed
            snap["dm"] = filtered(snap.get("dm", []))
            if removed != before:
                recent.put(conv, snap)
        removed += self._page_checkpoints(lambda text: _without_sentences(text, hit) if hit(text) else text)
        removed += self._log_forget(conv, lambda row: not keep(row) and (cut(row["text"]) if cut else True))
        if removed:
            dirty = getattr(self, "_recent_dirty", None)
            if isinstance(dirty, set):
                dirty.add(conv)
        return removed

    def _mask_lines(self, conv: str, values: dict[str, str]) -> int:
        """Hide ID and card numbers, passwords and codes (secretwords.mask, with the turn's `values`) in this chat's recent
        lines, wherever _purge_lines walks, and in the steps its replies keep; how many lines changed."""
        changed = self._purge_lines(conv, lambda text: secretwords.mask(text, values)[1],
                                    lambda text: secretwords.mask(text, values)[0])
        # A step of the reply (dm.py keeps its words with it) may carry the number too.
        for row in getattr(self, "dm_history", {}).get(channels.dm_user(conv), []):
            if row.get("steps"):
                row["steps"] = [secretwords.mask(step, values)[0] for step in row["steps"]]
        return changed

    def _log_forget(self, conv: str, gone: Callable[[dict], object]) -> int:
        """Remove the lines `gone` is true for from the chat's log, and give
        those it returns words for those words; how many changed."""
        try:
            return self.chat_log.forget(conv, gone)
        except sqlite3.Error as e:
            logger.warning("[Agent] chat log not rewritten: %s", e)
            return 0

    def _forget_chat(self, conv: str) -> bool:
        """Forget this chat's lines: the turns, the recent file and the log.
        Nothing is restorable. Whether anything went."""
        changed = False
        self._forgot(conv)
        self.memory_state.drop_conv(conv)
        self._save_memory_state()
        uid = channels.dm_user(conv)
        by_reader = {uid, conv} - {""} if uid else set()
        for name, keys in (("window_seq", {conv}), ("dm_history", by_reader),
                           ("_dm_unanswered", by_reader)):
            held = getattr(self, name, None)
            if isinstance(held, dict):
                for key in keys:
                    if key in held:
                        held.pop(key)
                        changed = True
        recent = getattr(self, "_recent", None)
        if recent is not None and recent.drop(conv):
            changed = True
            dirty = getattr(self, "_recent_dirty", None)
            if isinstance(dirty, set):
                dirty.add(conv)
        try:
            changed = self.chat_log.drop(conv) or changed
        except sqlite3.Error as e:
            logger.warning("[Agent] chat log not removed: %s", e)
        changed = bool(self._page_checkpoints(lambda text: "", channels.dm_user(conv).split(":", 1)[-1])) or changed
        self._final_copies()
        return changed

    def _page_checkpoints(self, change: Callable[[str], str], conversation: str = "") -> int:
        """The page's summary row of every chat (dm.py keeps a chat's checkpoint there), or of the chat
        `conversation` alone, given change(its text) and written anew, so the page draws it again; one left empty
        becomes the mark of the clear before it, or goes; no older copy is left in the database. How many changed."""
        store = db.at(self.memory_file.parent)
        rows = store.read("SELECT chat, body FROM page_messages WHERE kind = 'summary'"
                          + (" AND chat IN (SELECT id FROM page_chats WHERE conversation = ?)" if conversation else ""),
                          (conversation,) if conversation else ())
        changed = []
        for ident, body in rows:
            mark = json.loads(body)
            text = change(mark["text"])
            if text == mark["text"]:
                continue
            if text:
                mark = {**mark, "text": text, "at": time.time()}
            elif mark.get("floor"):
                # The clear before it stays, so no turn from before the clear comes back (dm._page_turns).
                mark = {**mark, "text": "", "from": mark["floor"], "at": time.time(), "cleared": True}
            else:
                mark = None
            changed.append((ident, mark))
        if not changed:
            return 0
        with store.write() as conn:
            for ident, mark in changed:
                if mark:
                    conn.execute("UPDATE page_messages SET body = ? WHERE chat = ? AND seq = 0",
                                 (json.dumps(mark, ensure_ascii=False), ident))
                else:
                    conn.execute("DELETE FROM page_messages WHERE chat = ? AND seq = 0", (ident,))
        store.scrubbed()
        return len(changed)

    async def forget_chats(self, conversation: str, keep: list[str]) -> int:
        """Forget the lines of the chat `conversation`, with nothing kept to
        restore, and with it every chat the page no longer lists; the chats in
        `keep` stay. How many chats held lines."""
        from .dm import chat_key
        conv = chat_key(conversation)[1]
        kept = {chat_key(c)[1] for c in keep}
        count = 0
        for key in [conv, *sorted(self._page_convs() - kept - {conv})]:
            async with self.locks[key]:
                count += self._forget_chat(key)
        return count

    # ---- the one person of the app's own chats (person.py) ------------------

    def _person_chat(self, conv: str) -> bool:
        """The app's own chat with its one person: what it learns of them is
        kept once, in person.json, for every chat of theirs."""
        return channels.platform_of(conv) == PAGE_PLATFORM and bool(channels.dm_user(conv))

    @property
    def person_store(self) -> person.Person:
        """Loaded on first use. A damaged file raises MemoryFileDamaged."""
        store = self._sidecar("_person_store", person.Person,
                              self.memory_file.with_name(person.FILE))
        if store._data is None:
            store.load()
        return store

    def _save_person(self) -> None:
        try:
            self.person_store.save()
        except OSError as e:
            logger.warning("[Agent] person.json save failed: %s", e)

    def _page_convs(self) -> set[str]:
        """Every page chat the agent holds lines of: in the turns, the recent
        file or a log."""
        keys = {channels.dm_routing_key(u) for u in getattr(self, "dm_history", {})}
        recent = getattr(self, "_recent", None)
        if recent is not None:
            keys |= set(recent.convs)
        keys |= self.chat_log.private_chats(PAGE_PLATFORM)
        return {k for k in keys if self._person_chat(k)}

    def _tell_profile(self, rows: list[dict], now: float) -> None:
        """What the person said they like, do not want, or how they want to be
        treated also goes to the profile the finds are ranked by."""
        from . import profile
        runtime = today_runtime(self)
        for row in rows:
            kind, text = row.get("kind"), row["text"]
            try:
                if kind == "like":
                    profile.like(runtime, person.topic_of(text), now, words=text)
                elif kind == "dislike" and person.refuses(text):
                    about = person.about_of(row.get("slot", ""), text)
                    profile.dislike(runtime, person.topic_of(text), about, now, words=text)
                elif kind == "form":
                    short, form_kind = person.form_of(text)
                    if short is not None or form_kind is not None:
                        profile.form(runtime, short, form_kind, now, words=text)
                elif kind == "manner":
                    profile.manner(runtime, text, now)
            except (OSError, ValueError) as e:
                logger.warning("[Agent] profile not told (%s): %s", kind, e)

    def _person_turn(self, conv: str, said: str, reply: str) -> None:
        """After a sent reply: the plans it asked about (person.apply_turn); a turn they asked not to keep
        leaves its words only as hashes. What they said of themselves is the fold's. A number or a code said in
        it is masked in the chat's record: this turn saw it, no later one does."""
        values = {**secretwords.secret_values(said), **secretwords.secret_values(reply)}
        if values:
            self._mask_lines(conv, values)
        store = self.person_store
        now = time.time()
        if person.unsaid(said):
            store.tomb(said, now)
            self._save_person()
            logger.info("[Agent] person: a turn not kept (%s)", conv)
            return
        if store.on and person.apply_turn(store, reply, now, self._prompt_tz()):
            self._save_person()

    def _drop_unsaid(self, conv: str, said: str, reply: str) -> dict:
        """After the reply to a turn they asked not to keep: the turn, its
        reply too (which often repeats it), leaves the turns, the recent file
        and the log. What the page drops from its own copy."""
        lines = [said, reply]
        line_set = {" ".join(x.split()) for x in lines}
        self._purge_lines(conv, lambda text: " ".join(text.split()) in line_set
                          or any(" ".join(t.split()) in line_set for t in text.split("\n")))
        return {"lines": lines}

    def _person_command(self, conv: str, kind: str, arg: str, code: str) -> str:
        """A memory command in a page chat, on the one person's store."""
        spec = chatlangs.spec(code)
        store = self.person_store
        now = time.time()

        def say(key: str) -> str:
            return self._memory_reply(key, code)

        # A 无痕对话 neither reads nor keeps memory; a forget still works there.
        if kind in ("remember", "recall") and channels.private_chat(conv):
            return say("private")
        if kind == "remember":
            content = re.sub(spec.note_lead, "", arg.strip(), flags=re.IGNORECASE) if spec.note_lead else arg.strip()
            if not content.strip(_QUERY_TRIM):
                return say("remember_what")
            refused, kept = self._person_keep(conv, content, code, "command")
            if refused:
                return say(refused)
            colon, sep = personview.marks(code)
            return say("noted") + colon + sep.join(personsaid.second_person(words, code) for words in kept)
        if kind == "recall":
            lines = personview.listing(store, code)
            if not lines:
                return say("empty")
            lines = [_FULL_STOP_RE.sub(" ", line).strip() for line in lines]
            return say("recall_head") + "\n" + "\n".join(lines)
        if kind == "forget":
            query = _forget_query(arg, spec)
            if not query or query.lower() in spec.everything:
                return say("forget_what")
            if len(query) < (2 if _HAS_CJK.search(query) else 3):
                return say("forget_what")
            gone, lines = self._forget_everywhere(conv, [query], [], now, code=code)
            if not (gone or lines):
                return say("nothing_to_forget")
            # What went, named: the kept things it took, else the words it took from the chats.
            colon, sep = personview.marks(code)
            named = [personsaid.second_person(r["text"], code) for r in gone][:3] or [query]
            return say("forgotten") + colon + sep.join(named)
        # forget_that: what they said just before.
        lines = self._last_said(conv)
        if not lines:
            return say("forget_what")
        rows = [r for r in store.facts() + store.plans("open", "asked")
                if set(r.get("refs") or ()) & {seq for seq, _t in lines}
                or any(len(_focus_tokens(r["text"], "zh") & _focus_tokens(t, "zh")) >= 2
                       for _seq, t in lines)]
        texts = [t for _seq, t in lines] + [r["text"] for r in rows]
        words = self._telling_words([r["text"] for r in rows], conv, [t for _s, t in lines])
        replies = self._replies_after(conv, {seq for seq, _t in lines})
        gone, _lines = self._forget_everywhere(conv, words, texts, now, replies, code=code)
        colon, sep = personview.marks(code)
        named = [personsaid.second_person(r["text"], code) for r in gone][:3]
        return say("forgotten") + (colon + sep.join(named) if named else "")

    def _replies_after(self, conv: str, seqs: set[int]) -> list[str]:
        """The character's lines that answered the lines `seqs` names."""
        out, after = [], False
        for row in self._log_rows(conv) or self.chat_log.read(conv):
            if self._own_line(row):
                if after:
                    out.append(str(row.get("text") or ""))
            else:
                after = _num(row.get("seq"), int) in seqs
        return out

    def _last_said(self, conv: str) -> list[tuple[int, str]]:
        """(seq, text) of what the person said last before this command,
        going back over short lines ("嗯", "哎不想他了") up to three of theirs."""
        rows = [r for r in self._log_rows(conv) if not r.get("self") and isinstance(r.get("text"), str)]
        if not rows:
            rows = [r for r in self.chat_log.read(conv) if not self._own_line(r)]
        out = []
        for row in reversed(rows):
            text = row["text"].strip()
            if not text or self._parse_memory_command(text) is not None:
                continue
            out.append((_num(row.get("seq"), int), text))
            if len(_focus_tokens(text, "zh")) >= (8 if _HAS_CJK.search(text) else 5) or len(out) == 3:
                break
        return out

    def _telling_words(self, texts: list[str], conv: str, said: list[str]) -> list[str]:
        """The words that pick out a forgotten thing in other lines: the
        two-character pieces (or whole words) of its facts that no other line
        of this chat uses, outside what was said and the reply after it."""
        own = set()
        for text in texts:
            own |= {t for t in _focus_tokens(text, "zh") if len(t) >= 2}
        if not own:
            return []
        others = set()
        rows = self._log_rows(conv) or self.chat_log.read(conv)
        said_set = {" ".join(s.split()) for s in said}
        skip_next = False
        for row in rows:
            text = str(row.get("text") or "")
            if " ".join(text.split()) in said_set:
                skip_next = True
                continue
            if skip_next and self._own_line(row):
                skip_next = False
                continue
            skip_next = False
            others |= _focus_tokens(text, "zh")
        for fact in self.person_store.facts():
            if fact["text"] not in texts:
                others |= _focus_tokens(fact["text"], "zh")
        return sorted(own - others)

    def _forget_everywhere(self, conv: str, words: list[str], texts: list[str], now: float,
                           replies: Iterable[str] = (), *, chats: bool = True,
                           code: str = "") -> tuple[list[dict], int]:
        """Forget at once: the store's rows and summary, the profile, the
        trash and the daily copies; the words stay only as hashes. With
        `chats`, in every page chat each sentence holding them (turns, recent
        file, logs) becomes the forgotten mark of the language `code`, and
        what the page marks in its copies is left for the answer to carry;
        `replies` are this chat's answers to it, marked whole.
        Returns (the store rows that went, how many chat lines changed)."""
        store = self.person_store
        said = person.forget_hit(words, texts)
        replies = [r for r in replies if r.strip()]
        whole = {" ".join(r.split()) for r in replies}

        def hit(text: str) -> bool:
            return said(text) or " ".join(text.split()) in whole
        gone = store.forget(hit, now)
        for text in words + texts:
            store.tomb(text, now)
        self._save_person()
        try:
            memstore.refresh_backup(store.path)
        except OSError as e:
            logger.warning("[Agent] person.json daily copy not refreshed: %s", e)
        from . import profile
        tokens = list(words) + [person.topic_of(r["text"]) for r in gone] + [r["text"] for r in gone]
        try:
            profile.forget(today_runtime(self), tokens)
        except (OSError, ValueError) as e:
            logger.warning("[Agent] profile forget failed: %s", e)
        lines = 0
        code = code or self.chat_lang
        for room in self._page_convs() | {conv}:
            if chats:
                lines += self._purge_lines(room, hit, lambda text: person.scrub(text, hit, code))
            self._forgot(room)
        self._final_copies()
        if chats:
            self.__dict__.setdefault("_page_scrub", {})[conv] = {"words": list(words), "texts": list(texts),
                                                                 "lines": replies, "mark": code}
        logger.info("[Agent] forgotten: %d rows, %d chat lines", len(gone), lines)
        return gone, lines

    def _person_keep(self, conv: str, content: str, code: str, src: str) -> tuple[str, list[str]]:
        """A 记住 or an item added on the page: each thing it says, typed and slotted in code (a name names them, a
        new home replaces the old, a like or a dislike reaches the finds), a dated one as a plan. (the reply key
        when nothing is kept, the words of what was kept as said)."""
        store = self.person_store
        if not store.on:
            return "paused", []
        if secretwords.secret(content):
            logger.info("[Agent] person: a secret not kept")
            return "secret", []
        content = memgate.validate(content)
        if not content:
            return "not_instructions", []
        now = time.time()
        facts, kept = [], []
        for fact_kind, slot, text in personsaid.command_facts(content):
            if not store.keeps(fact_kind, text):
                continue
            due = fact_kind == "other" and timewords.resolve_future(text, now, self._prompt_tz(), (code,))
            if due:
                row = store.put_plan(text, due, now, conv=conv)
            else:
                row, _old = store.put_fact(fact_kind, slot, text, now, src=src, conv=conv, imp=4)
                facts.append(row)
            # A 记住 is no line of the chat's record: its words are kept with what it kept, for 查看原话.
            if src == "command":
                row["words"] = text
            kept.append(text)
        if not kept:
            return "health_off", []
        self._save_person()
        self._tell_profile(facts, now)
        return "", kept

    def _person_settings(self, on: bool | None, health: bool | None) -> None:
        """Settings › 记忆's two switches. Memory turned on again does not fold what was said while it was off."""
        store = self.person_store
        use = store.data["use"]
        if on is True and not use["on"]:
            _rows, newest = self._person_lines(store)
            upto = store.data["fold"].setdefault("upto", {})
            for key, seq in newest.items():
                upto[key] = max(int(upto.get(key) or 0), seq)
        if on is not None:
            use["on"] = on
        if health is not None:
            use["health"] = health
        self._save_person()
        logger.info("[Agent] person: memory %s, health details %s", "on" if use["on"] else "off",
                    "kept" if use["health"] else "not kept")

    def _person_said(self, item_id: str) -> list[dict] | None:
        """The chat lines a fact or a plan was kept from, as the log still has them; None when the item is gone."""
        row = self.person_store.get(item_id)
        if row is None:
            return None
        if row.get("words"):
            return [{"text": row["words"], "at": _num(row.get("born"))}]
        if not (row.get("conv") and row.get("refs")):
            return []
        return [{"text": str(r.get("text") or ""), "at": _num(r.get("t"))}
                for r in self.chat_log.lines(row["conv"], chatlog.refs_of(row))]

    def _person_import_preview(self, text: str) -> list[dict]:
        """Another assistant's memory list, pasted: each item as it would be kept, or why it would not be (a
        secret, words that read as instructions, kept already, a health detail they do not keep). Data only."""
        store = self.person_store
        texts = {f["text"] for f in store.facts()}
        out = []
        for line in personsaid.pasted_lines(text):
            words = person.neutral(line)
            why = ("secret" if secretwords.secret(line) else "not_instructions" if not memgate.validate(line)
                   else "kept" if words in texts
                   else "health_off" if not store.data["use"]["health"] and person.health("", words) else "")
            out.append({"text": words, "ok": not why, "why": why})
            texts.add(words)
        return out

    def _person_import(self, lines: list[str], conv: str) -> int:
        """The items they ticked, each kept as one fact through the same checks as the preview; how many were."""
        store = self.person_store
        if not store.on:
            return 0
        now = time.time()
        rows = []
        for line in lines:
            words = person.neutral(line)
            if not words or secretwords.secret(words) or not memgate.validate(words):
                continue
            # Typed by what the person's own 记住 would say: Chinese "喜欢爬山" reads as "我喜欢爬山".
            chinese = re.match(r"[一-鿿]", words) and not re.search(r"[぀-ヿ가-힯]", words)
            kind, slot = personsaid._command_kind(("我" + words) if chinese else words)
            if store.keeps(kind, words):
                row, _old = store.put_fact(kind, slot, words, now, src="import", conv=conv, imp=3)
                rows.append(row)
        if rows:
            self._save_person()
            self._tell_profile(rows, now)
        logger.info("[Agent] person: %d imported item(s)", len(rows))
        return len(rows)

    def _person_restore(self, tid: str) -> dict | None:
        """Put a replaced or edited fact or plan back from the person's trash;
        a fact reaches the profile again too."""
        now = time.time()
        row = self.person_store.restore(tid, now)
        if row is not None:
            self._save_person()
            if row.get("kind"):
                self._tell_profile([row], now)
        return row

    # ---- the page's own view of the store (dashboard.py) ----------------------

    def _person_forget(self, conv: str, item_id: str, chats: bool = False) -> dict | None:
        """Forget one fact or plan from the page's view, with no undo; with
        `chats`, also from the chats as a forget in the chat does. What the
        page marks in its copies ({} for none), or None when the item is
        already gone."""
        row = self.person_store.get(item_id)
        if row is None:
            return None
        texts = [row["text"]] + ([row["said"]] if row.get("said") else [])
        # In the chats, also the lines that name its thing ("芒果" of "我对芒果过敏").
        words = texts + ([personsaid.thing_of(row)] if chats and personsaid.thing_of(row) else [])
        self._forget_everywhere(conv, words, texts, time.time(), chats=chats)
        return self.__dict__.get("_page_scrub", {}).pop(conv, {})

    def _person_edit(self, item_id: str, text: str) -> dict | None:
        """The person's own words for one fact or plan; the old ones go to
        the trash, to be put back. None when the item or the words fail."""
        text = memgate.validate(text, max_chars=person.TEXT_MAX)
        if not text:
            return None
        now = time.time()
        row = self.person_store.edit(item_id, text, now)
        if row is None:
            return None
        self._save_person()
        if not item_id.startswith("p"):
            self._tell_profile([row], now)
        return row

    def _person_forget_all(self) -> int:
        """Everything the store knows of the person goes, and from the profile
        too; what they said in the chats stays until those are forgotten."""
        from . import profile
        store = self.person_store
        texts = [r["text"] for r in store.facts(active=False) + store.plans()]
        now = time.time()
        n = store.forget_all(now)
        self._save_person()
        try:
            memstore.refresh_backup(store.path)
        except OSError as e:
            logger.warning("[Agent] person.json daily copy not refreshed: %s", e)
        try:
            profile.forget(today_runtime(self), texts + [person.topic_of(x) for x in texts])
        except (OSError, ValueError) as e:
            logger.warning("[Agent] profile forget failed: %s", e)
        logger.info("[Agent] person: forgot everything (%d rows)", n)
        return n

    def _memory_reply(self, key: str, code: str) -> str:
        return random.choice(_COMMAND_REPLIES[code][key])

    def _memory_cmd_patterns(self) -> list:
        """[(code, spec, {kind: regex or [regexes]})] for every chat language,
        cached per persona_name and aliases. The name may be left out, and
        the fillers a chat language allows may come first ("算了，忘掉阿杰")."""
        names = (self.persona_name, tuple(getattr(self, "persona_aliases", ())))
        cached = getattr(self, "_mem_cmd_pats", None)
        if cached and cached[0] == names:
            return cached[1]
        # Anchored at the start, so "I don't remember..." stays conversation.
        lead = r"^\s*(?:\[reply\]\s*)?"
        name = names_regex(*names)
        sep = r"\s*[：:，,]?\s*"
        table = []
        for code, spec in chatlangs.SPECS.items():
            vocative = f"(?:{spec.vocative})?" if spec.vocative else ""
            filler = (rf"(?:(?:{spec.lead_in})[\s，,、:：!！.。~～]*)*" if spec.lead_in else "")
            called = (r"(?:(?:@\S+\s*)*?@?" + name + vocative + r"\s*[，,:：、]?\s*)?") if name else ""
            head = lead + called + filler
            remember = [re.compile(head + f"(?:{spec.remember})" + spec.not_a_note
                                   + sep + r"(.+)", re.IGNORECASE)]
            forget = [re.compile(head + f"(?:{spec.forget})" + spec.not_a_delete
                                 + sep + r"(.+)", re.IGNORECASE)]
            # The verb-last forms: everything between the name and the keyword.
            end = r"[\s!！.。~～]*$"
            if spec.remember_last:
                remember.append(re.compile(
                    head + r"(.+?)\s*" + f"(?:{spec.remember_last})" + end, re.IGNORECASE))
            if spec.forget_last:
                forget.append(re.compile(
                    head + r"(.+?)\s*" + f"(?:{spec.forget_last})" + end, re.IGNORECASE))
            # Recall must be the whole message: "小夏 记忆力真好" is a compliment.
            tail = r"\s*" + (f"(?:{spec.recall_tail})?" if spec.recall_tail else "")
            table.append((code, spec, {
                "remember": remember,
                "forget": forget,
                "recall": re.compile(head + f"(?:{spec.recall})" + tail
                                     + r"[\s?？!！.。~～]*$", re.IGNORECASE),
            }))
        self._mem_cmd_pats = (names, table)
        return table
