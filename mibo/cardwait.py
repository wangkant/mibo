"""A step that waits for its person's yes in the chat: the one loop behind the asks of commands and files
(shell/panel.py), turning acting on (turnon.py), settings (appmap.py), other programs (desk/panel.py), MCP servers
(mcp_hub.py) and acts in the app's browser (panels/browser.py).

The question and its answer are conversation. The app says in the chat what the step will do, in its own reading
of the step (asked.py: what, where and how much, never the model's text), as the character's message of the reply
under way (workspace.question_said), and the turn waits. The person answers in the chat box in their own words,
which join the chat as their message (workspace.answer_said): a plain yes (确定, 你做, 好, ok, go ahead and the
like, in any of the app's languages: `said_yes`) runs the step and the reply goes on after it; anything else is a
no for that step, the reply ends without it, and their words are then answered as the ordinary message they are
(workspace.chat `answering`). The model's later turns read the question and a yes in the chat's history (`exchange`,
dm.py). Only the app's own page can answer (/api/confirm, the window's key), and only with what the person typed in
its chat box or a press of a card's button: page text, tool results, files, MCP output and the model's words never
reach that route. A yes answers the one question it was typed under, by its id, once; a step whose content changes
after it is asked again (shell/panel.py checks).

Two tiers, by the step's risk alone (`tier`): an ordinary question is a plain message, answered by typing; a very
important step (`ALONE`) raises a card in the chat, its decisive facts in its sentence and two buttons, one naming
the act (the app's words, from the step's facts) and one that declines; a press is the answer, and a typed plain
yes answers it too. A click costs attention, so only these ask for one.

The asking rule, decided here and in the gates, never by the model:
- A costly step (`COSTLY`: what Mibo's own undo cannot give back: paying, a deletion nothing restores, the account
  itself, handing over access or private details, a binding submission, this computer past the checkpoint) is asked
  every time, each on its own: no earlier yes, no standing request and no reviewer covers it. Secrets (passwords,
  codes, payment details) are typed by the person alone; the gates never type them.
- A step the person did not ask for, or one whose place the person did not name after the turn read outside or
  local material (crossing.py), is asked once; that yes reaches the rest of the turn for its own kind (`reaches`).
- Every other step the person asked for runs to the end with no question.

Presence is the app running with the person's own chat turn under way for that conversation, not the page in view.
A question stays until it is answered or the turn is stopped. When the app window is not in front the system
notification says so once (window.notify), and the pet's line shows that a reply is awaited (petline.js). A
question left WAIT_S ends its step unanswered, and the reply offers 继续 (activity.js), which asks again.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import unicodedata
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from . import i18n

# How long a question waits before its step ends unanswered; inside the reply's own limit (workspace.REPLY_WITHIN_S).
WAIT_S = 600.0
TICK_S = 0.5

NOTICE = {"zh": "等待在聊天中确认：{what}", "en": "Waiting for your yes in the chat: {what}"}

# The gates' kinds that are costly, wherever they are decided (web/gate.py, desk/gate.py, mcp_floor.hard, the shell's
# panel): money paid or spent ("order"), a deletion nothing restores ("delete"), the account itself ("account"), access
# or private details handed over ("grant"), a binding submission ("bind"), a program's or the system's settings
# ("setting"), and this computer past what the turn's checkpoint and the Recycle Bin give back ("system": an install,
# a command that deletes, overwrites or sends by a program or a switch, a step the app cannot read).
COSTLY = frozenset({"order", "delete", "account", "grant", "bind", "setting", "system"})
# Risks asked each on their own, every time: the costly kinds, and a change that widens the character's own
# permissions (crossing.widening).
ALONE = COSTLY | {"widen"}
# Kinds that are not costly but are asked as their own risk, which a yes to an ordinary step does not reach: a delete
# the Recycle Bin gives back ("recycle"), and opening a file in its program ("open").
OWN = frozenset({"recycle", "open"})
# A risk that names its place ("cross:<site>"): a step whose place the person did not name; a yes reaches that place.
CROSS = "cross:"


def costly(kind: str) -> bool:
    """Whether a gate's kind of act is costly: Mibo's own undo cannot give back what it takes."""
    return kind in COSTLY


def risk_of(kind: str) -> str:
    """The risk a gate's kind of act is asked about as: a costly kind or one of OWN as itself, else an ordinary
    step."""
    return kind if kind in COSTLY | OWN else "act"


def reaches(answered: str, step: str) -> bool:
    """How far one yes reaches in the rest of its turn: a step of the risk that was answered, and every ordinary step;
    never a costly step or a widening, which are asked each time. The one place that boundary is drawn."""
    return step not in ALONE and step in (answered, "act")


def tier(risk: str) -> str:
    """How a step's question shows in the chat: "card" for a very important one (ALONE), else "plain"."""
    return "card" if risk in ALONE else "plain"


