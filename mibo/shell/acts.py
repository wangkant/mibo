"""What a command would do, as the readers (read.py for PowerShell, bashread.py for bash) and the file tools
(files.py) sort it: one `Act` per effect, gathered in a `Reading` that `read.judge` holds against the grants."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Kinds of act, mildest first. The never kinds are refused whatever was granted when they are what is never done
# (`never`); the rest of them is asked every time as a costly system step (read.judge).
NEVER_KINDS = ("elevate", "system", "secrets", "hidden", "shutdown")
# What is never done, the one list every refusal of a command is for: reading a secret place (this app's own files,
# keys, sign-ins, other programs' data, a registry key not listed as readable), running or opening what came from the
# web, running as administrator, a command built to hide what it does (encoded, computed, downloaded and run), and
# changing security settings (firewall, antivirus, policies, permissions on files, remote management, sign-in
# secrets).
SECURITY = re.compile(r"firewall|defender|mppreference|mpcmdrun|executionpolicy|\buac\b|i?cacls|xcacls|takeown|auditpol|"
                      r"secedit|gpupdate|gpedit|polic|bcdedit|netsh|winrm|winrs|remote|another computer|ntdsutil|"
                      r"nltest|ksetup|wevtutil|security|\blsa\b|credential|winlogon|this computer's own services",
                      re.I)
ASK_KINDS = ("delete", "overwrite", "outside", "move_out", "network", "install", "program", "unknown")
# Code run: given as text, a file of code an interpreter or a runner is given (pstables.RUNNERS), an environment
# variable that makes a program run code (pstables.CODE_ENV); with what its text shows (code.py) or the turn around
# it (shell/panel.py). It runs under a change's limits (`tier`), online only for its "code" network act, which is
# asked every time.
CODE = ("inline", "written", "script", "env")
CODE_SIGNS = ("pieces", "read_outside")
# Writes the reviewer judges as it judges a program run (read._new_runnable): a file that runs when opened, a project's
# tool file. They run nothing now, so they never lift a command's limits (`tier`).
RUNS_WHEN_STARTED = ("new_runnable", "project_file")
# A longer command is not read: it comes back with an error.
COMMAND_MAX = 4000


def never(act: Act) -> bool:
    """Whether a never kind of act is one of what is never done (SECURITY's list), not a system change to ask."""
    if act.kind in ("secrets", "elevate", "hidden") or (act.kind, act.what) == ("system", "device"):
        # A raw device path (\?\, \.\) reaches past every check of a place: hidden.
        return True
    if act.kind == "system" and act.what == "registry":
        return act.why.startswith("reads") or bool(SECURITY.search(act.why))
    return act.kind == "system" and bool(SECURITY.search(f"{act.why} {act.name}"))


@dataclass
class Act:
    """One thing a command would do."""
    kind: str
    what: str
    why: str
    paths: list[str] = field(default_factory=list)
    dest: str = ""
    name: str = ""
    write: bool = False
    recurse: bool = False
    wild: bool = False
    unresolved: bool = False
    sends: bool = False
    host: str = ""
    raw: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)
    dest_unresolved: bool = False
    # The places a listing before named, with `raw`, which stand for its items in the plain words.
    listed: list[str] = field(default_factory=list)
    # A program run by its own file (paths[0]): its arguments as written, for the person's always-allow rules.
    args: list[str] | None = None


@dataclass
class Reading:
    """One command read before it runs: what it would do, or why it could not be read."""
    command: str
    cwd: str
    acts: list[Act]
    errors: list[str]


def tier(acts: list[Act]) -> str:
    """Which of Windows' own limits a command runs under (confine.py), from what it was read to do: "program" when it
    runs or opens a program, "read" when it does nothing but read, else "change". Code run (python -c, a script, a
    project's tests: `CODE`) is never a program's run, whatever else the command runs with it."""
    if any(a.what in CODE for a in acts):
        return "change"
    if any((a.kind in ("program", "install") and a.what not in RUNS_WHEN_STARTED) or a.what == "open" for a in acts):
        return "program"
    return "read" if all(a.kind == "read" and not a.write for a in acts) else "change"


def download_run(acts: list[Act]) -> list[Act]:
    """The never act of a command that both saves from the network and runs a program, or none."""
    if any(a.kind == "network" and a.paths for a in acts) and any(a.kind in ("program", "install") for a in acts):
        return [Act("hidden", "download_run", "downloads something and runs it in the same command")]
    return []
