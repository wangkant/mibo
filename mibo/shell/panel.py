"""The app page's side of commands: where they are judged, asked about and run, and Settings' section.

The character's turn runs in the service, which sends the command here
(/api/shell/do) and waits. Here it is read and judged (read.py) against the
grants (grants.py); a step that needs the person's yes is said in the chat in
the app's own words (cardwait.py) and waits for their typed yes, which only
the app's own page can pass on (/api/confirm, the window's key), never the
service and never the model's words. A question is asked only while the
person's own chat turn is under way in the app; nothing runs for a turn
nobody started, on a timer or in the background. The turn stopped in the chat
ends a waiting question and the running command's whole process tree.

The person's mode for commands (acting.py) is read at every step: read only
runs nothing that changes or starts anything; automatic review lets changes to
files inside folders that may be changed go without a question, as the turn's
checkpoint can put them back, and puts a program run, a step outside the
granted folders or a request that only fetches to the reviewer (review.py)
before any question; the log row carries the reviewer's decision and reason.
One yes reaches the rest of the turn for steps of its kind of risk and every
ordinary step (cardwait.reaches): a delete after a yes to a program run is
asked again. A folder outside the grants is asked for in the chat too, granted
to read when the step only reads and to change when it changes.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from ..cardwait import Card
from ..crossing import downloaded
from . import checkpoint, confine, filejob, files, guards, netguard, words
from . import read as reading
from . import run as running
from .acts import RUNS_WHEN_STARTED
from .acts import tier as tier_of
from .grants import NEVER, Grants, known_folders, norm, under

# A turn's name as the character's side makes it (shell/tool.py), which names its folder of checkpoints.
TURN = re.compile(r"[\w-]{1,64}")

LOG_OUT = 1500
# Seconds the reading /api/shell/read made stays good for the /api/shell/do that follows it.
READ_KEPT_S = 5.0
# How a step that asked went ahead on the person's yes typed under it (without one: "auto_edit", "rule", "review",
# "carried" for a yes earlier in the turn, "").
PRESSED = ("said",)
# In a turn's declined steps: a no the person gave to a step in another program this turn.
ELSEWHERE = ("elsewhere",)
# The reasons a command asks that the reviewer may pass in automatic review.
REVIEWED = ("program", "outside", "move_out")
# The reasons that only read or change what the turn's undo gives back (a read outside the open places, a move out
# of a folder): when the review does not pass such a step it is not done, never asked. A delete the review doubts
# is still asked, though the Recycle Bin keeps it.
UNDONE = ("outside", "move_out")


def _reviewed(act) -> bool:
    """A program run, a step outside the granted folders, a delete to the Recycle Bin, or a web address opened for the
    person to see."""
    return act.kind in REVIEWED or (act.kind, act.what) in (("network", "browse"), ("delete", "delete"))


def _fetch(act) -> bool:
    """A request that only fetches: no body, no upload, no form or sign-in, no address computed as it runs. Claude
    Code's auto mode lets read-only HTTP requests through and Codex's reviewer judges network requests; here the
    reviewer judges it on the person's words. Sending, uploading and what cannot be told ask each time."""
    return (act.kind, act.what) == ("network", "net") and not act.sends and act.host not in ("", "?")


# The step log's line for a step the read-only mode held.
READ_MODE = {"zh": "当前为只读模式，未进行任何更改", "en": "Read only: nothing was changed"}