# What counts as a plain yes, by language: the whole message, split at punctuation, must be made of these (a
# softening particle may follow each part, and a part may be several of them with spaces between). Any other word,
# a no or a question is not one.
YES = {
    "zh": "确定,确认,好,好的,行,可以,同意,是,是的,对,嗯,嗯嗯,做,你做,去做,执行,继续,开始,没问题,当然,允许,照做,发送,"
          "动手,请做,请执行,确定执行,就这样,那就做",
    "zh-TW": "確定,確認,好,好的,行,可以,同意,是,是的,對,嗯,做,你做,去做,執行,繼續,開始,沒問題,當然,允許,照做,發送,動手",
    "en": "yes,y,yeah,yep,yup,sure,ok,okay,k,go,go ahead,do it,proceed,confirm,confirmed,continue,sounds good,"
          "please do,please,fine,alright,all right,absolutely,of course,approved,approve,sure thing,go for it,"
          "let's go,lets go",
    "ja": "はい,うん,ええ,いいよ,いいです,お願い,お願いします,進めて,やって,どうぞ,オーケー,了解,了解です,承知しました,"
          "確定,実行,実行して,続けて,大丈夫",
    "ko": "네,예,응,그래,좋아,좋아요,확인,진행,진행해,진행해요,진행해 주세요,해줘,해 줘,해주세요,해 주세요,알겠어,"
          "알겠습니다,오케이,계속,승인",
    "de": "ja,jawohl,klar,okay,ok,mach,mach das,mach es,mach weiter,weiter,los,bestätigen,bestätigt,einverstanden,"
          "gerne,passt,in ordnung,sicher,genau,ja bitte",
    "es": "sí,si,vale,claro,ok,adelante,hazlo,confirmo,confirmar,de acuerdo,dale,perfecto,sigue,continúa,por favor,venga",
    "fr": "oui,ouais,d'accord,ok,vas-y,allez-y,fais-le,faites-le,confirme,confirmer,je confirme,bien sûr,parfait,"
          "continue,c'est bon,oui merci,volontiers",
    "pt-BR": "sim,ok,pode,pode fazer,pode ir,claro,confirmo,confirmar,vai,manda,beleza,certo,tá bom,ta bom,continua,"
             "prossiga,faz,faça,com certeza,por favor",
    "ru": "да,ага,ок,окей,хорошо,ладно,давай,делай,подтверждаю,конечно,продолжай,вперёд,вперед,можно,согласен,"
          "согласна,угу",
}
_YES = {unicodedata.normalize("NFKC", phrase).casefold().replace("’", "'")
        for words in YES.values() for phrase in words.split(",")}
# Particles that soften a yes without changing it (好的吧, 确定呀, はいよ, ok~).
_SOFT = re.compile(r"(?<=\S)([吧呀啊哦嘛啦的了喔哈~]+|よ|ね)$")
# Longest message that is read as a yes at all.
YES_MOST = 40


def said_yes(text: str) -> bool:
    """Whether the person's message is a plain yes: every part of it, split at punctuation, is one of YES."""
    said = unicodedata.normalize("NFKC", str(text or "")).casefold().replace("’", "'").strip()
    # A question ("ok?", "确定吗？") asks back rather than answers.
    if not said or len(said) > YES_MOST or "?" in said:
        return False

    def one(part: str) -> bool:
        if part in _YES or _SOFT.sub("", part) in _YES:
            return True
        words = part.split()
        return len(words) > 1 and all(w in _YES or _SOFT.sub("", w) in _YES for w in words)
    parts = [p.strip() for p in re.split(r"[,.!;:，。！；：、…\n]+", said) if p.strip()]
    return bool(parts) and all(one(p) for p in parts)


# What each turn asked and what a yes said, by (conversation, the turn's token), until the turn's record takes it
# (`exchange`).
_TOLD: dict[tuple, list[dict]] = {}


def exchange(conversation: str, token: str) -> list[dict]:
    """The questions a turn asked in order, each {"question", "answer": the person's words for a yes, else None},
    taken once (dm.py writes them into the chat's history)."""
    return _TOLD.pop((conversation, token), [])


