"""What a command would do, as the readers (read.py for PowerShell, bashread.py for bash) and the file tools
(files.py) sort it: one `Act` per effect, gathered in a `Reading` that `read.judge` holds against the grants."""
from __future__ import annotations

from dataclasses import dataclass, field

# Kinds of act, mildest first. The never kinds are refused whatever was granted.
NEVER_KINDS = ("elevate", "system", "secrets", "hidden", "shutdown")
ASK_KINDS = ("delete", "overwrite", "outside", "move_out", "network", "install", "program", "unknown")
# A longer command is not read: it comes back with an error.
COMMAND_MAX = 4000


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
    runs or opens a program, "read" when it does nothing but read, else "change"."""
    if any(a.kind in ("program", "install") or a.what == "open" for a in acts):
        return "program"
    return "read" if all(a.kind == "read" and not a.write for a in acts) else "change"


def download_run(acts: list[Act]) -> list[Act]:
    """The never act of a command that both saves from the network and runs a program, or none."""
    if any(a.kind == "network" and a.paths for a in acts) and any(a.kind in ("program", "install") for a in acts):
        return [Act("hidden", "download_run", "downloads something and runs it in the same command")]
    return []
