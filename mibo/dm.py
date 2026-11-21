"""The chat with the one person: their message read, a memory command run or
a turn of the model, and what the character says."""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time

from . import channels
from . import person
from . import today
from .llm import purpose
from .ingestion import reads_own_pictures
from .messages import turn_pictures
# A draft with nothing to send would come back identical from an unchanged
# prompt, so the one retry carries a note.
from .decision import EMPTY_DRAFT_RETRY_NOTE as _EMPTY_DRAFT_RETRY_NOTE
from .decision import PASS, SEND, is_pass_sentinel
from .search import ChatLookups
from .schedule_tool import run_of
from .turns import OutOfTime, Turn, current_turn
from .textproc import (
    TextProcessing,
    _as_protocol_object,
    _detect_image_mime,
    _strip_web_desc,
    salvage_json_object,
    strip_json_fences,
)

logger = logging.getLogger("agent")

# The empty-draft note's contract, for a draft that was PASS.
_PASS_DRAFT_RETRY_NOTE = (
    "Your previous draft was PASS, but a private chat has no PASS: the person "
    "is waiting for an answer. Emit the same JSON object again — same keys, "
    "same shape — with a `reply` of at least one word."
)
# A tool round answers without response_format, so a model may answer in prose:
# the final answer is then asked for once more as the protocol object, in JSON mode.
_OBJECT_AGAIN_NOTE = (
    "[Note from the app, not from them] Your answer came as plain text. Give it "
    "again as the one JSON object of <output_protocol>, with the same reply. In mem, "
    "an operation for each lasting thing about themselves that their last message "
    "says (who they are, where they live, family and friends, what they like or do "
    "not want, how long or in what form they want things, health, how they want you "
    "to treat or call them, a plan with its day words) and <about_them> does not show "
    "yet; [] only when it says none. When it says what they think of a find you "
    "shared, also its card operation."
)

# The name the person's turns are kept under; the prompt calls them by the name they gave (ADMIN_NAME).
_THEM = "you"

_DM_HISTORY_MAX = 60
_DM_HISTORY_KEEP = 40

# Joined to the system prompt of the answer asked for once a turn's tools have ended without one.
_TOOLS_OVER_NOTE = (
    "[Note from the app, not from them] Your tools have ended for this message, and this "
    "answer is the last thing they see for it. If the message asked for something to be "
    "looked up or done, say plainly what was done (it is under [What you looked up this "
    "turn] when anything was) and what was not; never say you will look, check, search or "
    "do it, and never ask them to wait: nothing runs after this answer. If it asked for "
    "nothing of the kind, just answer."
)

# The owner's turn on the page looks things up itself (`_reply_with_tools`); a
# context, so no fake `_chat_dm` needs a new argument or return value. None: no tools.
chat_lookups: contextvars.ContextVar[ChatLookups | None] = contextvars.ContextVar(
    "chat_lookups", default=None)
# What a tool is doing in the page's chat, which the page process reads (welcome.py).
CHAT_DOING_FILE = "chat-doing.json"


def _wonder_of(raw: str) -> str:
    """The protocol's optional `wonder`: a few search words the character
    wants to look into later, or ""."""
    data = salvage_json_object(strip_json_fences(raw or ""))
    words = data.get("wonder") if isinstance(data, dict) else None
    return " ".join(words.split())[:80] if isinstance(words, str) else ""


def _mem_of(raw: str, mem: str):
    """The protocol's `mem`: the list of operations a reply writes in the
    app's own chat, else the plain note `_parse_model_output` read."""
    data = salvage_json_object(strip_json_fences(raw or ""))
    ops = data.get("mem") if isinstance(data, dict) else None
    return ops if isinstance(ops, list) else mem


# A prose answer's own "mem: ..." lines (a weak model's way of writing the
# operations): never shown.
_PROSE_MEM = re.compile(r"^[ 	]*mem[ 	]*[:：][ 	]*(.*)$", re.IGNORECASE | re.MULTILINE)