class Asking:
    """The questions waiting in the chat in one app, by id (the place's answer for each), and the risks a yes was
    given to in each turn."""

    def __init__(self) -> None:
        self.open: dict[str, dict] = {}
        self.said: dict[tuple, set[str]] = {}

    def put(self, workspace, ident: str, conversation: str, turn: tuple, risk: str, card: dict, settle,
            lang: str) -> None:
        """Question `ident` said in the chat: the character's message of the reply under way, in the app's words for
        `card`, kept for the turn's record, and waiting for `settle`."""
        from .asked import question
        asked = question(card, risk, lang)
        text = asked.pop("text")
        workspace.question_said(conversation, {"role": "assistant", "text": text,
                                               "ask": {"id": ident, **asked, "state": "waiting"}})
        told = {"question": text, "answer": None}
        _TOLD.setdefault(turn, []).append(told)
        while len(_TOLD) > 16:
            _TOLD.pop(next(iter(_TOLD)))
        self.open[ident] = {"turn": turn, "risk": risk, "settle": settle, "workspace": workspace, "told": told,
                            **{k: asked[k] for k in ("tier", "act", "decline") if k in asked}}

    def close(self, ident: str, state: str = "unanswered") -> None:
        """Question `ident` no longer waits: one nobody answered is marked `state` ("unanswered", or "left" for a
        browser act a later message may still answer)."""
        waiting = self.open.pop(ident, None)
        if waiting is not None:
            waiting["workspace"].answer_said(ident, state)

    def carried(self, turn: tuple, risk: str) -> bool:
        # A record with no turn token (written before the turn's first step) carries nothing.
        return bool(turn[1]) and any(reaches(answered, risk) for answered in self.said.get(turn, ()))

    def yes_given(self, turn: tuple, risk: str) -> None:
        if risk in ALONE:
            return
        self.said.setdefault(turn, set()).add(risk)
        while len(self.said) > 16:
            self.said.pop(next(iter(self.said)))

    async def answer(self, ident: str, text: str | None = None, choice: str | None = None) -> dict:
        """The person's answer to question `ident`: what they typed under it, or for a card the button they pressed
        (`choice` "yes" or "no"), which no plain question takes. {"ok", "yes", "seq": the number of their message
        in the chat}; ok false when it is no longer waiting. Their words for a press are the button's own."""
        waiting = self.open.get(ident)
        if waiting is None or (choice is not None and waiting["tier"] != "card"):
            return {"ok": False, "yes": False}
        # Taken before the place settles it (an upload's settle waits on the Open dialog): one answer a question.
        del self.open[ident]
        yes = said_yes(text) if choice is None else choice == "yes"
        line = text if choice is None else waiting["act" if yes else "decline"]
        # What the place took it as: an upload whose Open dialog is cancelled hands nothing over.
        yes = await waiting["settle"](yes)
        if yes is None:
            # It stopped waiting meanwhile.
            waiting["workspace"].answer_said(ident, "unanswered")
            return {"ok": False, "yes": False}
        if yes:
            self.yes_given(waiting["turn"], waiting["risk"])
        # A typed no is their next message of its own, which the history holds as such.
        if yes or choice is not None:
            waiting["told"]["answer"] = line
        seq = waiting["workspace"].answer_said(ident, "yes" if yes else "no", line,
                                               pending=choice is None and not yes)
        return {"ok": True, "yes": yes, "seq": seq}


_ASKING: dict[str, Asking] = {}


def asking(workspace) -> Asking:
    """The one Asking of the app whose home is the workspace's."""
    return _ASKING.setdefault(str(Path(workspace.home).resolve()), Asking())


