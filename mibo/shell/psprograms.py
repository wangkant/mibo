"""Sorting a program run by its file name in a PowerShell command, and what Start-Process and Invoke-Item
start: the part of pssort.Sorter that knows Windows' programs (EXE_* in pstables)."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from .paths import _base, _local_host
from .psnodes import _bound, _plain_args
from .pstables import (
    EXE_INSTALL,
    EXE_NET,
    EXE_NEVER,
    EXE_OPEN,
    EXE_READ,
    EXE_REMOTE,
    EXE_STOP,
    GIT_NET,
    INSTALLERS,
    INTERPRETERS,
    NVIDIA_READ,
    OPEN_RISKY,
    RUNNABLE,
)

# An interpreter's options that give it code on the command line.
INLINE_CODE = ("-c", "-e", "-p", "--eval", "--print", "-command", "-r", "-jar")
# curl's, wget's and the like's options and words that send something.
SENDING = ("-d", "--data", "-f", "--form", "-t", "--upload-file", "-x", "--request", "push", "put", "send", "-h",
           "--header", "-u", "--user", "-b", "--cookie")
SENDING_PREFIXES = ("--data", "-d", "-f", "-t", "-h", "-u", "-b")
# The readers among EXE_READ that name files to read.
FILE_READERS = ("findstr", "tree", "fc", "comp", "more", "sort")


class Programs:
    """Mixed into pssort.Sorter, whose add(), loopback() and paths these use."""

    def program(self, node: dict, name: str, path: str, ctype: str) -> None:
        """A program or script run by its file name (`path` when PowerShell found it)."""
        base = os.path.splitext(os.path.basename(path or name))[0].lower()
        args = _plain_args(node, self.paths)
        ext = os.path.splitext(path or name)[1].lower()
        words = [a.lower() for a in (args or [])]
        if base in EXE_NEVER:
            self.add(EXE_NEVER[base], EXE_NEVER[base], f"runs {base}")
        elif ctype == "ExternalScript" or ext in RUNNABLE[2:]:
            self.add("program", "script", f"runs the script {path or name}", name=path or name, paths=[path] if path else [])
        elif ext in INSTALLERS:
            self.add("install", "install", f"runs the installer {path or name}", name=path or name)
        elif base in INTERPRETERS:
            self.interpreter(base, args, words)
        elif base in ("pip", "pip3"):
            self.pip(words, base)
        elif base in EXE_INSTALL:
            self.install_tool(base, args, words)
        elif base in EXE_STOP:
            self.add("program", "stop", f"ends a running program ({' '.join(args or [])[:60]})", name=f"{base} {' '.join(args or [])}"[:120])
        elif base == "git" and args is not None and not (set(words) & GIT_NET) and not any(
                "://" in a or a.startswith("--remote") for a in words):
            # Local git work (status, log, add, commit, diff) is a program run in its folder, not the network.
            self.add("program", "program", f"runs git {' '.join(args)[:80]}", name=f"{path or name} {' '.join(args)}"[:160],
                     paths=[path] if path else [], args=args)
        elif base in EXE_NET:
            self.exe_net(base, args, words)
        elif base in EXE_READ:
            self.exe_read(base, args, words)
        elif base in EXE_OPEN:
            self.exe_open(base, args)
        else:
            self.add("program", "program", f"runs the program {path or name}", name=f"{path or name} {' '.join(args or [])}"[:160],
                     paths=[path] if path else [], args=args)

    def interpreter(self, base: str, args: list[str] | None, words: list[str]) -> None:
        if args is None or any(a in INLINE_CODE for a in words):
            self.add("hidden", "hidden", f"runs {base} with code given on the command line")
        elif words[:2] == ["-m", "pip"]:
            self.pip(words[2:], base)
        elif words and words[0] in ("--version", "-v"):
            self.add("read", "info", f"asks {base} its version")
        else:
            self.add("program", "script", f"runs {base} {' '.join(args)[:80]}", name=f"{base} {' '.join(args)}"[:120])

    def install_tool(self, base: str, args: list[str] | None, words: list[str]) -> None:
        if words and words[0] in ("list", "ls", "--version", "-v", "freeze", "show", "info"):
            self.add("read", "apps", f"lists what {base} installed")
        elif base == "winget" and words and words[0] in ("search", "show"):
            self.add("network", "net", "searches the winget catalogue online", host="winget", sends=False)
        else:
            self.add("install", "install", f"runs {base} {' '.join(args or [])[:80]}",
                     name=f"{base} {' '.join(args or [])}"[:120])

    def exe_net(self, base: str, args: list[str] | None, words: list[str]) -> None:
        host = next((a for a in (args or []) if not a.startswith("-") and not a.startswith("/")), "")
        host = (urlsplit(host).hostname or host).lower()
        if host and _local_host(host):
            self.loopback(host)
            return
        sends = base in ("curl", "wget", "ftp", "tftp", "nc", "ncat", "git") and (
            args is None or any(a in SENDING or a.startswith(SENDING_PREFIXES) for a in words))
        self.add("network", "net", f"runs {base} to reach {host or 'the network'}", host=host or base, sends=sends,
                 name=f"{base} {' '.join(args or [])}"[:120])

    def exe_read(self, base: str, args: list[str] | None, words: list[str]) -> None:
        """A program that reads (EXE_READ), unless its words make it change the system, reach another computer
        or write a file."""
        if args is None:
            self.add("unknown", "unknown", f"runs {base} with computed arguments")
        elif base == "ipconfig" and any(a not in ("/all", "/?", "-all") for a in words):
            self.add("system", "system", "changes the network setup with ipconfig")
        elif base == "wmic" and any(a.startswith("/format") for a in words):
            self.add("hidden", "hidden", "runs wmic with a style sheet, which can run code")
        elif base == "wmic" and any(a.startswith("/node") for a in words):
            self.add("system", "remote", "runs wmic against another computer")
        elif base == "wmic" and (any(a in ("call", "create", "delete", "set", "process") for a in words)
                                 or any(a.startswith("/") for a in words)):
            self.add("system", "system", "changes the system through wmic")
        elif base == "fsutil" and words[:2] not in (["volume", "diskfree"], ["fsinfo", "drives"]):
            self.add("system", "system", "runs fsutil, a disk tool")
        elif base in EXE_REMOTE and any(a in ("/s", "-s") for a in words):
            self.add("network", "net", f"runs {base} against another computer", host=base, sends=True,
                     name=f"{base} {' '.join(args)}"[:120])
        elif base == "nvidia-smi" and any(a.startswith("-") and not a.startswith(NVIDIA_READ) for a in words):
            self.add("system", "system", "changes the graphics card's settings with nvidia-smi")
        elif (base == "sort" and any(a.startswith(("/o", "/output")) for a in words)) or (
                base == "gpresult" and any(a.startswith(("/h", "/x")) for a in words)):
            self.add("unknown", "write", f"runs {base}, which writes a file", name=f"{base} {' '.join(args)}"[:120])
        else:
            files = [a for a in args if a and not a.startswith(("/", "-")) and base in FILE_READERS]
            if base == "findstr" and files:
                files = files[1:]
            files += [a[3:] for a in args if base == "findstr" and a.lower().startswith(("/f:", "/g:"))]
            places = [self.paths.place(a)[1] for a in files]
            self.add("read", "search" if base == "findstr" else ("disk" if base == "fsutil" else "info"),
                     f"runs {base}", paths=[_base(p)[0] for p in places], globs=places,
                     wild=any(_base(p)[1] for p in places), recurse=base == "findstr" and "/s" in words)

    def exe_open(self, base: str, args: list[str] | None) -> None:
        """notepad, explorer and the like: a program that shows what it is given, unless that runs something."""
        if args is None:
            self.add("unknown", "unknown", f"opens {base} with computed arguments")
            return
        targets = [a for a in args if a and not a.startswith(("/", "-"))]
        for target in targets:
            if self.opened(target, base):
                return
        files = [self.paths.place(a)[1] for a in targets]
        self.add("read", "open", f"opens {base}", name=base, paths=files)

    def opened(self, target: str, base: str) -> bool:
        """A program given an address or a file it would run (explorer x.bat, explorer https://...): sorted as
        that, True; a plain file to show, False."""
        if self.address(target, f"{base} opens"):
            return True
        if os.path.splitext(target)[1].lower() in OPEN_RISKY:
            place = self.paths.place(target)[1]
            self.add("program", "program", f"{base} runs {target}", name=target[:160], paths=[place])
            return True
        return False

    def address(self, target: str, opens: str) -> bool:
        """An address opened (https://... in the browser, any other scheme in its own program): sorted, True;
        not an address, False."""
        scheme = re.match(r"^([a-z][a-z0-9+.-]+):", target, re.IGNORECASE)
        if not scheme:
            return False
        if scheme.group(1).lower() in ("http", "https"):
            host = (urlsplit(target).hostname or "").lower()
            if _local_host(host):
                self.loopback(host, "opens")
            else:
                self.add("network", "browse", f"opens {target[:120]} in the browser", host=host or target[:40],
                         sends=True)
        else:
            self.add("program", "program", f"{opens} {target[:120]}", name=target[:160])
        return True

    def pip(self, words: list[str], base: str) -> None:
        if words and words[0] in ("list", "show", "freeze", "check", "--version", "-v"):
            self.add("read", "apps", f"lists what {base} installed")
        else:
            self.add("install", "install", f"runs pip {' '.join(words)[:80]}", name=f"pip {' '.join(words)}"[:120])

    def start(self, node: dict, name: str) -> None:
        """Start-Process and Invoke-Item: each target opened in its own program, run, or installed."""
        if name == "start-process":
            verbs = self.paths.strings(_bound(node, "Verb")) if _bound(node, "Verb") is not None else []
            verb = " ".join(verbs or []).lower()
            if verbs is None or "runas" in verb or _bound(node, "Credential") is not None:
                self.add("elevate", "elevate", "starts a program as administrator or as another user")
                return
            targets = self.paths.strings(_bound(node, "FilePath"))
            if targets is None:
                self.add("hidden", "hidden", "starts a program whose name is computed")
                return
            arguments = self.paths.strings(_bound(node, "ArgumentList")) if _bound(node, "ArgumentList") is not None else []
        else:
            targets = None if not any(_bound(node, p) is not None for p in ("Path", "LiteralPath")) else \
                self.paths.strings(_bound(node, "Path") or _bound(node, "LiteralPath"))
            arguments = []
        if targets is None or arguments is None:
            self.add("unknown", "program", "starts something whose name is computed")
            return
        for target in targets:
            if not self.address(target, "opens"):
                self.started(target, arguments)

    def started(self, target: str, arguments: list[str]) -> None:
        """One file Start-Process or Invoke-Item starts."""
        base = os.path.splitext(os.path.basename(target))[0].lower()
        ext = os.path.splitext(target)[1].lower()
        place = self.paths.place(target)[1]
        exists = os.path.exists(place)
        if base in EXE_NEVER:
            self.add(EXE_NEVER[base], EXE_NEVER[base], f"starts {base}")
        elif ext in INSTALLERS:
            self.add("install", "install", f"starts the installer {target}", name=target, paths=[place] if exists else [])
        elif (ext in OPEN_RISKY or (not exists and not ext)) and base in EXE_OPEN and not arguments:
            self.add("read", "open", f"opens {base}", name=base)
        elif ext in OPEN_RISKY or (not exists and not ext):
            self.add("program", "program", f"starts {target} {' '.join(arguments)}".strip()[:160],
                     name=f"{target} {' '.join(arguments)}".strip()[:160], paths=[place] if exists else [])
        else:
            self.add("read", "open", f"opens {place} in its own program", paths=[place], name=os.path.basename(place))
