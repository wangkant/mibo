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
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from ..cardwait import Card
from ..crossing import downloaded
from . import checkpoint, files, office, words
from . import read as reading
from . import run as running
from .grants import NEVER, Grants, known_folders, norm, under

# A turn's name as the character's side makes it (shell/tool.py), which names its folder of checkpoints.
TURN = re.compile(r"[\w-]{1,64}")

LOG_OUT = 1500
# Items looked at in the granted folders when finding a file the model named badly.
FIND_MOST = 20000
# Seconds the reading /api/shell/read made stays good for the /api/shell/do that follows it.
READ_KEPT_S = 5.0
# How a step that asked went ahead on the person's yes typed under it (without one: "auto_edit", "rule", "review",
# "carried" for a yes earlier in the turn, "").
PRESSED = ("said",)
# In a turn's declined steps: a no the person gave to a step in another program this turn.
ELSEWHERE = ("elsewhere",)
# The reasons a command asks that the reviewer may pass in automatic review.
REVIEWED = ("program", "outside", "move_out")


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
READ_MODE ={"zh": "当前为只读模式，未进行任何更改", "en": "Read only: nothing was changed"}


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
            writable = self.grants.roots(write=True)
            paths = [p for a in reasons for p in a.paths] + verdict.overwrites
            if all(any(under(norm(p), r) for r in writable) for p in paths):
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
        context = {"cwd": cwd, "read": read_, "verdict": verdict,
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
            refused_said = {lang: words.refused_said(read_, verdict, lang) for lang in ("zh", "en")}
            self.log(command, cwd, read_, verdict, "refused", said=refused_said)
            return {"status": "refused", "said": refused_said,
                    "why": {lang: words.refused(verdict, lang) for lang in ("zh", "en")},
                    "reasons": [a.why for a in verdict.reasons][:6]}, context
        if mode == "read" and any(a.kind != "read" or a.write for a in read_.acts):
            # Read only: it reads files in the granted folders and nothing else, with no question to ask.
            self.log(command, cwd, read_, verdict, "read_mode", said=asked_said)
            return {"status": "read_mode", "shown": READ_MODE}, context
        if self.grants.root_of(norm(cwd)):
            self.last = cwd
        # The step as a no holds it: a write or an edit by what it would write too.
        step = ("step", command, cwd, hashlib.sha256(job["bytes"]).hexdigest()[:16] if job and "bytes" in job else "")
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
        if verdict.action == "ask" and not context["how"]:
            # Said in the chat in the app's own reading of the step, asked as its risk (`_risk`, cardwait.reaches).
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
            if passed is not None:
                # Why the reviewer did not pass it, in one line (chat.js draws it under the title).
                for lang in ("zh", "en"):
                    asked[lang]["review"] = passed.line(lang)
            # A command that names a file in a skill's folder says which skill it comes from (skills/store.py).
            from ..skills.store import FROM_SKILL, skill_in
            skill = await asyncio.to_thread(skill_in, command, self.home)
            if skill:
                asked["skill"] = skill
                for lang in ("zh", "en"):
                    asked[lang]["lines"].insert(0, FROM_SKILL[lang].format(name=skill))
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
        return None, context

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
                done = await asyncio.to_thread(running.run, command, context["cwd"], limit_s=limit_s, stop=stop,
                                               progress=self.running)
            finally:
                watcher.cancel()
                self.running = None
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

    def _place(self, raw: str, base: str, find: bool = False) -> str:
        """A path the model gave, absolute: relative ones from the working folder, ~ and %VARS% opened. With
        `find`, one that is not there is looked for in the granted folders by its name (_found)."""
        text = os.path.expandvars(os.path.expanduser(str(raw or "").strip().strip('"')))
        place = os.path.normpath(os.path.join(base, text)) if text else base
        return (self._found(text) or place) if find and text and not os.path.exists(place) else place

    def _found(self, raw: str) -> str:
        """The one item in the granted folders named as a badly built path ends ("t27 里 预算.xlsx" finds
        t27/预算.xlsx), as coding agents point a missing path to the file that is there; "" for none or several.
        Folder names written before the name pick among several. Nothing outside the granted folders is looked at."""
        words = [w.lower() for w in re.split(r"[\\/\s]+", raw) if w]
        hits: dict[str, str] = {}
        seen = 0
        for root in self.grants.folders():
            stack = [root]
            while stack and seen < FIND_MOST:
                try:
                    entries = list(os.scandir(stack.pop()))
                except OSError:
                    continue
                for entry in entries:
                    seen += 1
                    if entry.name.lower() == words[-1]:
                        hits[norm(entry.path)] = entry.path
                    if entry.is_dir(follow_symlinks=False) and not entry.is_symlink() and not running._junction(entry.path):
                        stack.append(entry.path)
        found = list(hits.values())
        if len(found) > 1:
            found = [p for p in found if os.path.basename(os.path.dirname(p)).lower() in words[:-1]]
        return found[0] if len(found) == 1 else ""

    async def file(self, op: str, args: dict, conversation: str, folder: str, turn: str,
                   said_no: bool = False, from_outside: bool = False) -> dict:
        """One file tool: made ready and checked here, judged by its paths (files.acts: the same folder question,
        question and refusal as a command doing it), then done in Python (files.py)."""
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
                job = await asyncio.to_thread(self._prepare, op, args, base)
            except ValueError as e:
                return {"status": "error", "message": str(e)}
            if job.get("answer"):
                return {"status": "done", "out": job["answer"], "said": {}, "cwd": base}
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
                out = await asyncio.to_thread(self._perform, job)
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

    def _prepare(self, op: str, args: dict, base: str) -> dict:
        """What a file tool will do, with absolute paths, checked before the gate: the error a model can fix
        comes back at once, with no question."""
        def place(key: str, find: bool = True) -> str:
            return self._place(args.get(key) or "", base, find)

        if op in ("read", "list", "search", "open"):
            raw = str(args.get("path") or "")
            path = raw.strip() if op == "open" and re.match(r"^https?://", raw.strip(), re.IGNORECASE) else place("path")
            if op == "read" and not os.path.exists(path) and self.grants.root_of(norm(path)):
                raise ValueError(f"There is no {path}. List the folder with list_files to find its exact name.")
            job = {"op": op, "path": path, "folder": path if op in ("list", "search") else os.path.dirname(path)}
            if op == "search":
                job["text"] = str(args.get("text") or "")
                if not job["text"]:
                    raise ValueError("Give the text to look for.")
            if op in ("list", "search"):
                job.update(pattern=str(args.get("pattern") or ""), recursive=bool(args.get("recursive")),
                           sort=str(args.get("sort") or "name"))
            if op == "read":
                job.update(offset=int(args.get("offset") or 1), limit=int(args.get("limit") or files.READ_LINES))
            if op == "open" and not job["path"].lower().startswith("http") and not os.path.exists(path):
                raise ValueError(f"There is no {path}. List the folder with list_files to find its exact name.")
            return job
        if op in ("write", "edit"):
            path = place("path", op == "edit")
            name, ext = os.path.basename(path), os.path.splitext(path)[1].lower()
            if os.path.isdir(path):
                raise ValueError(f"{path} is a folder.")
            if ext in office.OLD:
                raise ValueError(f"{ext} is the {office.NAMES[office.OLD[ext]]} format from before 2007, which is not "
                                 f"written here. Write {os.path.splitext(name)[0]}{office.OLD[ext]} instead: it opens "
                                 "in the same program.")
            if ext == ".pdf" and op == "write":
                raise ValueError("write_file does not make PDFs. Make the document as a .docx instead; Word saves it "
                                 "as a PDF (另存为 PDF) when they need one.")
            if ext in office.KINDS:
                job, before_lines, after_lines = self._document(op, path, ext, args)
            else:
                if op == "write":
                    text = str(args.get("content") if args.get("content") is not None else "")
                    before, encoding, data = files.read_for_change(path) if os.path.isfile(path) else ("", "utf-8", None)
                    after = text.replace("\r\n", "\n").replace("\n", "\r\n") if "\r\n" in before else text
                else:
                    before, encoding, data = files.read_for_change(path)
                    after = files.replaced(before, str(args.get("old_string") or ""),
                                           str(args.get("new_string") or ""), bool(args.get("replace_all")))
                    if after == before:
                        raise ValueError("old_string and new_string are the same: nothing would change.")
                job = {"op": "write", "kind": op, "path": path, "folder": os.path.dirname(path),
                       "bytes": files.encode(after, encoding), "before": data}
                before_lines, after_lines = before.splitlines(), after.splitlines()
            if job["before"] is not None:
                job["card"] = {lang: {"title": (f"修改「{name}」的内容" if lang == "zh" else f"Change the text of “{name}”")
                                      if op == "edit" else (f"用新内容替换「{name}」" if lang == "zh"
                                                            else f"Replace “{name}” with new text"),
                                      "lines": []} for lang in ("zh", "en")}
                job["card"]["diff"] = files.diff(before_lines, after_lines, name)
                job["said"] = {"zh": f"修改「{name}」", "en": f"Changed “{name}”"}
            elif ext in office.KINDS:
                job["said"] = {"zh": f"生成「{name}」", "en": f"Made “{name}”"}
            return job
        if op == "move":
            moves, copy = [], bool(args.get("copy"))
            for item in args.get("moves") or []:
                if not isinstance(item, dict) or not item.get("from") or not item.get("to"):
                    raise ValueError("Each move needs from and to.")
                src, raw_to = self._place(item["from"], base, True), str(item["to"])
                if not os.path.exists(src):
                    raise ValueError(f"There is no {src}. List the folder with list_files to find its exact name.")
                dest = self._place(raw_to, base)
                into = raw_to.endswith(("\\", "/")) or os.path.isdir(dest)
                target = os.path.join(dest, os.path.basename(src.rstrip("\\/"))) if into else dest
                if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(src):
                    raise ValueError(f"{target} is already there; nothing is replaced this way. Choose another name, or "
                                     "delete that one first with delete_files.")
                # Two moves landing on one name: the second would replace the first (shutil.move copies over a file).
                if any(os.path.normcase(m["to"]) == os.path.normcase(target) for m in moves):
                    raise ValueError(f"Two of the moves land on {target}, so one would replace the other; nothing was "
                                     "moved. To move them into a folder, end `to` with \\.")
                moves.append({"from": src, "to": target, "folder": dest if into and not os.path.isdir(dest) else (
                    "" if os.path.isdir(os.path.dirname(target)) else os.path.dirname(target))})
            if not moves:
                raise ValueError("Give at least one move.")
            return {"op": "move", "moves": moves, "copy": copy, "folder": os.path.dirname(moves[0]["from"]),
                    "said": {lang: words.move_said(moves, copy, lang) for lang in ("zh", "en")}}
        if op == "delete":
            paths = [self._place(p, base, True) for p in args.get("paths") or [] if str(p).strip()]
            missing = [p for p in paths if not os.path.exists(p)]
            if not paths or missing:
                raise ValueError(f"There is no {missing[0]}." if missing else "Give the paths to delete.")
            what = ({lang: words.quote(os.path.basename(paths[0].rstrip("\\/")), lang) for lang in ("zh", "en")}
                    if len(paths) == 1 else {"zh": f" {len(paths)} 项", "en": f"{len(paths)} items"})
            return {"op": "delete", "paths": paths, "folder": os.path.dirname(paths[0]),
                    "said": {lang: words.file_doing("delete", {"paths": paths}, lang, done=True) for lang in ("zh", "en")},
                    # The question says where they go; the gate's own lines below it say what is in them.
                    "card": {"zh": {"title": f"将{what['zh']}移到回收站", "lines": []},
                             "en": {"title": f"Move {what['en']} to the Recycle Bin", "lines": []}}}
        raise ValueError(f"No file tool {op}.")

    @staticmethod
    def _document(op: str, path: str, ext: str, args: dict) -> tuple[dict, list[str], list[str]]:
        """write_file or edit_file on a Word, Excel or PowerPoint file (office/): the document made from the model's
        Markdown, or the one there changed by exact replacement inside it; with the two documents' text, from which
        the question's difference is taken."""
        name = os.path.basename(path)
        data = files.document_for_change(path) if op == "edit" or os.path.isfile(path) else None
        if op == "write":
            text = str(args.get("content") or "")
            if not text.strip():
                raise ValueError(f"content is empty: give what {name} holds, written as Markdown.")
            made = office.make(ext, text)
        else:
            old, new = str(args.get("old_string") or ""), str(args.get("new_string") or "")
            if old == new:
                raise ValueError("old_string and new_string are the same: nothing would change.")
            made = office.replaced(ext, data, old, new, bool(args.get("replace_all")), name)
        job = {"op": "write", "kind": op, "path": path, "folder": os.path.dirname(path), "bytes": made,
               "before": data, "document": office.summary(ext, made)}
        # A file there that is not a readable document is replaced whole; its question shows all of the new text.
        before = (files.document_lines(path, data) if data is not None else None) or []
        return job, before, files.document_lines(path, made) or []

    def _perform(self, job: dict) -> str:
        """Does a judged file tool's work; what came of it, for the model."""
        op = job["op"]
        if op == "read":
            return files.read(job["path"], job["offset"], job["limit"])
        if op == "list":
            return files.listing(job["path"], self.grants.places, job["pattern"], job["recursive"], job["sort"])
        if op == "search":
            return files.search(job["path"], job["text"], self.grants.places, job["pattern"])
        if op == "open":
            if os.environ.get("SHELL_OPEN_DRY"):
                # The measuring script (tools/computer_tasks.py) checks what would open without a window.
                return f"Opened {job['path']} (not shown: SHELL_OPEN_DRY is set)."
            if re.match(r"^https?://", job["path"], re.IGNORECASE):
                # A page for them to see: in the app's own browser; their default browser only when the app
                # window is not open.
                from ..browsed import _ask
                if _ask(self.home, "POST", "/api/browser/op", 20, json={"op": "show", "url": job["path"]}).get(
                        "status") == "ok":
                    return f"Opened {job['path']} in the app's browser, in front of them."
                os.startfile(job["path"])
                return f"Opened {job['path']} in their default browser: the app's own browser is not open."
            os.startfile(job["path"])
            return f"Opened {job['path']} with its default program."
        if op == "write":
            os.makedirs(os.path.dirname(job["path"]), exist_ok=True)
            try:
                with open(job["path"], "wb") as f:
                    f.write(job["bytes"])
            except PermissionError as e:
                # Word, Excel and PowerPoint hold the file they have open.
                raise OSError(e.errno, "the file is open in another program or is read-only; ask them to close it "
                                       "there, then write it again", job["path"]) from e
            done = f"{'Changed' if job['before'] is not None else 'Made'} {job['path']} ({files.size(len(job['bytes']))})"
            if job.get("document"):
                return (f"{done}: {job['document']}. The file is finished and saved; no program has to be opened to "
                        "make it. open with show true shows it to them if they want to see it.")
            return done + "."
        if op == "move":
            files.move(job["moves"], job["copy"])
            verb = "Copied" if job["copy"] else "Moved"
            return "\n".join(f"{verb} {m['from']} -> {m['to']}" for m in job["moves"])
        if op == "delete":
            if not files.recycle(job["paths"]):
                raise OSError(0, "Windows did not move them to the Recycle Bin", job["paths"][0])
            return "Moved to the Recycle Bin: " + ", ".join(job["paths"])
        raise ValueError(op)

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
        }


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
        if not isinstance(command, str) or not command.strip() or not isinstance(conversation, str) or                 not isinstance(turn, str) or not TURN.fullmatch(turn):
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
        if not isinstance(op, str) or not isinstance(args, dict) or not isinstance(conversation, str) or                 not isinstance(turn, str) or not TURN.fullmatch(turn):
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
        if not isinstance(turn, str) or not TURN.fullmatch(turn) or not shell().checkpoints.has(turn) or                 not isinstance(n, int) or isinstance(n, bool):
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
        """The step waiting in the chat for the person's yes, if any (chat.js draws it; /api/confirm answers it)."""
        return {"card": shell().cards.card}