def doing(workspace) -> dict:
    """The app's record of the chat turn under way (loop.ChatLookups): {"conversation", "turn", ...}, or {}."""
    try:
        return json.loads((Path(workspace.home) / "runtime" / "desktop" / "chat-doing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def turn_of(workspace) -> tuple:
    """The turn under way as the yeses of the turn are kept: (conversation, the turn's own token)."""
    now = doing(workspace)
    return str(now.get("conversation") or ""), str(now.get("turn") or "")


class Card:
    """The one question a place has waiting in the chat at a time, said as the character's message (`Asking.put`);
    `card` is the gate's own reading of the step, which the place's route gives; the person's typed yes on the app's
    own page answers it."""

    def __init__(self, workspace, window=lambda: None) -> None:
        # `window`: the app window when there is one (app.state.window), for the notification.
        self.workspace, self.window = workspace, window
        self.card: dict | None = None
        self.answer: asyncio.Future | None = None
        # How the last step asked went ahead: "said" (their yes typed under it) or "carried" (a yes earlier in the turn).
        self.how = ""

    def turn_on(self, conversation: str) -> bool:
        """The person's own chat turn in the app is under way, for this conversation."""
        if not conversation or not self.workspace._chat_lock.locked():
            return False
        return doing(self.workspace).get("conversation") == conversation

    async def ask(self, card: dict, conversation: str, what: dict, ended=None, *, yes=True, no=False,
                  risk: str = "act", typed: bool = True):
        """Says `card` in the chat and waits: `yes` on the person's typed yes (or at once when a yes earlier in the
        turn reaches this risk; never for a costly one), `no` on any other message, None when the turn ended,
        `ended()` says the task did, or WAIT_S passed. `what` names it for the notification, {"zh", "en"}. With
        `typed` false it is something they fill in rather than confirm (an MCP server's form), answered by `press`
        alone and not said as a message."""
        everyone, turn = asking(self.workspace), turn_of(self.workspace)
        if typed and everyone.carried(turn, risk):
            self.how = "carried"
            return yes
        loop = asyncio.get_running_loop()
        ident = secrets.token_urlsafe(10)
        self.card, self.answer = {**card, "id": ident, "risk": risk, "typed": typed}, loop.create_future()

        async def settle(said: bool) -> bool | None:
            if not self.up(ident):
                return None
            self.answer.set_result(yes if said else no)
            return said
        if typed:
            everyone.put(self.workspace, ident, conversation, turn, risk, card, settle,
                         i18n.lang(self.workspace.config()))
        self._tell(loop, what)
        try:
            began = loop.time()
            while loop.time() - began < WAIT_S and self.turn_on(conversation) and not (ended and ended()):
                done, _ = await asyncio.wait({self.answer}, timeout=TICK_S)
                if done:
                    self.how = "said"
                    return self.answer.result()
            return None
        finally:
            everyone.close(ident)
            self.card = self.answer = None

    def up(self, ident: str) -> bool:
        """The question `ident` is up and not yet answered."""
        return self.card is not None and self.card["id"] == ident and not self.answer.done()

    def press(self, ident: str, answer) -> bool:
        """An answer from the page's own controls, for what is filled in rather than confirmed (an MCP server's form)."""
        if not self.up(ident):
            return False
        self.answer.set_result(answer)
        return True

    def drop(self) -> None:
        """The task ended: a question still waiting goes unanswered."""
        if self.answer is not None and not self.answer.done():
            self.answer.set_result(None)

    def _tell(self, loop, what: dict) -> None:
        """The system notification, when the app window is not in front (window.notify decides), off the loop."""
        window = self.window()
        if window is None:
            return
        lang = "zh" if str(self.workspace.config().get("AGENT_LANG") or "zh").lower().startswith("zh") else "en"
        loop.run_in_executor(None, window.notify, NOTICE[lang].format(what=what[lang]))


def mount(app, workspace, body) -> None:
    from .panels.runtime import WINDOW_HEADER

    @app.post("/api/confirm")
    async def confirm(request: Request):
        """The person's answer to a step waiting on their yes: from the app's own page on this computer alone, never
        from the service. {"id", "text"}: what they typed in the chat box; or {"id", "choice": "yes" | "no"}: a
        card's button. -> {"ok", "yes", "seq"}: their message joins the chat as number `seq`. A message that is not
        a plain yes is a no for that step, and the page then sends it on with `answering` = seq, to be answered as
        the ordinary message it is (workspace.chat)."""
        window = getattr(app.state, "window", None)
        if window is not None and not window.is_own_page(request.headers.get(WINDOW_HEADER, "")):
            return JSONResponse({"error": "local_only"}, status_code=403)
        payload = await body(request)
        ident, text, choice = payload.get("id"), payload.get("text"), payload.get("choice")
        if not isinstance(ident, str) or (choice not in ("yes", "no") if "choice" in payload
                                          else not isinstance(text, str)):
            return JSONResponse({"error": "generic"}, status_code=400)
        # Held to the length of any message, as a no is then sent on to the model (workspace.chat).
        if isinstance(text, str) and len(text) > 8000:
            return JSONResponse({"error": "invalid_message"}, status_code=400)
        return await asking(workspace).answer(ident, text if choice is None else None, choice)