def _error(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


class Shell:
    """One command at a time: the grants, the question waiting for the person, the command running."""

    def __init__(self, app, workspace):
        self.app, self.workspace = app, workspace
        self.home = Path(workspace.home)
        self.desktop = self.home / "runtime" / "desktop"
        self.grants = Grants(self.desktop, self.home)
        self.cards = Card(workspace, lambda: getattr(app.state, "window", None))
        self.busy = asyncio.Lock()
        # The folder the last step worked in, where the next one starts when it names none.
        self.last = ""
        # Each turn's changes to files, which the person can take back (checkpoint.py); the command running now.
        self.checkpoints = checkpoint.Checkpoints(self.home)
        self.running: dict | None = None
        # (command, folder, when, reading) of the last /api/shell/read, which the /api/shell/do after it takes.
        self.kept_read: tuple | None = None
        # What they said no to, per turn: the same step (a write or an edit with the same text) or folder asked for
        # again in that turn is refused with no second question; every other step of the turn goes on, and none
        # passes without a question but by what the person allowed themselves.
        self.said_no: dict[str, set[tuple]] = {}
        # The files each turn's steps wrote, so a script among them that a later step runs is read as code (`_code`).
        self.wrote: dict[str, set[str]] = {}

    def turn_on(self, conversation: str) -> bool:
        return self.cards.turn_on(conversation)

    async def ask(self, card: dict, conversation: str, risk: str = "act") -> bool | None:
        """Says `card` in the chat and waits: True on the person's typed yes (or a yes earlier in the turn that
        reaches `risk`), False on any other message, None when nobody answered or the turn ended."""
        return await self.cards.ask(card, conversation, {lang: card[lang]["title"] for lang in ("zh", "en")}, risk=risk)

    def mode(self) -> str:
        """The person's one acting mode (acting.py): off, read or auto (automatic review)."""
        from ..acting import Modes
        return Modes(self.desktop).mode()

    def _scope(self, read_: reading.Reading, verdict: reading.Verdict, cwd: str) -> dict | None:
        """What may pass this step without a question: {"key": "edit"} for changes to files inside folders that
        may be changed, which auto-edit lets through when each can be put back; or one program run in the granted
        folder it runs in, with arguments that stay inside it ({"key", "program", "shown", "root"}), which an
        always-allow rule kept from before may cover. None for anything else (a delete, the network, an install, a
        place outside, what cannot be told)."""
        runs = [a for a in read_.acts if a.args is not None and a.paths]
        exes = {norm(a.paths[0]) for a in runs}
        reasons = [a for a in verdict.reasons if not (a.kind == "outside" and a.paths and norm(a.paths[0]) in exes)]
        if not reasons:
            return None
        if all(a.kind == "overwrite" for a in reasons):
            paths = [p for a in reasons for p in a.paths] + verdict.overwrites
            if all(self.grants.open(norm(p), True) for p in paths):
                return {"key": "edit", "paths": paths}
            return None
        root = self.grants.root_of(norm(cwd))
        if not root or len(exes) != 1 or len(runs) != len([a for a in read_.acts if a.kind == "program"]) or \
                any(a.kind != "program" or a.args is None for a in reasons):
            return None
        for arg in (x for a in runs for x in a.args):
            if "://" in arg or "%" in arg or re.match(r"^[\w.-]+@[\w.-]+:", arg):
                return None
            drive = re.search(r"[A-Za-z]:[\\/]", arg)
            place = arg[drive.start():] if drive else arg.split("=", 1)[-1] if arg.startswith("-") else arg
            if (drive or re.search(r"[\\/]", place) or place.startswith(("..", "~"))) and \
                    not under(norm(os.path.join(cwd, os.path.expanduser(place))), root):
                return None
        exe = exes.pop()
        return {"key": f"program:{exe}@{root}", "program": exe, "shown": words.program_name(runs[0]), "root": root}

    @staticmethod
    def _risk(verdict: reading.Verdict, command: str, job: dict | None, from_outside: bool) -> str:
        """The risk a step that asks is asked as (cardwait.py): "delete" for an overwrite of a file the turn's
        checkpoint cannot keep, "system" for an install, a send over the network, a step the app cannot read, or a
        command whose program or switches delete, overwrite or send (review.costly_command): all costly, asked every
        time. Else a command that came verbatim from material the turn read (crossing.py), asked for that once;
        "recycle" for a delete the Recycle Bin gives back, "delete" for one it cannot hold; "act" for the rest."""
        from ..cardwait import CROSS
        from ..review import costly_command
        overwrites = [p for a in verdict.reasons if a.kind == "overwrite" for p in a.paths] + verdict.overwrites
        if any(os.path.isfile(p) and os.path.getsize(p) > checkpoint.KEEP_MAX for p in overwrites):
            return "delete"
        removed = verdict.deletes
        if removed and (any(d.get("more") for d in removed) or not files.bin_keeps(
                [d["path"] for d in removed], sum(d.get("bytes") or 0 for d in removed))):
            return "delete"
        if any(a.kind == "install" or (a.kind == "unknown" and a.what not in ("unresolved", "from_outside"))
               or (a.kind == "network" and a.sends and a.what != "browse") for a in verdict.reasons) or (
                not job and costly_command(command)):
            return "system"
        if from_outside:
            return CROSS + "command"
        if verdict.deletes or any(a.kind == "delete" for a in verdict.reasons):
            return "recycle"
        return "act"

    def _passed(self, scope: dict | None, mode: str) -> str:
        """How a question is skipped: "auto_edit" (the mode, for changes each turn's checkpoint can put back),
        "rule" (an always-allow the person gave this program in this folder); "" when it is asked."""
        if scope is None:
            return ""
        if scope["key"] == "edit" and mode == "auto" and all(
                not os.path.isfile(p) or os.path.getsize(p) <= checkpoint.KEEP_MAX for p in scope["paths"]):
            return "auto_edit"
        return "rule" if scope.get("program") and self.grants.allowed(scope["program"], scope["root"]) else ""

    def cwd_for(self, folder: str) -> tuple[str, str]:
        """(folder to run in, a folder to ask for first): the named folder, else the first granted one, else the
        person's own folder (where a command that names no place runs; anything there is outside and asks)."""
        roots = self.grants.folders()
        if folder:
            named = next((row["path"] for row in known_folders()
                          if folder.strip().lower() in (row["key"], row["zh"], row["en"].lower())), "")
            place = os.path.realpath(named or os.path.expandvars(os.path.expanduser(folder.strip())))
            if self.grants.root_of(norm(place)):
                return place, ""
            if os.path.isdir(place) and not self.grants.places.grantable(norm(place)):
                return place, place
            return "", ""
        if self.last and self.grants.root_of(norm(self.last)) and os.path.isdir(self.last):
            return self.last, ""
        return (roots[0] if roots else os.environ.get("USERPROFILE") or str(Path.home())), ""

    def log(self, command: str, cwd: str, read_: reading.Reading | None, verdict: reading.Verdict | None,
            outcome: str, done: dict | None = None, said: dict | None = None, how: str = "",
            review: dict | None = None) -> None:
        self.grants.log({
            "command": command, "cwd": cwd, "outcome": outcome, **({"how": how} if how else {}),
            **({"review": review} if review else {}),
            "kinds": sorted({a.kind for a in read_.acts}) if read_ else [],
            "action": verdict.action if verdict else "", "said": said or {},
            "why": [a.why for a in verdict.reasons][:6] if verdict else [],
            **({"code": done["code"], "out": done["out"][:LOG_OUT], "seconds": done["seconds"],
                "timed_out": done["timed_out"], "stopped": done["stopped"]} if done else {})})

    def ready(self, conversation: str) -> dict | None:
        """Why nothing may run now, as the outcome, or None."""
        if self.mode() == "off":
            return {"status": "off"}
        if running.elevated():
            return {"status": "elevated"}
        if not self.turn_on(conversation):
            return {"status": "unwatched"}
        return None

    def folder_card(self, folder: str, write: bool, turn_on: bool) -> dict:
        """The question granting `folder`, to read only when the step only reads and to change when it must change
        something there; with `turn_on`, the same yes turns commands and files on. No folder: it only turns them
        on."""
        return {"type": "folder" if folder else "turn_on", "folder": folder, "turn_on": turn_on, "write": write,
                **{lang: words.folder_card(folder, lang, write, turn_on) for lang in ("zh", "en")}}

    async def enable(self, folder: str, conversation: str) -> dict:
        """turn_on for commands and files (turnon.py): one question turns them on and grants the folder their
        message names to read, as WorkBuddy and Cowork ask for the working folder at the start."""
        if not self.turn_on(conversation):
            return {"status": "unanswered"}
        place = self.cwd_for(folder)[1] if folder else ""
        off = self.mode() == "off"
        if not off and not place:
            return {"status": "on", "folder": "", "read_only": False}
        answer = await self.ask(self.folder_card(place, False, off), conversation)
        if not answer:
            return {"status": "declined" if answer is False else "unanswered"}
        if off:
            from ..acting import Modes
            Modes(self.desktop).set("auto")
            self.grants.log({"granted": place, "outcome": "turned_on"})
        if place and not self.grants.add(place, read_only=True):
            self.last = place
        return {"status": "on", "folder": place, "read_only": bool(place)}

    def take_read(self, command: str, cwd: str) -> reading.Reading | None:
        """The reading /api/shell/read made of this command in this folder a moment ago, taken once."""
        kept, self.kept_read = self.kept_read, None
        if kept and kept[:2] == (command, cwd) and time.monotonic() - kept[2] < READ_KEPT_S:
            return kept[3]
        return None

    async def judged(self, command: str, conversation: str, folder: str, card: dict | None = None,
                     job: dict | None = None, turn: str = "", from_outside: bool = False) -> tuple:
        """Reads and judges `command` in `folder`, asks for a folder and for the yes a step needs: (outcome,
        context), the outcome None when it may run now. A file tool's `job` is judged by its own acts (files.acts),
        `command` being its call; `card` gives its own title and lines. `from_outside`: the service found the
        command's text, or a script it runs, in material the turn read (crossing.py); it is asked even when it
        would run."""
        cwd, ask_first = self.cwd_for(folder)
        if not cwd:
            return {"status": "bad_folder"}, {}
        mode = self.mode()

        def read_now() -> reading.Reading:
            return reading.Reading(command, cwd, files.acts(job, cwd), []) if job else reading.read(command, cwd)

        no = self.said_no.setdefault(turn, set())
        while len(self.said_no) > 16:
            self.said_no.pop(next(iter(self.said_no)))
        asked_for: set[str] = set()
        for _ in range(4):
            read_, write = None, False
            if ask_first:
                folder_to_grant = ask_first
            else:
                read_ = (None if job else self.take_read(command, cwd)) or await asyncio.to_thread(read_now)
                verdict = await asyncio.to_thread(reading.judge, read_, self.grants)
                if verdict.action != "folder":
                    break
                folder_to_grant, write = verdict.folder, verdict.write
                if write and mode == "read":
                    return {"status": "read_mode", "shown": READ_MODE}, {}
            inside = [f for f in self.grants.folders()
                      if under(norm(f), norm(folder_to_grant)) and norm(f) != norm(folder_to_grant)]
            if inside:
                # A badly built path in the folder above one they granted: never a question for it, the model
                # is told which folder to use.
                self.log(command, cwd, read_, None, "use_granted")
                return {"status": "use_granted", "folder": folder_to_grant, "folders": inside}, {}
            if norm(folder_to_grant) in asked_for:
                # Granted read only a moment ago, and this step changes something there.
                return {"status": "read_only", "folder": folder_to_grant}, {}
            if ("folder", norm(folder_to_grant)) in no:
                return {"status": "folder_declined", "folder": folder_to_grant, "again": True}, {}
            answer = await self.ask(self.folder_card(folder_to_grant, write, False), conversation)
            if not answer:
                if answer is False:
                    no.add(("folder", norm(folder_to_grant)))
                self.log(command, cwd, read_, None, "folder_declined" if answer is False else "folder_unanswered")
                return {"status": "folder_declined" if answer is False else "unanswered", "folder": folder_to_grant}, {}
            why = self.grants.add(folder_to_grant, read_only=not write)
            if why:
                return {"status": "bad_folder", "why": why}, {}
            self.grants.log({"granted": folder_to_grant, "outcome": "granted"})
            asked_for.add(norm(folder_to_grant))
            ask_first = ""
        else:
            return {"status": "bad_folder"}, {}
        # The limits Windows holds it to as it runs (confine.py), from this same reading.
        context = {"cwd": cwd, "read": read_, "verdict": verdict, "tier": tier_of(read_.acts),
                   "online": guards.online(read_.acts),
                   "said": {lang: words.summary(read_, lang, "ed") for lang in ("zh", "en")}}
        # What it would have done, for a command that was not run.
        asked_said = {lang: (card or {}).get(lang, {}).get("title") or words.summary(read_, lang, "card")
                      for lang in ("zh", "en")}
        if verdict.action == "invalid":
            self.log(command, cwd, read_, verdict, "invalid")
            return {"status": "invalid", "errors": read_.errors[:5]}, context
        if verdict.action == "bin":
            self.log(command, cwd, read_, verdict, "use_bin")
            return {"status": "use_bin"}, context
        if verdict.action == "refuse":
            return self._refused(command, cwd, read_, verdict), context
        if mode == "read" and any(a.kind != "read" or a.write for a in read_.acts):
            # Read only: it reads files in the granted folders and nothing else, with no question to ask.
            self.log(command, cwd, read_, verdict, "read_mode", said=asked_said)
            return {"status": "read_mode", "shown": READ_MODE}, context
        if self.grants.root_of(norm(cwd)):
            self.last = cwd
        # The step as a no holds it: a write or an edit by what it would write too.
        step = ("step", command, cwd, hashlib.sha256(job["bytes"]).hexdigest()[:16] if job and "bytes" in job else "")
        code = [] if verdict.action not in ("run", "ask") else await asyncio.to_thread(
            self._code, read_, verdict, cwd, turn)
        if code:
            read_ = reading.Reading(read_.command, read_.cwd, read_.acts + code, read_.errors)
            context.update(read=read_, tier=tier_of(read_.acts), online=guards.online(read_.acts))
            never = [a for a in code if a.kind == "hidden"]
            verdict = reading.Verdict("refuse" if never else "ask", never or verdict.reasons + code,
                                      deletes=verdict.deletes, overwrites=verdict.overwrites, root=verdict.root)
            if never:
                return self._refused(command, cwd, read_, verdict), context
        if from_outside and verdict.action == "run":
            # A command or script taken from a page, a message or a file is asked even when it only reads.
            verdict = reading.Verdict("ask", [reading.Act("unknown", "from_outside",
                                                          "its text comes from material read this turn, not from them")])
        if verdict.action == "ask" and step in no:
            # Before any reviewer or mode passes it: what they declined does not run later in the turn.
            return {"status": "declined", "again": True, "said": asked_said,
                    "asked": {lang: [asked_said[lang]] for lang in ("zh", "en")}}, context
        risk = self._risk(verdict, command, job, from_outside) if verdict.action == "ask" else "act"
        mild = risk in ("act", "recycle")
        scope = self._scope(read_, verdict, cwd) if verdict.action == "ask" and mild else None
        context["how"] = self._passed(scope, mode)
        if no and context["how"] == "auto_edit":
            # After a no in this turn, only what the person allowed themselves (an always-allow rule) skips a question.
            context["how"] = ""
        passed = None
        if verdict.action == "ask" and mild and not context["how"] and mode == "auto" and not no and all(
                _reviewed(a) or _fetch(a) for a in verdict.reasons):
            # A program run, a step outside the granted folders, a delete to the Recycle Bin, a page opened for them
            # or a request that only fetches: the reviewer first, on the person's own words of this turn. A costly
            # step (cardwait.COSTLY) and a command from material the turn read are asked each time.
            from .. import acting, review
            from ..crossing import turn_read
            passed = await review.decide("commands", await asyncio.to_thread(acting.asked, self.workspace), {
                "kind": "command", "where": cwd, "text": command, "effects": [a.why for a in verdict.reasons][:6],
                "only_reads": all(a.kind == "read" and not a.write for a in read_.acts), "undo": True},
                ask=acting.reviewer(self.workspace), attended=True, lang=self.workspace.config().get("AGENT_LANG", "zh"),
                read=turn_read(self.workspace))
            # The reviewer's decision and reason go with the log row, so a question that came can be read from it.
            context["review"] = {"decision": passed.decision, "by": passed.by, "reason": passed.reason}
            if passed.decision == "go":
                context["how"] = "review"
            elif passed.decision == "refuse":
                self.log(command, cwd, read_, verdict, "refused", said=asked_said, how="review",
                         review=context["review"])
                return {"status": "refused", "said": asked_said, "why": {"zh": passed.reason, "en": passed.reason},
                        "reasons": [passed.reason], "declined": passed.declined()}, context
            elif all(a.kind in UNDONE for a in verdict.reasons):
                # It reads, or changes only what undo gives back: not a step asked of the person (cardwait.py). The
                # review did not pass it (or gave no answer), so it is not done and the turn goes on another way.
                self.log(command, cwd, read_, verdict, "not_passed", said=asked_said, how="review",
                         review=context["review"])
                return {"status": "not_passed", "said": asked_said, "reason": passed.reason}, context
        if verdict.action == "ask" and not context["how"] and not job:
            # The reviewer's floor on a command's text (review.CMD_BLOCKED's credentials) holds for one asked with no
            # review too: a program the reader cannot follow (robocopy, tar) naming a secret's place is refused.
            from ..review import CMD_BLOCKED
            secret = dict(CMD_BLOCKED)["credentials"].search(command)
            if secret:
                return self._refused(command, cwd, read_, reading.Verdict(
                    "refuse", [reading.Act("secrets", "secrets", f"it names {secret.group()}")])), context
        if verdict.action == "ask" and not context["how"]:
            # Said in the chat in the app's own reading of the step, asked as its risk (`_risk`, cardwait.reaches).
            asked = await self._question(command, cwd, read_, verdict, card, asked_said, passed)
            lines = {lang: asked[lang]["lines"] for lang in ("zh", "en")}
            yes = await self.ask(asked, conversation, risk)
            if not yes:
                if yes is False:
                    no.add(step)
                status = "declined" if yes is False else "unanswered"
                self.log(command, cwd, read_, verdict, status, said=asked_said, review=context.get("review"))
                return {"status": status, "said": asked_said, "asked": lines}, context
            # What was said in the chat must still be what runs.
            again = await asyncio.to_thread(lambda: reading.judge(read_now(), self.grants))
            if again.action != context["verdict"].action or (
                    sorted(d["path"] for d in again.deletes) != sorted(d["path"] for d in verdict.deletes)
                    or [d["files"] for d in again.deletes] != [d["files"] for d in verdict.deletes]
                    or sorted(again.overwrites) != sorted(verdict.overwrites)):
                self.log(command, cwd, read_, again, "changed", said=asked_said)
                return {"status": "changed", "said": asked_said}, context
            context["how"] = self.cards.how
        if turn:
            self.wrote.setdefault(turn, set()).update(
                norm(p) for a in read_.acts for p in ([a.dest] if a.dest else []) + (a.paths if a.write else []))
            while len(self.wrote) > 16:
                self.wrote.pop(next(iter(self.wrote)))
        return None, context

    def _refused(self, command: str, cwd: str, read_: reading.Reading, verdict: reading.Verdict) -> dict:
        """A step refused, logged, with what it would have done and why, in the person's words."""
        said = {lang: words.refused_said(read_, verdict, lang) for lang in ("zh", "en")}
        self.log(command, cwd, read_, verdict, "refused", said=said)
        return {"status": "refused", "said": said, "why": {lang: words.refused(verdict, lang) for lang in ("zh", "en")},
                "reasons": [a.why for a in verdict.reasons][:6]}

    def _code(self, read_: reading.Reading, verdict: reading.Verdict, cwd: str, turn: str) -> list:
        """Code given as text, past what the reader sees (acts.CODE): a script this turn wrote, run now, with what its
        text shows (psprograms.code_acts); and that, code on the command line, or a file that runs later
        (acts.RUNS_WHEN_STARTED) after the turn read outside material (crossing.py), asked every time."""
        from ..crossing import OUTSIDE, turn_read
        from .psprograms import code_acts
        # What this command writes itself counts, its code being in the command's own text.
        now = {norm(p) for a in read_.acts for p in ([a.dest] if a.dest else []) + (a.paths if a.write else [])}
        wrote = self.wrote.get(turn, set()) | now
        code = []
        for act in read_.acts:
            if act.kind != "program" or act.what != "script":
                continue
            for name in act.paths or [w.strip("'\"") for w in act.name.split(" ")[1:] if not w.startswith("-")][:1]:
                path = norm(os.path.join(cwd, name))
                if path not in wrote:
                    continue
                text = read_.command
                if path not in now and os.path.isfile(path):
                    with open(path, encoding="utf-8", errors="replace") as f:
                        text = f.read(1 << 18)
                code += [reading.Act("program", "written", f"runs {name}, a script written in this task",
                                     name=name, paths=[path]), *code_acts(text)]
        if (code or any(a.what in ("inline", *RUNS_WHEN_STARTED) for a in read_.acts + verdict.reasons)) and turn_read(
                self.workspace).get(OUTSIDE):
            code.append(reading.Act("unknown", "read_outside", "it comes after the task read outside material"))
        return code

    async def _question(self, command: str, cwd: str, read_: reading.Reading, verdict: reading.Verdict,
                        card: dict | None, asked_said: dict, passed) -> dict:
        """The question said in the chat for a step: the app's own lines for it, a file tool's own lines and
        difference, why the reviewer did not pass it, and the skill a command's file comes from."""
        asked = {"type": "command", "command": words.visible(command), "cwd": words.visible(cwd),
                 "where": {lang: words.folder_name(cwd, lang) for lang in ("zh", "en")},
                 **{lang: {"title": asked_said[lang],
                           # A file tool's difference says what an overwrite line would, only better.
                           "lines": [words.visible(line) for line in (card or {}).get(lang, {}).get("lines", [])
                                     + [line for line in words.card_lines(read_, verdict, lang)
                                        if not (card and line.startswith(("覆盖现有文件", "Replace ")))]]}
                    for lang in ("zh", "en")}}
        if (card or {}).get("diff"):
            # An edit's whole difference, with its indentation (activity.js draws it).
            asked["diff"] = card["diff"]
        # How many items it deletes, or files it replaces: what a costly step's sentence and button name (asked.py).
        replaced = verdict.overwrites + [p for a in verdict.reasons if a.kind == "overwrite" for p in a.paths]
        if verdict.deletes or replaced:
            asked.update(count=len(verdict.deletes) or len(set(replaced)),
                         removes="delete" if verdict.deletes else "replace")
        if passed is not None:
            # Why the reviewer did not pass it, in one line (under the question's fold, asked.py).
            for lang in ("zh", "en"):
                asked[lang]["review"] = passed.line(lang)
        # A command that names a file in a skill's folder says which skill it comes from (skills/store.py).
        from ..skills.store import FROM_SKILL, skill_in
        skill = await asyncio.to_thread(skill_in, command, self.home)
        if skill:
            asked["skill"] = skill
            for lang in ("zh", "en"):
                asked[lang]["lines"].insert(0, FROM_SKILL[lang].format(name=skill))
        return asked

    async def do(self, command: str, conversation: str, folder: str, limit_s: float, turn: str,
                 said_no: bool = False, from_outside: bool = False) -> dict:
        not_now = self.ready(conversation)
        if not_now:
            return not_now
        if said_no:
            self.said_no.setdefault(turn, set()).add(ELSEWHERE)
        async with self.busy:
            outcome, context = await self.judged(command, conversation, folder, turn=turn, from_outside=from_outside)
            if outcome:
                return outcome
            # The files its reading names are kept first; what Remove-Item moved to the bin is listed as it runs.
            kept = self.checkpoints.turn(turn)
            paths, moves = checkpoint.targets(context["read"])
            await asyncio.to_thread(kept.before, paths + context["verdict"].overwrites)
            stop = threading.Event()
            watcher = asyncio.create_task(self._watch(conversation, stop))
            self.running = {"started": time.monotonic(), "last": ""}
            try:
                done = await asyncio.to_thread(running.run, command, context["cwd"], tier=context["tier"],
                                               online=context["online"], home=self.home, limit_s=limit_s, stop=stop,
                                               progress=self.running)
            except confine.Unconfined as e:
                # Never run without Windows' limits.
                self.log(command, context["cwd"], context["read"], context["verdict"], "unconfined", said=context["said"])
                return {"status": "error", "message": f"Windows' limits for this command could not be set up "
                                                      f"({e.strerror or e}), so it was not run."}
            finally:
                watcher.cancel()
                self.running = None
            # When Windows' limits stopped it: which one and why, in one line for the model.
            done["limit"] = guards.refused_line(done["err"], context["tier"], context["online"], self.home)
            changes = await asyncio.to_thread(self._kept, kept, moves, done["recycled"])
            self.log(command, context["cwd"], context["read"], context["verdict"], "ran", done, said=context["said"],
                     how=context["how"], review=context.get("review"))
            return {"status": "done", "said": context["said"], "asked": context["how"] in PRESSED, "how": context["how"],
                    "cwd": context["cwd"], "changes": changes, **done}

    def _kept(self, kept: checkpoint.Turn, moves: list, recycled: list) -> int:
        """The turn's list of changes brought up to date after a step; how many it gained."""
        changes = kept.after(moves, recycled)
        if changes:
            self.checkpoints.prune()
        return changes

    async def file(self, op: str, args: dict, conversation: str, folder: str, turn: str,
                   said_no: bool = False, from_outside: bool = False) -> dict:
        """One file tool: made ready and checked (filejob.prepare), judged by its paths (files.acts: the same folder
        question, question and refusal as a command doing it), then done in Python (filejob.perform)."""
        not_now = self.ready(conversation)
        if not_now:
            return not_now
        if said_no:
            self.said_no.setdefault(turn, set()).add(ELSEWHERE)
        async with self.busy:
            base, ask_first = self.cwd_for(folder)
            if ask_first or (not base and folder and os.path.isdir(folder)):
                # A folder not granted, often the parent of a granted one when the model split a path: the paths
                # are joined to it and judged on their own (asking for a folder only when they lie outside).
                base, folder = ask_first or os.path.realpath(folder), ""
            if not base:
                return {"status": "bad_folder"}
            try:
                job = await asyncio.to_thread(filejob.prepare, op, args, base, self.grants)
            except ValueError as e:
                return {"status": "error", "message": str(e)}
            if job["op"] == "open" and downloaded(job["path"]):
                # A program or script that came from the web is never opened by the character.
                said = {lang: words.REFUSED["downloaded"][0 if lang == "zh" else 1] for lang in ("zh", "en")}
                self.grants.log({"command": f"open {job['path']}", "outcome": "refused", "why": ["downloaded"]})
                return {"status": "refused", "said": said, "why": said, "reasons": ["it came from the web"]}
            command = files.call(job)
            outcome, context = await self.judged(command, conversation, folder, card=job.get("card"), job=job,
                                                 turn=turn, from_outside=from_outside)
            if outcome:
                return outcome
            kept = self.checkpoints.turn(turn)
            moves = [(m["from"], m["to"]) for m in job["moves"]] if job["op"] == "move" and not job["copy"] else []
            await asyncio.to_thread(kept.before, [job["path"]] if job["op"] == "write" else
                                    [m["to"] for m in job["moves"]] if job["op"] == "move" else [])
            try:
                out = await asyncio.to_thread(filejob.perform, job, self.grants, self.home)
            except OSError as e:
                out = f"Failed: {e.strerror or e} ({getattr(e, 'filename', '') or ''})"
                self.log(command, context["cwd"], context["read"], context["verdict"], "failed",
                         {"code": 1, "out": out, "seconds": 0, "timed_out": False, "stopped": False})
                return {"status": "error", "message": out,
                        "changes": await asyncio.to_thread(self._kept, kept, moves, [])}
            changes = await asyncio.to_thread(self._kept, kept, moves, job["paths"] if job["op"] == "delete" else [])
            self.log(command, context["cwd"], context["read"], context["verdict"], "ran",
                     {"code": 0, "out": out, "seconds": 0, "timed_out": False, "stopped": False},
                     said=job.get("said") or context["said"], how=context["how"], review=context.get("review"))
            return {"status": "done", "out": out, "said": job.get("said") or context["said"],
                    "asked": context["how"] in PRESSED, "how": context["how"], "cwd": context["cwd"], "changes": changes}

    async def _watch(self, conversation: str, stop: threading.Event) -> None:
        """The turn ended in the chat (stopped, or the page went away): the command's tree is ended."""
        while True:
            await asyncio.sleep(0.5)
            if not self.turn_on(conversation):
                stop.set()
                return

    def view(self) -> dict:
        folders = self.grants.folders()
        granted, read_only = {norm(p) for p in folders}, self.grants.read_only()
        return {
            "on": self.mode() != "off", "elevated": running.elevated(), "mode": self.mode(),
            "folders": [{"path": p, "zh": words.folder_name(p, "zh"), "en": words.folder_name(p, "en"),
                         "read_only": norm(p) in read_only} for p in folders],
            "rules": [{"program": r["program"], "shown": r["shown"], "folder": r["folder"],
                       "zh": words.folder_name(r["folder"], "zh"), "en": words.folder_name(r["folder"], "en")}
                      for r in self.grants.rules()],
            "known": [{**row, "granted": norm(row["path"]) in granted} for row in known_folders()],
            "never": [{"zh": zh, "en": en} for zh, en in NEVER],
            "limits": self.limits(),
        }

    def limits(self) -> dict | None:
        """Settings' Windows limits: the guards placed on other places, by why, and the optional hardening."""
        if sys.platform != "win32":
            return None
        kept = guards.keeper(self.home).view()
        places = [row for row in kept["places"] if row["why"] != "app"]
        return {"guards": kept["on"], "places": places, "failed": [row["path"] for row in places if row["failed"]],
                "hardening": netguard.state(self.desktop)}


def mount(app, workspace, body) -> None:
    from ..panels.runtime import WINDOW_HEADER

    def shell() -> Shell:
        if getattr(app.state, "shell", None) is None:
            app.state.shell = Shell(app, workspace)
        return app.state.shell

    # The PowerShells kept for reading and for running commands end with the app.
    app.state.closers += [running.SPARE.close, reading.PARSER.close]

    @app.get("/api/shell")
    async def shell_view():
        return await asyncio.to_thread(shell().view)

    @app.post("/api/shell")
    async def shell_change(request: Request):
        """Settings: the switch, the mode (read only, automatic review), a folder granted (a read-only one made
        sortable, or one set to read only) or taken back, an always-allow rule taken back. Only on the computer the
        app runs on."""
        from ..acting import Modes
        payload = await body(request)
        grants = shell().grants
        if isinstance(payload.get("on"), bool):
            # The switch is the one acting mode: on is automatic review, off stops every acting place.
            await asyncio.to_thread(Modes(shell().desktop).set, "auto" if payload["on"] else "off")
        elif payload.get("mode") in ("read", "auto") and shell().mode() != "off":
            await asyncio.to_thread(Modes(shell().desktop).set, payload["mode"])
        elif isinstance(payload.get("forget"), dict):
            rule = payload["forget"]
            await asyncio.to_thread(grants.forget, str(rule.get("program") or ""), str(rule.get("folder") or ""))
        elif isinstance(payload.get("add"), str) and payload["add"].strip():
            # "read_only": true grants it, or sets one granted already, the person's own folders too, to read only.
            why = await asyncio.to_thread(grants.add, os.path.expandvars(payload["add"].strip().strip('"')),
                                          payload.get("read_only") is True)
            if why:
                return _error(f"folder_{why}")
            await asyncio.to_thread(grants.log, {"granted": payload["add"].strip(), "outcome": "granted_in_settings"})
        elif isinstance(payload.get("remove"), str):
            await asyncio.to_thread(grants.remove, payload["remove"])
        elif isinstance(payload.get("guards"), bool) and sys.platform == "win32":
            # Off takes every guard of other places out, each list as it was; on places them again.
            keeper = guards.keeper(shell().home)
            await asyncio.to_thread(keeper.turn_on if payload["guards"] else keeper.remove)
        elif isinstance(payload.get("hardening"), bool) and sys.platform == "win32":
            # The system's elevation prompt for the one-time setup; cancelled there, nothing changes.
            failed = await asyncio.to_thread(netguard.elevate, payload["hardening"], shell().desktop)
            if failed:
                return _error(f"hardening_{failed}")
        else:
            return _error("generic")
        return await asyncio.to_thread(shell().view)

    @app.post("/api/shell/pick")
    async def shell_pick():
        """Settings' 选择文件夹: the system's folder dialog over the app window (pywebview's FileDialog.FOLDER), and the
        folder picked granted. What the person picks there is their choice; cancelled, nothing changes."""
        window = getattr(app.state, "window", None)
        if window is None:
            return _error("no_window")
        picked = await asyncio.to_thread(window.pick_folder)
        if picked:
            why = await asyncio.to_thread(shell().grants.add, picked)
            if why:
                return _error(f"folder_{why}")
            await asyncio.to_thread(shell().grants.log, {"granted": picked, "outcome": "granted_in_settings"})
        return await asyncio.to_thread(shell().view)

    @app.get("/api/shell/log")
    async def shell_log(n: int = 40):
        return {"rows": await asyncio.to_thread(shell().grants.log_rows, max(1, min(n, 200)))}

    @app.post("/api/shell/log")
    async def shell_log_clear(request: Request):
        if (await body(request)).get("clear") is not True:
            return _error("generic")
        await asyncio.to_thread(shell().grants.clear_log)
        return {"rows": []}

    @app.post("/api/shell/read")
    async def shell_read(request: Request):
        """The plain words for a command before it is judged: the step log's line while it runs. The reading is kept
        for the /api/shell/do that follows, and a PowerShell is made ready to run it meanwhile."""
        payload = await body(request)
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            return _error("generic")
        if shell().mode() != "off":
            await asyncio.to_thread(running.SPARE.warm)
        cwd = shell().cwd_for(str(payload.get("folder") or ""))[0] or os.environ.get("USERPROFILE", "")
        read_ = await asyncio.to_thread(reading.read, command, cwd)
        shell().kept_read = (command, cwd, time.monotonic(), read_)
        return {lang: {"ing": words.summary(read_, lang, "ing"), "ed": words.summary(read_, lang, "ed")}
                for lang in ("zh", "en")}

    @app.post("/api/shell/enable")
    async def shell_enable(request: Request):
        """turn_on for commands and files from the character's turn (turnon.py): the one question that turns them
        on and grants the folder named. Waits for the person's yes."""
        payload = await body(request)
        conversation = payload.get("conversation")
        if not isinstance(conversation, str):
            return _error("generic")
        return await shell().enable(str(payload.get("folder") or "").strip(), conversation)

    @app.post("/api/shell/do")
    async def shell_do(request: Request):
        """One command from the character's turn: judged, asked about, run, refused. Waits for the person's yes."""
        payload = await body(request)
        command, conversation, turn = payload.get("command"), payload.get("conversation"), payload.get("turn")
        if not isinstance(command, str) or not command.strip() or not isinstance(conversation, str) or \
                not isinstance(turn, str) or not TURN.fullmatch(turn):
            return _error("generic")
        limit = payload.get("limit")
        limit_s = float(limit) if isinstance(limit, (int, float)) and not isinstance(limit, bool) else running.TIME_LIMIT_S
        return await shell().do(command.strip(), conversation, str(payload.get("folder") or ""),
                                max(5.0, min(limit_s, running.TIME_MAX_S)), turn, payload.get("said_no") is True,
                                payload.get("from_outside") is True)

    @app.post("/api/shell/file")
    async def shell_file(request: Request):
        """One file tool from the character's turn (read, list, search, write, edit, open, move, delete), through
        the same gate as a command. Waits for the person's yes."""
        payload = await body(request)
        op, args, conversation, turn = payload.get("op"), payload.get("args"), payload.get("conversation"), payload.get("turn")
        if not isinstance(op, str) or not isinstance(args, dict) or not isinstance(conversation, str) or \
                not isinstance(turn, str) or not TURN.fullmatch(turn):
            return _error("generic")
        return await shell().file(op, args, conversation, str(payload.get("folder") or ""), turn,
                                  payload.get("said_no") is True, payload.get("from_outside") is True)

    @app.get("/api/shell/changes")
    async def shell_changes(turn: str = ""):
        """A turn's changes to files, for the fold 本次改动 under its reply (activity.js)."""
        if not TURN.fullmatch(turn) or not shell().checkpoints.has(turn):
            return _error("generic", 404)
        return await asyncio.to_thread(lambda: shell().checkpoints.turn(turn).view())

    def own_page(request: Request) -> bool:
        window = getattr(app.state, "window", None)
        return window is None or window.is_own_page(request.headers.get(WINDOW_HEADER, ""))

    @app.post("/api/shell/undo")
    async def shell_undo(request: Request):
        """撤销这次的改动: the person's press on the app's own page puts the turn's files back, never the service's.
        Not while a command or a file tool is at work."""
        if not own_page(request):
            return _error("local_only", 403)
        turn = (await body(request)).get("turn")
        if not isinstance(turn, str) or not TURN.fullmatch(turn) or not shell().checkpoints.has(turn):
            return _error("generic")
        kept = shell().checkpoints.turn(turn)
        if kept.state["undone"] or kept.state.get("expired"):
            return _error("generic")
        async with shell().busy:
            done = await asyncio.to_thread(kept.undo)
        await asyncio.to_thread(shell().grants.log, {"outcome": "undone", "turn": turn, **done})
        return {**done, **(await asyncio.to_thread(kept.view))}

    @app.post("/api/shell/reveal")
    async def shell_reveal(request: Request):
        """A changed file shown in its folder in File Explorer, from the fold; the person's own click."""
        if not own_page(request):
            return _error("local_only", 403)
        payload = await body(request)
        turn, n = payload.get("turn"), payload.get("n")
        if not isinstance(turn, str) or not TURN.fullmatch(turn) or not shell().checkpoints.has(turn) or \
                not isinstance(n, int) or isinstance(n, bool):
            return _error("generic")
        items = shell().checkpoints.turn(turn).state["items"]
        if not 0 <= n < len(items) or items[n]["op"] == "deleted":
            return _error("generic")
        place = items[n].get("dest") or items[n]["path"]
        if not os.path.lexists(place):
            return _error("gone", 404)
        if not os.environ.get("SHELL_OPEN_DRY"):
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(place)])
        return {"ok": True}

    @app.get("/api/shell/running")
    async def shell_running():
        """The command running now: seconds so far and the last line it printed, for the waiting row."""
        now = shell().running
        if not now:
            return {}
        return {"seconds": round(time.monotonic() - now["started"]), "last": words.visible(now.get("last", "")[:120])}

    @app.get("/api/shell/card")
    async def shell_card():
        """The gate's reading of the step waiting for the person's yes, if any (said in the chat as the character's message (cardwait.py); /api/confirm answers it)."""
        return {"card": shell().cards.card}