def _prose_answer(text: str) -> str:
    """A prose answer as the protocol object, without its "mem:" lines."""
    # Prose with the protocol object written after it: the object is the answer.
    data = salvage_json_object(text)
    if isinstance(data, dict) and isinstance(data.get("reply"), str):
        return json.dumps(data, ensure_ascii=False)
    if not _PROSE_MEM.search(text):
        return _as_protocol_object(text)
    return json.dumps({"reasoning": "", "intent": "chat", "reply": _PROSE_MEM.sub("", text).strip(), "mem": []},
                      ensure_ascii=False)


def _with_found(messages: list[dict], found: str) -> list[dict]:
    """`messages` with what this turn's lookups found ahead of the last turn,
    for the answer asked for without tools."""
    last = messages[-1]
    head = f"[What you looked up this turn]\n{found}\n\n"
    content = last["content"]
    if isinstance(content, list):
        content = [{**content[0], "text": head + content[0]["text"]}, *content[1:]]
    else:
        content = head + content
    return messages[:-1] + [{**last, "content": content}]


def _done_so_far(lookups: ChatLookups) -> str:
    """What a turn had done when its time ran out: the steps in its trace, and a computer task's own note."""
    from .shell import tool as shell_tool
    steps = "; ".join(f"{step['tool']} {step['what']}".strip() for step in lookups.trace)
    return "\n".join(line for line in (
        f"(the time for this message ran out while you were working; steps taken: {steps or 'none finished'})",
        shell_tool.out_of_steps(lookups, len(lookups.trace))) if line)


def _trimmed_history(history: list[dict]) -> list[dict]:
    """Drop a batch of old turns at once: dropping a little every turn would
    shift the whole history and lose its prefix cache each time."""
    return history[-_DM_HISTORY_KEEP:] if len(history) > _DM_HISTORY_MAX else history


