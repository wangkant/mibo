"""Sorting a program run by its file name in a PowerShell command, and what Start-Process and Invoke-Item
start: the part of pssort.Sorter that knows Windows' programs (EXE_* in pstables)."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from ..crossing import from_web
from .code import python
from .code import words as code_acts
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
    GIT_CODE,
    GIT_NET,
    INSTALLERS,
    INTERPRETERS,
    NPM_RUNS,
    NVIDIA_READ,
    OPEN_RISKY,
    RUNNABLE,
    RUNNERS,
    SCRIPT_SWITCHES,
    TEST_MODULES,
)

# An interpreter's options that give it code on the command line.
INLINE_CODE = ("-c", "-e", "-p", "--eval", "--print", "-command", "-r", "-jar")
# curl's, wget's and the like's options and words that send something.
SENDING = ("-d", "--data", "-f", "--form", "-t", "--upload-file", "-x", "--request", "push", "put", "send", "-h",
           "--header", "-u", "--user", "-b", "--cookie")
SENDING_PREFIXES = ("--data", "-d", "-f", "-t", "-h", "-u", "-b")
# The readers among EXE_READ that name files to read.
FILE_READERS = ("findstr", "tree", "fc", "comp", "more", "sort")


# Options of interpreters that take the next argument as their value, not as the script.
VALUE_OPTIONS = ("-x", "-w", "--env-file", "--config", "-c", "--cwd")
# Options that have node load a file of code before the script.
PRELOAD = ("--require", "--import", "--loader", "--experimental-loader")
# yarn's and pnpm's subcommands that are not a package.json script's name.
NOT_SCRIPTS = ("add", "install", "i", "remove", "rm", "upgrade", "up", "update", "create", "global", "link", "unlink",
               "init", "publish", "config", "set", "info", "list", "ls", "why", "outdated", "audit", "cache", "login",
               "logout", "version", "help", "import", "pack", "patch", "plugin", "dedupe", "store", "setup", "env")


def git_code(words: list[str]) -> str:
    """A setting of git's that runs a program (pstables.GIT_CODE), set by a git command's -c, --config-env or
    `git config`; "" for none. An alias runs a program only when its value starts with "!"."""
    pairs = [w.split("=", 1) for n, w in enumerate(words) if n and words[n - 1] == "-c"]
    pairs += [w[2:].split("=", 1) for w in words if w.startswith("-c") and len(w) > 2 and "=" in w]
    pairs += [w.split("=", 2)[1:] for w in words if w.startswith("--config-env=")]
    if "config" in words and not any(w in ("--unset", "--unset-all", "--get", "--get-all", "--get-regexp", "--list",
                                           "-l", "--remove-section", "--rename-section") for w in words):
        rest = words[words.index("config") + 1:]
        given = [w for n, w in enumerate(rest) if not w.startswith("-") and not (
            n and rest[n - 1] in ("-f", "--file", "--blob", "--type", "--default", "--comment"))]
        given = given[1:] if given[:1] == ["set"] else given
        if len(given) >= 2:
            pairs.append(given[:2])
    return next((key for key, *value in pairs if GIT_CODE.match(key) and (
        not key.startswith("alias.") or "".join(value).lstrip("'\"").startswith("!"))), "")


class Programs:
    """Mixed into pssort.Sorter, whose add(), loopback() and paths these use."""

    def program(self, node: dict, name: str, path: str, ctype: str) -> None:
        """A program or script run by its file name (`path` when PowerShell found it)."""
        base = os.path.splitext(os.path.basename(path or name))[0].lower()
        args = _plain_args(node, self.paths)
        ext = os.path.splitext(path or name)[1].lower()
        words = [a.lower() for a in (args or [])]
        # The name as written: a bare one PowerShell found on PATH.
        typed = str((node.get("first") or {}).get("v") or name)
        if base == "git" and git_code(words):
            self.add("unknown", "git_code", f"sets git's {git_code(words)}, which runs a program", name=git_code(words))
        if base in RUNNERS and args is not None and self.runner(base, args, words):
            return
        if base in EXE_NEVER:
            self.add(EXE_NEVER[base], EXE_NEVER[base], f"runs {base}")
        elif (ctype == "ExternalScript" or ext in RUNNABLE[2:]) and not (path and not re.search(r"[\\/.]", typed)):
            # A script named by its path; one found on PATH by a bare name is an installed tool's (npm.ps1), sorted
            # below by its name.
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
        if args is None:
            self.add("hidden", "hidden", f"runs {base} with arguments computed as it runs")
        elif any(a in INLINE_CODE for a in words):
            # Code written out on the command line hides nothing: the reader cannot read it, so it is a code run
            # whose code the reviewer and the question show, under a change's limits (acts.tier), with what its
            # text shows (code.py).
            self.add("program", "inline", f"runs {base} with this code: {' '.join(args)[:300]}",
                     name=f"{base} {' '.join(args)}"[:160])
            at = next(n for n, a in enumerate(words) if a in INLINE_CODE)
            self.acts += python(args[at + 1] if at + 1 < len(args) else "", self.paths.cwd) if base.startswith(
                "py") and words[at] == "-c" else code_acts(" ".join(args))
        elif words[:2] == ["-m", "pip"]:
            self.pip(words[2:], base)
        elif words and words[0] in ("--version", "-v", "-version"):
            self.add("read", "info", f"asks {base} its version")
        else:
            # Started with no file of code: it waits for code on its input.
            self.add("program", "script", f"runs {base} {' '.join(args)[:80]}", name=f"{base} {' '.join(args)}"[:120])

    def runner(self, base: str, args: list[str], words: list[str]) -> bool:
        """An interpreter or a runner given a file of code, a module, a notebook or a project's tests
        (pstables.RUNNERS): a code run (acts.CODE) under a change's limits, its file read with it (code.scripts), and
        never one from the web. False when its arguments give it no such thing (inline code, a version, an install,
        a switch that keeps it hidden), for the rest of `program` to sort."""
        kind, cwd = RUNNERS[base], self.paths.cwd
        name = f"{base} {' '.join(args)}"[:160]
        plain = [a for n, a in enumerate(args) if not a.startswith(("-", "/")) and not (
            n and words[n - 1] in VALUE_OPTIONS)]
        if kind == "script" and base in INTERPRETERS:
            if any(w in INLINE_CODE for w in words) or words[:1] in (["--version"], ["-v"], ["-version"]):
                return False
            if words[:1] == ["-m"] and len(words) > 1:
                return words[1] != "pip" and self.module(base, args[1], name)
            plain = plain[1:] if base in ("deno", "bun") and plain[:1] == ["run"] else plain
            plain = [args[n + 1] for n, w in enumerate(words[:-1]) if w in PRELOAD] + [
                a for a in plain if not any(a == args[n + 1] for n, w in enumerate(words[:-1]) if w in PRELOAD)][:1]
            for extra in plain[:-1]:
                self.script(extra, name)
            plain = plain[-1:]
        elif kind == "script":
            # cscript and wscript: their own switches start with //.
            plain = [a for a in args if not a.startswith("//")]
        elif kind == "file":
            at = next((n for n, w in enumerate(words) if w in ("-file", "-f")), None)
            switches = words[:at] if at is not None else words
            # The execution policy a script runs under is its own process's: the script is read whatever it says.
            policy = {n + 1 for n, w in enumerate(switches) if w in ("-executionpolicy", "-ep", "-exec")}
            if at is None or at + 1 >= len(args) or any(
                    w not in (*SCRIPT_SWITCHES, "-executionpolicy", "-ep", "-exec") and n not in policy
                    for n, w in enumerate(switches)):
                return False
            plain = args[at + 1:]
        elif kind == "bat":
            at = next((n for n, w in enumerate(words) if w == "/c"), None)
            if at is None or at + 1 >= len(args) or any(w not in ("/d", "/q") for w in words[:at]) or \
                    os.path.splitext(args[at + 1])[1].lower() not in (".bat", ".cmd"):
                return False
            plain = args[at + 1:]
        elif kind == "tests":
            self.add("program", "script", f"runs the project's tests with {base}", name=name, paths=[cwd])
            return True
        elif kind == "notebook":
            if not (words[:1] in (["execute"], ["run"]) or ("nbconvert" in words and "--execute" in words)):
                return False
            plain = [a for a in plain if a.lower().endswith((".ipynb", ".py"))]
        elif kind == "make":
            given = next((args[n + 1] for n, w in enumerate(words[:-1]) if w in ("-f", "--file", "--makefile")), "")
            plain = [given or next((f for f in ("GNUmakefile", "makefile", "Makefile")
                                    if os.path.isfile(os.path.join(cwd, f))), "")]
        elif kind == "npm":
            first = words[0] if words else ""
            if first in ("exec", "x", "dlx"):
                return self.package(base, args[1:], name)
            if first not in NPM_RUNS and (base == "npm" or not first or first.startswith("-") or first in NOT_SCRIPTS):
                return False
            plain = ["package.json"]
        elif kind == "package":
            return self.package(base, args, name)
        if not plain or not plain[0]:
            return False
        return self.script(plain[0], name)

    def script(self, given: str, name: str) -> bool:
        """The file of code a runner is given: never one from the web, else run with what it holds read."""
        place = self.paths.place(given)[1]
        if from_web(place):
            self.add("hidden", "downloaded", f"runs {place}, which came from the web", paths=[place])
        else:
            self.add("program", "script", f"runs {name}", name=name, paths=[place])
        return True

    def module(self, base: str, module: str, name: str) -> bool:
        """python -m: a project's tests, a module of the folder (its file read), or one installed, judged by its name
        as an import is (code.python)."""
        cwd = self.paths.cwd
        if module.split(".")[0] in TEST_MODULES:
            self.add("program", "script", f"runs the project's tests with {base} -m {module}", name=name, paths=[cwd])
            return True
        top = os.path.join(cwd, *module.split("."))
        own = next((p for p in (top + ".py", os.path.join(top, "__main__.py")) if os.path.isfile(p)), "")
        if own:
            return self.script(own, name)
        self.add("program", "script", f"runs {name}", name=name)
        self.acts += python(f"import {module}", cwd)
        return True

    def package(self, base: str, args: list[str], name: str) -> bool:
        """npx, npm exec and the like: a package's program installed in the folder runs as code does; one not there
        is fetched from the registry first, an install."""
        package = next((a for a in args if not a.startswith("-")), "")
        bin_ = os.path.join(self.paths.cwd, "node_modules", ".bin", package.split("@")[0] if package else "")
        if package and any(os.path.isfile(bin_ + ext) for ext in ("", ".cmd", ".ps1")):
            self.add("program", "script", f"runs the folder's {package}", name=name, paths=[self.paths.cwd])
        else:
            self.add("install", "install", f"fetches and runs {package or 'a package'} with {base}", name=name)
        return True

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
        if base in RUNNERS and ext in ("", ".exe", ".cmd", ".bat", ".ps1") and self.runner(
                base, arguments, [a.lower() for a in arguments]):
            return
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
