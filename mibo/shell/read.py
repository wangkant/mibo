"""Reading a command before it runs, and judging what it would do.

PowerShell's own parser reads it (parse.ps1, in a PowerShell kept for the
purpose): the syntax tree, every command at any depth (pipeline stages, sub-
expressions, script blocks, function bodies), its parameters bound the way
PowerShell binds them (`StaticParameterBinder`: names, abbreviations,
positions), aliases resolved through PowerShell's own command table, file
redirections, method calls, type names and assignments. pssort.py sorts every
command into acts (acts.py), its paths made absolute with variables, `~`, `..`,
links and junctions followed. `judge` then holds the acts against the person's
grants and the never list. Anything the tables (pstables.py) do not know is
"unknown": it is never run without the person's press.
"""
from __future__ import annotations

import base64
import fnmatch
import functools
import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..crossing import downloaded
from . import run as running
from .acts import ASK_KINDS, COMMAND_MAX, NEVER_KINDS, Act, Reading, download_run, never
from .grants import PROJECT_FILES, RUNS_LATER, Grants, known_folders, norm, under
from .paths import LIST_MOST, _base, _matches, _walk, _wild
from .psnodes import _items
from .pssort import Sorter
from .pstables import CONTENT_READS

READ_TIMEOUT_S = 20
# What Places.blocked says is never touched; its "system" is asked every time instead.
NEVER_PLACES = ("app", "secrets")
# Acts that take only names, sizes and dates: free in the program places Start reads (grants.FINDABLE).
NAMES_ONLY = ("look", "list", "info")
# A parser just started loads PowerShell and compiles parse.ps1 before its first answer; on a busy computer
# that alone has taken more than READ_TIMEOUT_S.
START_TIMEOUT_S = 90

# ---------------------------------------------------------------- the parser process