def _page_turns(path, conversation: str) -> list[dict]:
    """The page's own saved copy of its chat (browser-chat.json) as turns,
    for a page chat that has no recent window yet; [] if it is another chat."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(saved, dict) or str(saved.get("conversation") or "") != conversation:
        return []
    turns: list[dict] = []
    for message in saved.get("messages") or []:
        # A message that was never answered is shown to the person, not a turn the character had.
        if not isinstance(message, dict) or message.get("failed"):
            continue
        role, text = message.get("role"), message.get("text")
        if not isinstance(text, str):
            continue
        # What the person attached, as their turn named it.
        attached = [f"[file: {a.get('file')}]" if a.get("kind") == "file" else "[image]"
                    for a in message.get("attachments") or []]
        text = "\n".join(t for t in (text, *attached) if t.strip())
        if role not in ("user", "assistant") or not text.strip():
            continue
        # One turn per side in a row, as the history keeps them.
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    # The words still waiting for this answer are the turn being answered.
    while turns and turns[-1]["role"] == "user":
        turns.pop()
    return turns[-_DM_HISTORY_KEEP:]


def chat_key(conversation: str) -> tuple[str, str]:
    """The names a chat of the page goes by inside: its reader and its key (channels.py)."""
    user_id = f"{channels.PAGE_PLATFORM}:{conversation}"
    return user_id, channels.dm_routing_key(user_id)


class DirectMessages:
    async def answer(self, conversation: str, parts: list[dict], *, choices=(),
                     run: dict | None = None) -> list[dict]:
        """One message of the person's in the chat `conversation`, answered: a
        memory command carried out, or a turn of the model. `parts` as
        `_read_message` takes them; `choices` what they chose for this message
        (turns.TURN_CHOICES); `run` a scheduled task's run in place of words of
        theirs. What the character says (turns.Turn.said): a line said because
        the model did not answer carries "reason": "excuse"."""
        user_id, pkey = chat_key(conversation)
        turn = Turn(choices, run)
        token = current_turn.set(turn)
        try:
            # One turn of a chat at a time; the follow-up of a plan waits its turn too.
            async with self.turn_locks[pkey]:
                await self._answer(user_id, pkey, parts)
        finally:
            current_turn.reset(token)
        texts = [item for item in turn.said if item.get("type") == "text"]
        if turn.thinking and texts:
            texts[-1]["thinking"] = turn.thinking
        if run and run.get("spent"):
            # A run's model use, for its record on the page (panels/schedule.py).
            turn.said.append({"type": "spent", "spent": run["spent"]})
        return turn.said

    async def _answer(self, user_id: str, pkey: str, parts: list[dict]) -> None:
        # A reply model that is shown pictures gets theirs itself; a vision model reads them
        # out whole for one that is not.
        pictures = [] if self._shows_pictures() else None
        shown = turn_pictures.set(pictures)
        own = reads_own_pictures.set(True)
        try:
            text = await self._read_message(parts)
        finally:
            turn_pictures.reset(shown)
            reads_own_pictures.reset(own)
        if not text:
            return
        # Without what was fetched or attached: a page or a file can run no memory command.
        typed = _strip_web_desc(text)
        self.last_dm_activity_at[user_id] = time.time()
        if self._parse_memory_command(typed) is not None:
            # No model call, no turn of the history.
            said = self._say(self._handle_memory_command(pkey, typed) or "", by_line=True)
            # What a forget took out of every chat: the page drops it from its own copies (welcome.py).
            scrub = vars(self).get("_page_scrub", {}).pop(pkey, None)
            if scrub and said:
                said[-1]["scrub"] = scrub
            return
        self._wake(pkey)
        self.__dict__.setdefault("_dm_heard_at", {})[user_id] = time.time()
        self._recent_dirty.add(pkey)
        # Kept until a reply to them is committed: a turn that failed leaves its words for the next.
        self._dm_unanswered.setdefault(user_id, []).append(text)
        if pictures:
            self.__dict__.setdefault("_dm_pictures", {}).setdefault(user_id, []).extend(pictures)
        await self._dm_turn(user_id, pkey, text)

    @staticmethod
    def _say(text: str, *, by_line: bool = False) -> list[dict]:
        """The character's words into the turn being answered: one message, or
        with `by_line` one per line (a memory command's answer). The messages said."""
        text = TextProcessing._sanitize_reply(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()] if by_line else [text]
        said = [{"type": "text", "text": line} for line in lines if line]
        current_turn.get().said.extend(said)
        return said

    def _commit_dm_history(self, user_id: str, pkey: str, history: list[dict]) -> None:
        """Keep `history` as the reader's turns, trimmed; the unconsolidated
        turns the trim drops wait in the DM spill for consolidation."""
        before = self.dm_history.get(user_id, [])
        kept = _trimmed_history(history)
        held = {id(turn) for turn in kept}
        folded = self.folded_upto.get(pkey, 0)
        dropped = {id(turn): turn for turn in [*before, *history]
                   if id(turn) not in held and int(turn.get("seq") or 0) > folded}
        if dropped:
            self._spill_rows(pkey, sorted(dropped.values(),
                                          key=lambda turn: int(turn.get("seq") or 0)),
                             dm_reader=user_id)
        self.dm_history[user_id] = kept
        vars(self).get("_dm_heard_at", {}).pop(user_id, None)
        self._recent_dirty.add(pkey)
        self._maybe_flush_recent()

    def _rehydrate_page(self, user_id: str, pkey: str) -> None:
        """A page chat with no turns held reads the page's saved copy once."""
        if user_id in self.dm_history:
            return
        done = self.__dict__.setdefault("_page_rehydrated", set())
        if pkey in done:
            return
        done.add(pkey)
        turns = _page_turns(self.memory_file.parent / "desktop" / "browser-chat.json",
                            user_id.split(":", 1)[-1])
        for turn in turns:
            turn["t"], turn["seq"] = 0.0, self._next_seq(pkey)
        if turns:
            self.dm_history[user_id] = turns
            self._recent_dirty.add(pkey)

    async def _dm_turn(self, user_id: str, pkey: str, text: str) -> None:
        """One turn of the model: the call under the turn's time budget, the
        reply said, the history committed."""
        # The person's words this turn; kept for their next turn unless committed.
        said: list[str] = []
        committed = False
        conversation = user_id.split(":", 1)[-1]
        lookups = ChatLookups(self.memory_file.parent / "desktop" / CHAT_DOING_FILE, conversation)
        context = chat_lookups.set(lookups)
        # Where the stop button finds this turn (`stop_turn`).
        vars(self).setdefault("_page_turns", {})[conversation] = lookups
        try:
            async with self.locks[pkey]:
                self._rehydrate_page(user_id, pkey)
                history = list(self.dm_history.get(user_id, []))
                # Everything taken in since the last committed reply is one
                # user turn, so two user turns never sit in a row.
                said = list(self._dm_unanswered.get(user_id) or [text])
                # Shown with this turn only: later turns read their place as [image].
                pictures = vars(self).get("_dm_pictures", {}).pop(user_id, [])
                heard = vars(self).get("_dm_heard_at", {}).get(user_id)
                history.append({"role": "user",
                                "content": "\n".join(said),
                                "name": _THEM, "t": heard or time.time(),
                                "seq": self._next_seq(pkey)})
                history = _trimmed_history(history)

            cue = {"pictures": pictures} if pictures else {}
            # Only this await is stopped: the commit below runs whole or not at all.
            lookups.work = asyncio.current_task()
            lookups.doing("recall")
            try:
                try:
                    try:
                        reply, auto_mem = await self._within_turn_budget(self._chat_dm(
                            history, pkey=pkey, **cue))
                    except OutOfTime:
                        if not (lookups.trace or lookups.__dict__.get("steps")):
                            raise
                        # Work was under way: one more call says what was done, in place of a failure line.
                        reply, auto_mem = await asyncio.wait_for(self._chat_dm(
                            history, pkey=pkey, out_of_time=True, **cue), self.llm_timeout_s)
                finally:
                    stoppable = lookups.work
                    lookups.work = None
            except asyncio.CancelledError:
                if not lookups.stopped:
                    raise
                # Python 3.11+ counts cancels; this one is handled here.
                getattr(stoppable, "uncancel", lambda: None)()
                # Stopped by the person: no excuse, and the words are not carried into the next turn.
                logger.info("[Agent] turn stopped by the person (chat=%s)", conversation)
                said = []
                self._dm_unanswered.pop(user_id, None)
                return
            except Exception as e:
                logger.warning("[Agent] model call failed: %s", e)
                # Told to the waiting person in place of an answer, marked so the page shows its own
                # error; not committed to the history.
                for item in self._say(self._model_failure_excuse(text)):
                    item["reason"] = "excuse"
                return
            if not reply:
                return

            final = self._final_reply(reply, log_ctx=f"chat={conversation}")
            if final.verdict == PASS:
                logger.info("[Agent] PASS (chat=%s)", conversation)
            if final.verdict != SEND:
                return
            reply = final.text
            texts = self._say(reply)
            if lookups.trace and texts:
                # Shown under the reply and kept with it (welcome.py); the trace is what it looked up.
                texts[-1]["sources"], texts[-1]["trace"] = lookups.sources, lookups.trace
            if texts and lookups.feedback:
                # What the person said of finds; the page keeps it in the feed (welcome.py).
                texts[-1]["feedback"] = lookups.feedback
            if texts and lookups.bring:
                # The find it brought, as a card under the reply, the way the share step posts one.
                from . import life
                from .library import Library
                item = Library(today.runtime_of(self)).get(lookups.bring)
                card = life.said(item).get("card") if item is not None else None
                if card:
                    texts[-1]["card"] = card

            asked = "\n".join(said)
            unsaid = bool(person.unsaid(asked))
            async with self.locks[pkey]:
                history.append({"role": "assistant", "content": reply,
                                "t": time.time(), "seq": self._next_seq(pkey),
                                # What it did on the way, short: the next turns read it (prompt._recent_steps).
                                **({"steps": [f"{s['tool']} {s.get('what') or ''}".strip()[:160]
                                              for s in lookups.trace[-12:]]} if lookups.trace else {})})
                self._commit_dm_history(user_id, pkey, history)
                self._dm_unanswered.pop(user_id, None)
                committed = True
                private = channels.private_chat(pkey)
                if not run_of() and not private:
                    # The one person's store, which every chat reads (person.py); a scheduled run's
                    # request is not something they said now, and a 无痕对话 keeps nothing.
                    self._person_turn(pkey, asked, reply, auto_mem)
                if unsaid:
                    scrub = self._drop_unsaid(pkey, asked, reply)
                    if texts:
                        texts[-1]["scrub"] = scrub
                used = self._mark_used(pkey, reply)
                if used and texts:
                    # The memories the reply drew on, listed under it with edit and forget (activity.js).
                    texts[-1]["memory"] = {"used": used}
                self._maybe_consolidate(pkey, "trim")
            # Never the words: what they say may be forgotten later.
            logger.info("[Agent] reply (chat=%s, %d chars)", conversation, len(reply))
            if lookups.wonder and not private:
                # Something the talk made it want to look into: a walk goes for it as soon as it may.
                if today.wonder(self.memory_file.parent, lookups.wonder, time.time()) and getattr(self, "roam", None):
                    self.roam.request()
        finally:
            # No await: this also runs when the turn is cancelled. A scheduled run that said nothing
            # leaves nothing for their next turn.
            if said and not committed and not run_of():
                self._dm_unanswered[user_id] = said
                self._recent_dirty.add(pkey)
            chat_lookups.reset(context)
            lookups.done()
            if vars(self).get("_page_turns", {}).get(conversation) is lookups:
                del self._page_turns[conversation]

    def stop_turn(self, conversation: str) -> bool:
        """Cancel the reply under way in the chat `conversation`: its model
        and tool calls stop, and nothing of it is said or kept."""
        lookups = vars(self).get("_page_turns", {}).get(conversation)
        if lookups is None or lookups.work is None:
            return False
        lookups.stopped = True
        lookups.work.cancel()
        return True

    async def _chat_dm(self, history: list[dict], pkey: str = "", follow_up: str = "",
                       pictures: list[bytes] = (), out_of_time: bool = False) -> tuple[str, str]:
        """One model turn of the chat `pkey` (LLM_DM_MODEL). `follow_up`: nobody
        wrote; the note says which plan of theirs to ask after (proactive.py),
        and the turn uses no tools. `pictures` go with the last turn for the
        model to see itself. `out_of_time`: the turn's time ran out with work
        under way, so this call only says what was done, without tools.
        Returns (reply, memory)."""
        await self._prepare_retrieval(self._last_user_text(history), pkey)
        prompt = self._build_dm_prompt(history, pkey=pkey, follow_up=follow_up,
                                       pictures=len(pictures))
        system, messages = prompt.system, prompt.messages
        # A turn of the person's: the reply model looks things up itself below.
        lookups = None if follow_up else chat_lookups.get()
        messages = prompt.messages_with_context(messages)
        if pictures:
            # Image parts after the words; an endpoint that refuses them gets the words alone (endpoints.py).
            urls = [await self._vision_data_url(data, _detect_image_mime(data)) for data in pictures]
            last = messages[-1]
            messages = messages[:-1] + [{**last, "content": [
                {"type": "text", "text": last["content"]},
                *({"type": "image_url", "image_url": {"url": url}} for url in urls if url)]}]

        async def draft(system_text: str) -> tuple[str, str]:
            with purpose("reply"):
                raw = await self._call_llm(
                    system=system_text,
                    messages=messages,
                    model=self.llm_dm_model,
                    max_tokens=4096,
                    # No hidden reasoning: the protocol carries its own `reasoning` field.
                    disable_thinking=True,
                    json_object=True,
                    # `reply` is the whole schema, so recovered prose is unambiguous.
                    plain_text_fallback=True,
                )
            return parsed(raw)

        def parsed(raw: str) -> tuple[str, str]:
            reply, reasoning, intent, mem = TextProcessing._parse_model_output(
                raw, self.llm_dm_model)
            if reasoning:
                logger.debug("[Agent] DM model metadata parsed (intent=%s, reasoning_chars=%d)",
                             intent or "?", len(reasoning))
            if lookups is not None:
                lookups.wonder = _wonder_of(raw) or lookups.wonder
            return reply, _mem_of(raw, mem)

        answer = ""
        if out_of_time:
            messages = _with_found(messages, _done_so_far(lookups))
        elif lookups is not None:
            from .skills import offer as skill_offer
            from .skills import tool as skill_tool
            run = run_of()
            if run is None:
                # A market skill the message plainly fits, offered on a card first (skills/offer.py); a scheduled
                # run has nobody to answer a card.
                await skill_offer.offer(self, self._last_user_text(history), lookups)
            # The skills that fit the message, or a run's request: listed for use_skill, or put in the prompt
            # (skills/tool.py).
            system = skill_tool.before(self, system, run["words"] if run else self._last_user_text(history), lookups)
            answer, found = await self._reply_with_tools(system, messages, self.llm_dm_model, lookups,
                                                         said=self._last_user_text(history))
            system = skill_tool.after(self, system, lookups)
            if found:
                messages = _with_found(messages, found)
            # Asked without response_format: the object once more in JSON mode, else
            # prose is the reply, as in `_call_llm`.
            if answer and not re.sub(r"^```(?:json)?\s*", "", answer, flags=re.IGNORECASE).startswith(("{", "[")):
                answer = (await self._object_again(system, messages, answer, self._last_user_text(history))
                          or _prose_answer(answer))
        if lookups is not None and not answer:
            system += "\n\n" + _TOOLS_OVER_NOTE
        reply, mem = parsed(answer) if answer else await draft(system)
        # An answer to the person has no PASS, so a draft that would say nothing is
        # retried once; a follow-up's empty draft is the character declining.
        # A watch whose condition does not hold says PASS (panels/schedule.py).
        note = "" if follow_up or (run_of() or {}).get("kind") == "watch" else self._draft_retry_note(reply)
        if note:
            logger.info("[Agent] DM draft would send nothing, retrying once")
            # The protocol block ends without a newline.
            retry_reply, retry_mem = await draft(system + "\n\n" + note)
            # The first draft's memory is still a fact about the conversation.
            reply, mem = retry_reply, (retry_mem or mem)
        if lookups is not None and isinstance(mem, list):
            # What they said of a find, as an operation: kept the way note_reaction keeps it.
            for op in mem:
                if (isinstance(op, dict) and op.get("op") == "card" and op.get("verdict") in ("like", "skip")
                        and not any(f["id"] == str(op.get("id") or "") for f in lookups.feedback)):
                    self._note_reaction({"id": str(op.get("id") or ""), "liked": op["verdict"] == "like",
                                         "words": self._last_user_text(history).rsplit(chr(3), 1)[-1]}, lookups)
        return reply, mem

    async def _object_again(self, system: str, messages: list[dict], prose: str, said: str) -> str:
        """The protocol object for a tool round's prose answer, asked once in
        JSON mode with the prose as the draft; "" when the prose already
        carries the object or its mem lines, or the second ask brings none."""
        data = salvage_json_object(prose)
        if (isinstance(data, dict) and isinstance(data.get("reply"), str)) or _PROSE_MEM.search(prose):
            return ""
        try:
            with purpose("reply"):
                raw = await self._call_llm(
                    system=system,
                    messages=messages + [{"role": "assistant", "content": prose},
                                         {"role": "user", "content": _OBJECT_AGAIN_NOTE + "\nTheir last message: "
                                          + json.dumps(str(said)[:300], ensure_ascii=False)}],
                    model=self.llm_dm_model, max_tokens=4096,
                    disable_thinking=True, json_object=True)
        except Exception as e:
            logger.warning("[Agent] protocol object not asked again: %s", type(e).__name__)
            return ""
        data = salvage_json_object(strip_json_fences(raw or ""))
        if isinstance(data, dict) and isinstance(data.get("reply"), str) and data["reply"].strip():
            return json.dumps(data, ensure_ascii=False)
        return ""

    def _draft_retry_note(self, reply: str) -> str:
        """The note for a second draft when this one would send nothing: a
        PASS, or no words; else ""."""
        if is_pass_sentinel(reply):
            return _PASS_DRAFT_RETRY_NOTE
        return "" if self._final_reply(reply, log_ctx="DM draft").verdict == SEND else _EMPTY_DRAFT_RETRY_NOTE