class Parser:
    """A Windows PowerShell kept to read commands (parse.ps1), started on first use and again if it dies."""

    def __init__(self):
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None

    def _start(self) -> subprocess.Popen:
        script = (Path(__file__).with_name("parse.ps1")).read_text(encoding="utf-8")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return subprocess.Popen(
            [running.POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=os.environ.get("TEMP") or None, env=running.environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, command: str, cwd: str) -> dict | None:
        """The parse of `command` as parse.ps1 answers it, or None when the parser gave no answer in time."""
        request = json.dumps({"b64": base64.b64encode(command.encode("utf-8")).decode("ascii"), "cwd": cwd}) + "\n"
        with self.lock:
            for _ in range(2):
                started = self.process is None or self.process.poll() is not None
                if started:
                    self.process = self._start()
                parsed = _answer(self.process, request.encode("utf-8"), START_TIMEOUT_S if started else READ_TIMEOUT_S)
                if parsed is not None:
                    return parsed
                self.process.kill()
                self.process = None
        return None

    def close(self) -> None:
        with self.lock:
            if self.process is not None:
                self.process.kill()
                self.process = None


def _answer(process: subprocess.Popen, request: bytes, within: float):
    """parse.ps1's answer to one request, or None when it gives none in `within` seconds or one that is not JSON.
    The exchange runs on a thread of its own, so a parser that hangs is left behind."""
    answer: list[bytes] = []

    def ask() -> None:
        process.stdin.write(request)
        process.stdin.flush()
        answer.append(process.stdout.readline())

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    worker.join(within)
    if not answer or not answer[0].strip():
        return None
    try:
        return json.loads(answer[0].decode("utf-8"))
    except ValueError:
        return None


PARSER = Parser()


def read(command: str, cwd: str) -> Reading:
    """Reads and sorts one command to be run in `cwd`. A command that does not parse comes back with errors."""
    if len(command) > COMMAND_MAX:
        return Reading(command, cwd, [], [f"the command is longer than {COMMAND_MAX} characters"])
    parsed = PARSER.read(command, cwd)
    if parsed is None or parsed.get("fatal"):
        return Reading(command, cwd, [Act("unknown", "unknown", "the app could not read this command")], [])
    errors = [str(e) for e in _items(parsed.get("errors"))]
    sorter = Sorter(parsed, cwd)
    if not errors:
        sorter.sort()
    acts = sorter.acts
    acts += download_run(acts)
    return Reading(command, cwd, acts, errors)


# ---------------------------------------------------------------- judging against the grants

@dataclass
class Verdict:
    """What to do with a command: "run", "ask", "folder" (grant a folder first), "refuse", "invalid" or "bin" (a
    delete past the Recycle Bin, to be written another way)."""
    action: str
    reasons: list[Act]
    folder: str = ""
    deletes: list[dict] = field(default_factory=list)
    overwrites: list[str] = field(default_factory=list)
    root: str = ""
    # For "folder": the folder must be one that may be changed, not only read.
    write: bool = False


@functools.lru_cache(maxsize=1)
def _known() -> tuple:
    return tuple(known_folders())


def folder_for(path: str) -> str:
    """The folder to ask for so that `path` is inside: a known folder holding it, else the nearest folder."""
    real = norm(path)
    for row in _known():
        if under(real, norm(row["path"])):
            return row["path"]
    place = path
    while place and not os.path.isdir(place):
        parent = os.path.dirname(place)
        if parent == place:
            return ""
        place = parent
    return place


def _folder_to_grant(grants: Grants, path: str) -> str:
    """A read-only granted folder is asked for again, to change in; else the folder that would hold `path`."""
    held = grants.root_of(norm(path))
    return grants.folder_of(held) if held else folder_for(path)


def _escaping_links(folder: str, inside, most: int = 20000) -> list[str]:
    """Links and junctions under `folder` that lead where `inside` (a `norm`ed place) does not hold (a recursive walk
    would follow)."""
    found, seen, stack = [], 0, [folder]
    while stack and seen < most:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            seen += 1
            link = entry.is_symlink() or (entry.is_dir(follow_symlinks=False) and running._junction(entry.path))
            if link and not inside(norm(entry.path)):
                found.append(entry.path)
            elif not link and entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
    return found


def _pattern_reaches(pattern: str, root: str, deep: bool) -> bool:
    """A wildcard path matches `root` or something inside it (or, with `deep`, a folder above it)."""
    p = [c for c in re.split(r"[\\/]", os.path.normcase(pattern)) if c]
    r = [c for c in re.split(r"[\\/]", root) if c]
    n = min(len(p), len(r))
    if not all(fnmatch.fnmatch(r[i], p[i]) for i in range(n)):
        return False
    return len(p) >= len(r) or deep


def _reaches_protected(act: Act, places) -> str:
    """For a wildcard, or a recursive read of contents: a protected place it reaches ("" none, "?" too many files to
    tell). Named places are checked one by one in judge."""
    # Zipping and copying read whole files too; zipping a folder always takes everything in it.
    content = act.what in (*CONTENT_READS, "zip", "copy") or act.write
    deep = content and (act.recurse or act.what == "zip")
    for glob in act.globs:
        if _wild(glob):
            reached = _pattern_protected(glob, act.write, deep, content, places)
        elif deep:
            reached = next((root for root in (places.home, places.package, places.python, places.appdata)
                            if under(root, norm(glob))), "")
        else:
            reached = ""
        if not reached and deep and os.path.isdir(_base(glob)[0]):
            reached = _inside_protected(_base(glob)[0], act.write, places)
        if reached:
            return reached
    return ""


def _pattern_protected(glob: str, write: bool, deep: bool, content: bool, places) -> str:
    """A protected place a wildcard path could match, or one it matches now; ""."""
    literal = _base(glob)[0]
    for root in (places.home, places.package, places.python, places.appdata,
                 os.path.join(places.windows, "system32", "config")):
        # Start's program places and the temporary folder, where they are inside AppData, are not AppData's own.
        if root == places.appdata and any(under(norm(literal), p) and under(p, root)
                                          for p in [*places.findable, places.temp] if p):
            continue
        if _pattern_reaches(glob, root, deep):
            return root
    p = [c for c in re.split(r"[\\/]", os.path.normcase(glob)) if c]
    r = [c for c in re.split(r"[\\/]", places.profile) if c]
    # A dot folder in the profile (.ssh, .aws), named by a pattern that could match one.
    if len(p) > len(r) and _pattern_reaches(glob, places.profile, False) and (
            fnmatch.fnmatch(".x", p[len(r)]) or p[len(r)].startswith(".")) and (len(p) > len(r) + 1 or content):
        return places.profile + "\\."
    return next((place for place in _matches(glob) if places.blocked(norm(place), write) in NEVER_PLACES), "")


def _inside_protected(folder: str, write: bool, places) -> str:
    """A place inside `folder` never touched (the app's own, a secret's), "" none, "?" when there are too many files
    to tell."""
    found = _walk(folder)
    if found is None:
        return "?"
    return next((place for place in found if places.blocked(os.path.normcase(place), write) in NEVER_PLACES), "")


def _receives(act: Act, path: str) -> bool:
    """Whether `act` puts content at `path` (a write, a copy's or a move's destination), not only takes a file away
    (a delete, a move's source)."""
    return (bool(path) and path == act.dest) or (act.kind != "delete" and act.what != "move")


def _reaches_system(act: Act, places) -> str:
    """For a change by wildcard or to a whole folder: a file in it that is Windows', a program's, or one that runs by
    itself (Places.blocked's "system"), asked every time as `_system_places` asks a named one; "" none."""
    if not act.write:
        return ""
    receives = _receives(act, "")
    for glob in act.globs:
        found = [norm(p) for p in _matches(glob)] if _wild(glob) else []
        reached = next((p for p in found if places.blocked(p, True, receives=receives) == "system"), "")
        if not reached and act.recurse and os.path.isdir(_base(glob)[0]):
            reached = next((p for p in _walk(_base(glob)[0]) or [] if places.blocked(
                os.path.normcase(p), True, receives=receives) == "system"), "")
        if reached:
            return reached
    return ""


def _targets(act: Act) -> list[str] | None:
    """What a wildcard names now, found in Python as PowerShell would match it (a listing's items come already
    listed). None when there are more than can be told first."""
    found: list[str] = []
    for glob in act.globs:
        found += _matches(glob) if _wild(glob) else [glob]
    found = _outermost([p for p in dict.fromkeys(found) if os.path.lexists(p)])
    return found if len(found) <= LIST_MOST else None


def _outermost(paths: list[str]) -> list[str]:
    """`paths` less those inside another of them: a folder taken whole leaves out what is inside it."""
    normed = [norm(p) for p in paths]
    # Each path's parent as `under` reads it (the path without its trailing separators), to the paths it stands for.
    holders: dict[str, set[str]] = {}
    for n in normed:
        holders.setdefault(n.rstrip("\\/"), set()).add(n)

    def inside(n: str) -> bool:
        return any(n[i] == os.sep and holders.get(n[:i], set()) - {n} for i in range(len(n)))

    return [p for p, n in zip(paths, normed) if not inside(n)]


def _names(act: Act) -> str:
    """How much a read takes of the places it names (grants.Places.blocked): "" their contents; "look" whether one
    is there, its size and dates; "shallow" or "deep" the names in a folder, or all below it."""
    if act.what not in NAMES_ONLY or act.write:
        return ""
    return "look" if act.what != "list" else "deep" if act.recurse else "shallow"


def _refused_places(act: Act, cwd: str, places) -> list[Act]:
    """What `act` may never do by its places: run a file from the web, or touch the app's own or a secret place. A
    change to Windows', a program's or a drive's own files, or one that would run by itself later, is asked every
    time as a costly system step instead (`_system_places`)."""
    refused = []
    # A program or script that came from the web is never run or opened by the character (crossing.py).
    if act.kind in ("program", "install") or act.args is not None or act.what == "open":
        refused += [Act("hidden", "downloaded", f"runs {path}, which was downloaded from the web", paths=[path])
                    for path in dict.fromkeys(act.paths + [os.path.join(cwd, a) for a in act.args or []])
                    if downloaded(path)]
    for path in act.paths + ([act.dest] if act.dest else []):
        why = places.blocked(norm(path), act.write or path == act.dest, _names(act))
        # A program's own file (user installs live in AppData) is run, not read: only the app's own refuse.
        if why in ("", "system") or (why != "app" and act.args is not None and path == act.paths[0]):
            continue
        whose = "this app's own files" if why == "app" else "protected"
        refused.append(Act("secrets" if why in ("app", "secrets") else "system", why,
                           f"touches {path}, which is {whose}", paths=[path]))
    return refused


def _system_places(act: Act, places) -> list[Act]:
    """The changes asked every time as a costly system step (cardwait.COSTLY, by shell/panel.py's `_risk`): to
    Windows', a program's or a drive's own files, other programs' data, and anywhere what is written would run or be
    loaded without the person starting it (grants.Places.runs_later)."""
    asks = []
    for path in act.paths + ([act.dest] if act.dest else []):
        write = act.write or path == act.dest
        if write and places.blocked(norm(path), True, receives=_receives(act, path)) == "system":
            asks.append(Act("unknown", "runs_later", f"{act.why}; {places.runs_later(norm(path), _receives(act, path)) or 'it changes a system or program file'}",
                            paths=[path], write=True))
    return asks


def _new_runnable(act: Act, path: str) -> Act | None:
    """A new file that runs when it is opened (a script, a batch file), written in an ordinary folder: the
    reviewer's, on the person's words; asked when it does not pass. It runs only when someone starts it. So is a
    project's tool file (grants.PROJECT_FILES), new or replaced: its tools run it when the project is built or tested."""
    if (act.write or path == act.dest) and os.path.basename(path).lower() in PROJECT_FILES:
        return Act("program", "project_file", f"writes {os.path.basename(path)}, which the project's tools run",
                   paths=[path], name=os.path.basename(path), write=True)
    if (act.write or path == act.dest) and not os.path.exists(path) and os.path.splitext(path)[1].lower() in RUNS_LATER:
        return Act("program", "new_runnable", f"writes {os.path.basename(path)}, a file that runs when it is opened",
                   paths=[path], name=os.path.basename(path), write=True)
    return None


def _moves_and_links(act: Act, grants: Grants) -> list[Act]:
    """Asks for a move out of its granted folder, and for links a recursive act would follow outside them."""
    asks = []
    if act.what == "move" and act.dest and act.paths:
        src_roots = {grants.root_of(norm(p)) for p in act.paths}
        if src_roots != {grants.root_of(norm(act.dest))}:
            asks.append(Act("move_out", "move_out", f"moves out of {', '.join(sorted(src_roots))}",
                            paths=act.paths, dest=act.dest))
    if act.recurse and act.kind in ("read", "change", "delete"):
        asks += [Act("outside", "outside", f"{link} inside leads outside the open places", paths=[link])
                 for path in act.paths if os.path.isdir(path)
                 for link in _escaping_links(path, lambda p: grants.open(p) and not grants.places.blocked(p, False))]
    return asks


def _replaced(found: list[str], dest: str) -> list[str]:
    """The files a wildcard copy or move replaces: each item lands in `dest` by its own name."""
    out = []
    for src in found:
        target = os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) else dest
        if os.path.isfile(target) and os.path.normcase(target) != os.path.normcase(src):
            out.append(target)
    return out


def _listed_changes(acts: list[Act], verdict: Verdict) -> list[Act]:
    """The real list of what each delete moves to the Recycle Bin and what a wildcard change replaces, put in the
    verdict; asks for those with more items than can be listed first."""
    asks = []
    for act in acts:
        if act.unresolved or act.kind not in ("delete", "change", "overwrite"):
            continue
        found = _targets(act) if act.wild else list(act.paths)
        if found is None:
            asks.append(Act("unknown", "unresolved", f"{act.why}, over more files than can be listed first",
                            paths=act.paths))
        elif act.kind == "delete":
            verdict.deletes += [{"path": p, **running.listing(p)} for p in found]
        elif act.dest and act.what in ("copy", "move"):
            verdict.overwrites += _replaced(found, act.dest) if act.wild else []
        elif act.wild and act.what in ("write", "attr", "empty"):
            verdict.overwrites += [p for p in found if os.path.isfile(p)]
    return asks


def judge(reading: Reading, grants: Grants) -> Verdict:
    """Holds a reading against the never list and the person's grants, with the real list of what a delete moves
    to the Recycle Bin and what a wildcard copy or move replaces, found in Python."""
    if reading.errors:
        return Verdict("invalid", [Act("unknown", "invalid", "; ".join(reading.errors)[:400])])
    places = grants.places
    # Only what is never done is refused (acts.never); a system change past that is asked every time.
    refused = [a for a in reading.acts if a.kind in NEVER_KINDS and never(a)]
    asks: list[Act] = [Act("unknown", "system", a.why, paths=a.paths, name=a.name) for a in reading.acts
                       if a.kind in NEVER_KINDS and not never(a)]
    for act in reading.acts:
        reached = _reaches_protected(act, places)
        if reached == "?":
            asks.append(Act("unknown", "unresolved", f"{act.why}, over more files than can be checked first",
                            paths=act.paths))
        elif reached:
            refused.append(Act("secrets", "secrets", f"{act.why}, which reaches {reached}, which is protected",
                               paths=[reached]))
        elif (system := _reaches_system(act, places)) and system != "?":
            asks.append(Act("unknown", "runs_later", f"{act.why}, which reaches {system}, a program's or the "
                                                     "system's own file", paths=act.paths, write=True))
    for act in reading.acts:
        refused += _refused_places(act, reading.cwd, places)
        asks += _system_places(act, places)
    if refused:
        return Verdict("refuse", refused)
    past_bin = [a for a in reading.acts if a.what == "skip_bin"]
    if past_bin:
        return Verdict("bin", past_bin)
    asks += [a for a in reading.acts if a.kind in ASK_KINDS]
    # A place computed only as it runs cannot be checked first: asked (a new name in the same folder is the
    # exception, Rename-Item cannot move a file).
    asks += [Act("unknown", "unresolved", f"{a.why}, at places computed only when it runs", paths=a.paths)
             for a in reading.acts if a.unresolved and (a.kind == "read" or (
                 a.kind in ("change", "overwrite") and not (a.what == "rename" and a.dest_unresolved)))]
    # A program's own file is outside the granted folders by nature; running it is asked as a program.
    every = [(act, p) for act in reading.acts for p in act.paths + ([act.dest] if act.dest else [])
             if not (act.args is not None and p == act.paths[0])]
    for act, path in every:
        write = act.write or path == act.dest
        if write and any(norm(path) in a.paths or path in a.paths for a in asks if a.what == "runs_later"):
            continue
        new = _new_runnable(act, path)
        if new:
            asks.append(new)
            continue
        # Open by default (Grants.open): the profile and the other drives; a place's name, size and dates anywhere,
        # and the program places Start reads by name (grants.FINDABLE). What is protected was refused above.
        if grants.open(norm(path), write) or (not write and (act.what == "look" or (
                _names(act) and not places.blocked(norm(path), False, "deep") and any(
                    under(norm(path), p) for p in places.findable)))):
            continue
        folder = _folder_to_grant(grants, path)
        if folder and not places.grantable(norm(folder)):
            return Verdict("folder", [act], folder=folder, write=write)
        asks.append(Act("outside", "outside", f"{act.why}; {path} is outside the folders they granted", paths=[path],
                        write=act.write))
    for act in reading.acts:
        asks += _moves_and_links(act, grants)
    verdict = Verdict("run", [])
    asks += _listed_changes(reading.acts, verdict)
    if verdict.overwrites and not any(a.kind == "overwrite" for a in asks):
        asks.append(Act("overwrite", "overwrite", f"overwrites {', '.join(verdict.overwrites[:5])}",
                        paths=verdict.overwrites))
    verdict.root = next((root for root in (grants.root_of(norm(p)) for _, p in every) if root), "")
    if asks:
        verdict.action, verdict.reasons = "ask", asks
    return verdict
