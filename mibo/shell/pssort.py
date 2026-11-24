"""Sorting what parse.ps1 read into acts: every command, redirection, method call, type name and assignment
in a PowerShell command, its paths made absolute."""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .acts import Act
from .paths import Paths, _base, _copy_overwrites, _listed, _local_host, _some, _unzip_overwrites
from .psmethods import Methods
from .psnodes import _bound, _items, _named, _switch
from .psprograms import Programs
from .pstables import (
    CHANGES,
    CODE_ENV,
    DISK_CLASSES,
    DRY_DEFEATERS,
    EXE_INSTALL,
    EXE_NET,
    EXE_NEVER,
    EXE_OPEN,
    EXE_READ,
    EXE_STOP,
    FACTS,
    FS_READERS,
    FS_SWITCHES,
    HIDDEN_VARS,
    INBOX_MODULES,
    INSTALL,
    INTERPRETERS,
    ITEM_FILTERS,
    ITEM_SOURCES,
    LISTING_EXACT,
    LISTING_RESHAPED,
    NETWORK,
    NEVER_CMDLETS,
    PURE,
    READ_PARAMS,
    READ_VERBS,
    READS,
    REGISTRY_READ,
    REGISTRY_WRITE,
    RUNNERS,
    SELECT_RESHAPED,
    SYSTEM_NOUNS,
    VARIABLE_CMDLETS,
    VARIABLE_PARAMS,
    VERBED,
)

# The programs sorted by their name even when PowerShell does not find them here.
KNOWN_PROGRAMS = {*EXE_NEVER, *INTERPRETERS, *EXE_READ, *EXE_NET, *EXE_INSTALL, *EXE_OPEN, *EXE_STOP, *RUNNERS}
# Commands that move where the command works.
LOCATIONS = ("set-location", "push-location", "pop-location")


@dataclass
class Listing:
    """What a stage that lists files hands down the pipeline."""
    paths: list[str]
    raw: list[str]
    globs: list[str]
    recurse: bool
    # A parameter past the path (-Filter, -Include, -Depth) picks among the items.
    narrowed: bool
    # The items themselves, found in Python; None when they cannot be listed first.
    items: list[str] | None


def _scopeless(name) -> str:
    """A variable's name, lowercased, without its scope ($global:x is $x)."""
    return re.sub(r"^(global|script|local|private):", "", str(name or "").lower())


def _remote(node: dict) -> bool:
    """The command is pointed at another computer."""
    return any(p.lower() in ("computername", "cimsession", "session") for p in (node.get("bound") or {}))


class Sorter(Programs, Methods):
    """Sorts one parsed command into acts (`acts`), following the folder it works in and the constants it sets."""

    def __init__(self, parsed: dict, cwd: str):
        self.parsed = parsed
        self.paths = Paths(cwd)
        self.acts: list[Act] = []
        self.funcs = {str(n.get("name") or "").lower() for n in _items(parsed.get("nodes")) if n.get("type") == "func"}
        # Each pipeline's listing so far, or None when what goes down it may be any path at all.
        self.pipes: dict[int, Listing | None] = {}
        self.last_raw: list[str] = []
        self.last_globs: list[str] = []
        self.last_listed: list[str] = []
        self.origin = cwd
        self.unstable, self.no_consts = self._unstable(_items(parsed.get("nodes")))

    @staticmethod
    def _unstable(nodes: list) -> tuple[set, bool]:
        """Variables that may hold more than one value as the command runs (assigned twice, looped over, set by
        name), and whether any variable may (set by a computed name, or through an object)."""
        seen: dict[str, int] = {}
        unstable: set[str] = set()
        anything = False

        def strip(v) -> str:
            return _scopeless(str(v or "").lstrip("+"))

        for node in nodes:
            if node.get("type") == "assign":
                if node.get("ltype") in ("MemberExpressionAst", "IndexExpressionAst"):
                    anything = True
                var = strip(node.get("var"))
                seen[var] = seen.get(var, 0) + 1
                if seen[var] > 1:
                    unstable.add(var)
            elif node.get("type") == "foreach":
                unstable.add(strip(node.get("var")))
            elif node.get("type") == "cmd":
                names = [_bound(node, p) for p in VARIABLE_PARAMS]
                if _named(node)[0] in VARIABLE_CMDLETS - {"get-variable"}:
                    names.append(_bound(node, "Name"))
                named = [el for el in names if el is not None]
                unstable |= {strip(el.get("v")) for el in named if isinstance(el, dict) and el.get("k") == "s"}
                anything = anything or any(not (isinstance(el, dict) and el.get("k") == "s") for el in named)
        return unstable, anything

    def add(self, kind: str, what: str, why: str, **more) -> Act:
        # The paths as written, from the files() call just before, for the plain words.
        more.setdefault("raw", self.last_raw)
        more.setdefault("globs", self.last_globs)
        more.setdefault("listed", self.last_listed)
        self.last_raw = []
        self.last_globs = []
        self.last_listed = []
        act = Act(kind, what, why, **more)
        self.acts.append(act)
        return act

    def loopback(self, host: str, verb: str = "reaches") -> None:
        """Aimed at this computer's own services, which may hold anything: refused."""
        self.add("system", "loopback", f"{verb} this computer's own services at {host}")

    def files(self, node: dict, params, write: bool, default_cwd: bool = False) -> tuple[list[str], bool, bool, bool]:
        """(absolute paths, any wildcard, any unresolved, from the pipeline) named by these parameters. A
        registry, certificate or other provider path is sorted on the spot."""
        out: list[str] = []
        raws: list[str] = []
        globs: list[str] = []
        wild = unresolved = False
        given = [el for el in (_bound(node, p) for p in params) if el is not None]
        if not given:
            if int(node.get("index") or 0) > 0:
                return self.piped(node)
            if default_cwd and self.paths.where:
                self.provider(*self.paths.where, write, node)
                return [], False, False, False
            if default_cwd:
                self.last_globs = [self.paths.cwd]
            return ([self.paths.cwd] if default_cwd else []), False, False, False
        for el in given:
            strings = self.paths.strings(el)
            if strings is None:
                unresolved = True
                # Its written part up to what is computed, when that names a file there (a stream's spelling,
                # `.env::$DATA`): a secret named so is still refused.
                head = re.split(r"[$`(]", str(el.get("t") or "") if isinstance(el, dict) else "", maxsplit=1)[0]
                head = re.sub(r"(?<=..):+[^\\/:]*$", "", head.strip("\"'"))
                provider, place = self.paths.place(head) if head else ("", "")
                if provider == "file" and os.path.isfile(place):
                    out.append(place)
                    raws.append(head)
                    globs.append(place)
                continue
            for raw in strings:
                provider, place = self.paths.place(raw)
                if provider == "file":
                    base, has = _base(place)
                    out.append(base)
                    raws.append(raw)
                    globs.append(place)
                    wild = wild or has
                else:
                    self.provider(provider, place, write, node)
        self.last_raw = raws
        self.last_globs = globs
        return out, wild, unresolved, False

    def piped(self, node: dict) -> tuple[list[str], bool, bool, bool]:
        """files() of the items from the stage before: known only when it listed files (ITEM_SOURCES) and what
        came after only filtered them; anything else may hand on any path at all."""
        upstream = self.pipes.get(node.get("pipe"))
        if upstream is None:
            return [], False, True, True
        if upstream.items is None:
            # More than can be listed first: the listing's own places stand for them.
            self.last_raw, self.last_globs = list(upstream.raw), list(upstream.globs)
            return list(upstream.paths), False, True, True
        self.last_globs = list(upstream.items)
        # Items picked among as it runs, or listed by patterns, are named by the listing in the plain words.
        if (upstream.narrowed or int(node.get("index") or 0) > 1
                or (upstream.raw and all(any(c in r for c in "*?") for r in upstream.raw))):
            self.last_raw, self.last_listed = list(upstream.raw), list(upstream.paths)
        return list(upstream.items), False, False, True

    def keeps(self, node: dict):
        """Which items a listing's -File, -Directory, -Filter and -Include let through, read loosely so that no
        item PowerShell would hand on is left out: Windows also matches a three-letter extension against a longer
        one and *.* against a name with no dot, and a pattern computed, with brackets, escapes, the system's own
        wildcards (< > ") or a short name's ~ narrows nothing here."""
        file, folder = _switch(node, "File"), _switch(node, "Directory")
        groups = []
        for param in ("Filter", "Include"):
            got = self.paths.strings(_bound(node, param)) if _bound(node, param) is not None else None
            if got and not any(c in s for s in got for c in "[`~<>\""):
                groups.append([s.lower().replace("?", "*") for s in got])

        def keep(path: str) -> bool:
            if (file and not os.path.isfile(path)) or (folder and not os.path.isdir(path)):
                return False
            name = os.path.basename(path).lower()
            stem, ext = os.path.splitext(name)
            names = (name, stem + ext[:4], name + ".")
            return all(any(fnmatch.fnmatchcase(n, s) for n in names for s in group) for group in groups)
        return keep

    def unlisted_recurse(self, node: dict, piped: bool) -> bool:
        """Items from a recursive listing too large to list first: any file under its places."""
        upstream = self.pipes.get(node.get("pipe")) if piped else None
        return upstream is not None and upstream.items is None and upstream.recurse

    def provider(self, provider: str, place: str, write: bool, node: dict) -> None:
        name = _named(node)[0]
        if provider == "registry":
            if not write and any(place == k or place.startswith(k + "\\") for k in REGISTRY_READ):
                self.add("read", "info", f"reads the registry key {place}")
            elif write and name == "set-itemproperty" and any(place == k for k in REGISTRY_WRITE):
                self.add("unknown", "setting", f"changes the Windows setting at {place}", name=place)
            else:
                self.add("system", "registry", f"{'changes' if write else 'reads'} the registry ({place})")
        elif provider == "cert":
            self.add("secrets", "certs", "reaches the certificate store")
        elif provider in ("function", "alias"):
            self.add("hidden", "redefine", f"changes PowerShell's own {provider}s, which hides what later commands do")
        elif provider == "wsman":
            self.add("system", "remote", "changes remote management settings")
        elif provider == "device":
            self.add("system", "device", f"reaches a raw device path ({place[:60]})")
        elif provider == "unc":
            # A share on another computer: the path and the person's sign-in go out over the network.
            self.add("network", "share", f"reaches the network share {place[:80]}", paths=[],
                     host=re.split(r"[\\/]", place[2:])[0], sends=True)
        elif provider == "provider":
            self.add("system", "provider", f"reaches PowerShell's {place.split(':')[0]} provider")
        elif provider == "env" and write and re.match(r"env:(path|pathext|psmodulepath|comspec)\b", place):
            self.add("hidden", "redefine", "changes where programs are looked up, which hides what later commands run")
        elif provider == "env" and write and CODE_ENV.match(place[4:]):
            self.env(place[4:])

    def sort(self) -> None:
        """Sorts every node parse.ps1 found, in the order they stand in the command."""
        for node in sorted(_items(self.parsed.get("nodes")), key=lambda n: int(n.get("off") or 0)):
            kind = node.get("type")
            if kind == "cmd":
                before = len(self.acts)
                self.command(node)
                self.pipe_on(node, self.acts[before:])
                self.redirects(node)
            elif kind == "expr":
                self.redirects(node)
            elif kind == "method":
                self.method(node)
            elif kind == "type":
                self.type_name(str(node.get("name") or ""))
            elif kind == "assign":
                self.assign(node)
            elif kind == "other":
                what = str(node.get("what"))
                if what in ("UsingStatementAst", "DynamicKeywordStatementAst"):
                    self.add("hidden", "hidden", f"uses {what[:-3]}, which loads or builds code")
                elif what == "TypeDefinitionAst":
                    self.add("unknown", "unknown", "defines a class")
        for name in _items(self.parsed.get("vars")):
            if _scopeless(name) in HIDDEN_VARS:
                self.add("hidden", "hidden", f"uses ${name}, which can run commands that cannot be read first")

    def pipe_on(self, node: dict, acts: list[Act]) -> None:
        """What a pipeline stage hands down after this command (its `acts`): the items a listing names, those
        a filter passes on, or anything at all."""
        name = _named(node)[0]
        pipe = node.get("pipe")
        given = {str(k).lower() for k in (node.get("bound") or {})}
        if name in ITEM_SOURCES and not self.paths.where:
            globs = [g for act in acts for g in act.globs]
            recurse = any(act.recurse for act in acts)
            # A place of another provider, or computed, or a listing that hands on something else.
            known = bool(acts) and not given & LISTING_RESHAPED and all(
                act.globs and not act.unresolved for act in acts)
            items = _listed(globs, name == "get-childitem", recurse or "depth" in given,
                            self.keeps(node)) if known else None
            self.pipes[pipe] = Listing([p for act in acts for p in act.paths],
                                       [r for act in acts for r in act.raw], globs, recurse,
                                       bool(given - LISTING_EXACT), items)
        elif (name not in ITEM_FILTERS or int(node.get("index") or 0) == 0
              or (name == "select-object" and given & SELECT_RESHAPED)):
            self.pipes[pipe] = None

    def redirects(self, node: dict) -> None:
        for redirect in _items(node.get("redirs")):
            el = redirect.get("file") or {}
            if el.get("var") == "null":
                continue
            if self.paths.where:
                self.add("system", "provider", "writes while working inside the registry or another provider")
                continue
            strings = self.paths.strings(el)
            if strings is None:
                self.add("unknown", "write", "writes its output to a file whose name is computed", unresolved=True,
                         write=True)
                continue
            for raw in strings:
                provider, place = self.paths.place(raw)
                if provider != "file":
                    self.provider(provider, place, True, node)
                    continue
                append = bool(redirect.get("append"))
                exists = os.path.isfile(place)
                self.add("overwrite" if exists and not append else "change", "append" if append else "write",
                         f"{'appends' if append else 'writes'} its output to {place}", paths=[place], write=True)

    def env(self, name: str) -> None:
        """An environment variable that makes a program run the code it names (pstables.CODE_ENV), set for the
        command: a code run (acts.CODE), the reviewer's at least."""
        self.add("program", "env", f"sets {name}, which makes programs run the code it names", name=name.upper())

    def assign(self, node: dict) -> None:
        var = _scopeless(node.get("var"))
        left = str(node.get("left") or "").lower().replace("{", "").replace("}", "")
        if var in ("whatifpreference", "confirmpreference") or left.startswith(("$function:", "$alias:")) or (
                node.get("ltype") != "VariableExpressionAst" and DRY_DEFEATERS.search(left)):
            self.add("hidden", "hidden", f"changes {node.get('left')}, which would change how commands delete or hide them")
        elif node.get("ltype") in ("MemberExpressionAst", "IndexExpressionAst"):
            # Setting a property is not a variable's new value.
            pass
        elif var.startswith("env:") and var[4:] in ("path", "pathext", "psmodulepath", "comspec"):
            self.add("hidden", "redefine", "changes where programs are looked up, which hides what later commands run")
        elif var.startswith("env:") and CODE_ENV.match(var[4:]):
            self.env(var[4:])
        elif var and node.get("op") == "Equals" and isinstance(node.get("right"), dict) and not self.no_consts \
                and var not in self.unstable:
            self.paths.consts[var] = node["right"]
        elif var:
            self.paths.consts.pop(var, None)

    def literal_places(self, node: dict) -> list[str]:
        """What cannot be sorted counts as the worst it could be: every literal argument that could be a path is
        taken as written to, so a key or the app's own files named there are still refused."""
        places = []
        for el in _items(node.get("args")):
            for raw in self.paths.strings(el) or []:
                if "://" in raw or not re.search(r"[\\/:]|\.\w{1,5}$|^\.", raw):
                    continue
                provider, place = self.paths.place(raw)
                if provider == "file":
                    places.append(_base(place)[0])
                else:
                    self.provider(provider, place, True, node)
        return places

    # ------------------------------------------------------------ one command

    def command(self, node: dict) -> None:
        """One command: refused when its name is computed or it changes how deletes work, else sorted as a
        program by its file or as a PowerShell command."""
        first = node.get("first") or {}
        if first.get("type") == "ScriptBlockExpressionAst":
            return
        if first.get("k") != "s" or not node.get("name"):
            self.add("hidden", "hidden", f"runs a command whose name is computed ({str(node.get('text'))[:60]}), "
                                         "which cannot be read first")
            return
        name, ctype, program = _named(node)
        if _defeats_dry_run(node):
            self.add("hidden", "hidden", f"{node.get('name')} is given -WhatIf or a preference that changes how it "
                                         "deletes")
            return
        if name in self.funcs:
            return
        if name in VARIABLE_CMDLETS and _bound(node, "Name") is not None and self.paths.strings(_bound(node, "Name")) is None:
            # A variable set by a computed name may be a preference that changes deletes, or any constant here.
            self.add("unknown", "unknown", f"{node.get('name')} sets a variable whose name is computed")
            return
        if name == "foreach-object":
            self.foreach(node)
            return
        if any(isinstance(a, dict) and a.get("sp") for a in _items(node.get("args"))):
            self.add("unknown", "unknown", f"passes {node.get('name')} its parameters from a variable (@splat)")
            return
        unbound = [str(k).lower() for k in _items(node.get("unbound"))]
        if name in FS_READERS and set(unbound) <= FS_SWITCHES:
            # The file system's own switches (-File, -Raw) on a reader; the binder knows them only for some paths.
            unbound = []
        if ctype not in ("Application", "ExternalScript") and unbound:
            # A provider parameter such as -Raw after the path leaves the command unbound.
            self.add("unknown", "unknown", f"PowerShell could not tell what every part of {node.get('name')} is for",
                     paths=self.literal_places(node), write=True)
            return
        if ctype in ("Application", "ExternalScript") or (not ctype and re.search(r"[\\/]|\.\w{2,4}$", name)):
            self.program(node, name, program or str(first.get("v") or ""), ctype)
        elif not ctype and os.path.splitext(name)[0] in KNOWN_PROGRAMS:
            # A known program missing here is still sorted by its name (wmic is gone from new Windows, not from all).
            self.program(node, name, str(first.get("v") or ""), ctype)
        elif not ctype:
            self.add("unknown", "unknown", f"runs {node.get('name')}, which PowerShell does not know here",
                     paths=self.literal_places(node), write=True)
        else:
            self.cmdlet(node, name)

    def foreach(self, node: dict) -> None:
        """ForEach-Object: script blocks are read where they stand; anything else names a member to call on every
        item."""
        for param in ("MemberName", "Process", "Begin", "End", "RemainingScripts"):
            el = _bound(node, param)
            for item in (_items(el.get("items")) if isinstance(el, dict) and el.get("k") == "a" else [el]):
                if item is not None and not (isinstance(item, dict) and item.get("type") == "ScriptBlockExpressionAst"):
                    self.member(item, str(node.get("text") or ""))

    def cmdlet(self, node: dict, name: str) -> None:
        """A command PowerShell knows (cmdlet, function, alias resolved): refused, harmless, or sorted by what its
        kind of command does."""
        if name in NEVER_CMDLETS:
            kind = NEVER_CMDLETS[name]
            self.add(kind, kind, f"runs {node.get('res', {}).get('n') or name}")
            return
        verb, _, noun = name.partition("-")
        if verb not in READ_VERBS and any(s in noun for s in SYSTEM_NOUNS) and name not in CHANGES:
            self.add("system", "system", f"runs {node['res'].get('n')}, which changes the system")
            return
        if name == "get-help" and _switch(node, "Online"):
            self.add("network", "browse", "opens the help page online in the browser", host="docs.microsoft.com")
            return
        if name in PURE:
            return
        sorting = self.sorting_for(name)
        if sorting is not None:
            sorting(node, name)
            return
        module = str((node.get("res") or {}).get("m") or "").lower()
        if verb in READ_VERBS and (module.startswith("microsoft.") or module in INBOX_MODULES):
            self.inbox_read(node)
            return
        self.add("unknown", "unknown", f"runs {node['res'].get('n') or name}, which the app does not know",
                 paths=self.literal_places(node), write=True)

    def sorting_for(self, name: str):
        """The method that sorts this kind of PowerShell command, or None; the first table holding it wins."""
        for names, sorting in ((LOCATIONS, self.location), (FACTS, self.facts), (READS, self.read_items),
                               (CHANGES, self.change), (("get-clipboard",), self.clipboard),
                               (NETWORK, self.network), (INSTALL, self.install),
                               (("start-process", "invoke-item"), self.start), (("stop-process",), self.stop),
                               (("new-object",), self.new_object), (("import-module",), self.import_module),
                               (("invoke-command",), self.invoke_command), (("set-item",), self.set_item)):
            if name in names:
                return sorting
        return None

    def read_items(self, node: dict, name: str) -> None:
        what, default_cwd = READS[name]
        paths, wild, unresolved, piped = self.files(node, READ_PARAMS, False, default_cwd)
        # Items from a recursive listing too large to list first are any file under it.
        recurse = _switch(node, "Recurse") or self.unlisted_recurse(node, piped)
        self.add("read", what, f"{what}s {_some(paths) or 'what comes down the pipeline'}", paths=paths,
                 wild=wild or piped, unresolved=unresolved, recurse=recurse)

    def clipboard(self, node: dict, name: str) -> None:
        self.add("outside", "clipboard", "reads what is on the clipboard")

    def install(self, node: dict, name: str) -> None:
        self.add("install", "install", f"runs {node['res'].get('n')}", name=str(node.get("text"))[:120])

    def stop(self, node: dict, name: str) -> None:
        self.add("program", "stop", "ends a running program", name=str(node.get("text"))[:120])

    def invoke_command(self, node: dict, name: str) -> None:
        if any(_bound(node, p) is not None for p in ("ComputerName", "Session", "FilePath", "ConnectionUri", "VMName")):
            self.add("system", "remote", "runs commands on another computer or from a file")

    def set_item(self, node: dict, name: str) -> None:
        paths, _, unresolved, _ = self.files(node, ("Path", "LiteralPath"), True)
        if paths or unresolved:
            self.add("unknown", "unknown", "sets an item", paths=paths, unresolved=unresolved, write=True)

    def inbox_read(self, node: dict) -> None:
        """A Get- or Test- command of a module that comes with Windows: it reads, unless aimed at another
        computer."""
        params = [p for p in (node.get("bound") or {}) if "path" in p.lower() or p.lower() in ("file", "filepath")]
        paths, wild, unresolved, _ = self.files(node, params, False)
        if _remote(node):
            self.add("system", "remote", f"runs {node['res'].get('n')} against another computer")
            return
        self.add("read", "info", f"runs {node['res'].get('n')}", paths=paths, wild=wild, unresolved=unresolved)

    def location(self, node: dict, name: str) -> None:
        if name == "pop-location":
            if self.paths.stack:
                self.paths.cwd, self.paths.where = self.paths.stack.pop()
            return
        el = _bound(node, "Path") or _bound(node, "LiteralPath")
        strings = self.paths.strings(el) if el is not None else [os.environ.get("USERPROFILE", "")]
        if not strings:
            self.add("unknown", "unknown", "moves to a folder whose name is computed")
            return
        provider, place = self.paths.place(strings[0])
        if name == "push-location":
            self.paths.stack.append((self.paths.cwd, self.paths.where))
        if provider != "file":
            self.provider(provider, place, False, node)
            self.paths.where = (provider, place)
            return
        self.paths.where = None
        self.paths.cwd = place
        self.add("read", "look", f"works in {place}", paths=[place])

    def facts(self, node: dict, name: str) -> None:
        if _remote(node):
            self.add("system", "remote", f"runs {node['res'].get('n')} against another computer")
            return
        what = FACTS[name]
        if name in ("get-ciminstance", "get-wmiobject", "get-cimclass"):
            cls = " ".join(self.paths.strings(_bound(node, "ClassName") or _bound(node, "Class")) or []).lower()
            query = " ".join(self.paths.strings(_bound(node, "Query") or _bound(node, "Filter")) or []).lower()
            what = "disk" if any(c in cls or c in query for c in DISK_CLASSES) else "info"
        self.add("read", what, f"reads {node['res'].get('n')}")

    def change(self, node: dict, name: str) -> None:
        """A command that changes files (CHANGES): made, deleted, written, or copied, moved and renamed."""
        what, sources, dest_param = CHANGES[name]
        if self.paths.where:
            self.add("system", "provider", f"runs {node.get('name')} inside the registry or another provider")
            return
        if name in ("new-item", "mkdir"):
            self.new_item(node, name)
            return
        paths, wild, unresolved, piped = self.files(node, sources, what != "zip")
        recurse = _switch(node, "Recurse")
        if what == "delete":
            # Remove-Item is run.BIN's function, which moves to the Recycle Bin; named with its module, the cmdlet.
            # Items a listing narrows (-Filter, -File) or a stage after it picks among are known only as it runs.
            upstream = self.pipes.get(node.get("pipe")) if piped else None
            narrowed = upstream is not None and (upstream.narrowed or int(node.get("index") or 0) > 1)
            self.add("delete", "skip_bin" if "\\" in str(node.get("name") or "") else "delete",
                     f"deletes {_some(paths) or 'what comes down the pipeline'}", paths=paths, write=True,
                     wild=wild or piped, recurse=recurse or self.unlisted_recurse(node, piped),
                     unresolved=unresolved or narrowed
                     or any(_bound(node, k) is not None for k in ("Include", "Exclude", "Filter")))
        elif what == "empty":
            self.add("overwrite", "empty", f"empties {_some(paths)}", paths=paths, write=True, wild=wild,
                     unresolved=unresolved)
        elif what in ("write", "append", "attr"):
            append = what == "append" or _switch(node, "Append")
            exists = any(os.path.isfile(p) for p in paths)
            kind = "overwrite" if exists and not append and not _switch(node, "NoClobber") and what != "attr" else "change"
            self.add(kind, "append" if append else what, f"{'appends to' if append else 'writes'} {_some(paths)}",
                     paths=paths, write=True, wild=wild, unresolved=unresolved or (piped and what == "attr"))
        else:
            self.relocate(node, what, dest_param, paths, wild, unresolved, piped, recurse)

    def new_item(self, node: dict, name: str) -> None:
        typed = self.paths.strings(_bound(node, "ItemType")) if _bound(node, "ItemType") is not None else [""]
        item_type = _item_type(" ".join(typed or []) if typed is not None else None, name)
        if item_type in ("link", "unknown"):
            self.add("system", "link", "makes a link (or an item of a computed type), which can make a folder "
                                       "reach places outside it")
            return
        paths, _, unresolved, _ = self.files(node, ("Path",), True, default_cwd=True)
        names = self.paths.strings(_bound(node, "Name")) if _bound(node, "Name") is not None else None
        if _bound(node, "Name") is not None and names is None:
            unresolved = True
        if names:
            paths = [os.path.join(p, n) for p in paths for n in names]
        exists = any(os.path.exists(p) for p in paths)
        force = _switch(node, "Force")
        self.add("overwrite" if exists and force and not item_type.startswith("dir") else "change",
                 "mkdir" if item_type.startswith("dir") else "newfile", f"creates {', '.join(paths)}",
                 paths=paths, write=True, unresolved=unresolved)

    def relocate(self, node: dict, what: str, dest_param: str, paths: list[str], wild: bool, unresolved: bool,
                 piped: bool, recurse: bool) -> None:
        """Copied, moved, renamed, zipped or unzipped to a destination, which may replace what is there."""
        got = self.destination(node, dest_param, paths)
        if got is None:
            return
        dest, dest_unresolved = got
        overwrite = bool(dest) and not wild and not unresolved and not piped and _replaces(
            what, paths, dest, _switch(node, "Force"), recurse)
        self.add("overwrite" if overwrite else "change", what,
                 f"{VERBED.get(what, what + 's')} {_some(paths) or 'items'} to {dest or '?'}",
                 paths=paths, dest=dest, write=what in ("move", "rename"), wild=wild or piped,
                 unresolved=unresolved or dest_unresolved, recurse=recurse,
                 dest_unresolved=dest_unresolved and not unresolved)

    def destination(self, node: dict, dest_param: str, paths: list[str]) -> tuple[str, bool] | None:
        """(where the items go, whether that is computed); None when it is another provider's place, sorted
        on the spot."""
        if dest_param == "NewName":
            names = self.paths.strings(_bound(node, "NewName"))
            if names is None or len(names) != 1:
                return "", True
            return os.path.join(os.path.dirname(paths[0]) if len(paths) == 1 else self.paths.cwd, names[0]), False
        el = _bound(node, dest_param)
        if el is None:
            return self.paths.cwd, False
        strings = self.paths.strings(el)
        if strings is None or len(strings) != 1:
            return "", True
        provider, dest = self.paths.place(strings[0])
        if provider != "file":
            self.provider(provider, dest, True, node)
            return None
        return dest, False

    def network(self, node: dict, name: str) -> None:
        targets = self.paths.strings(_bound(node, NETWORK[name]))
        target = " ".join(targets or [])
        host = (urlsplit(target).hostname or target.split("/")[0]).lower() if target else ""
        if target and _local_host(host):
            self.loopback(host)
            return
        method = " ".join(self.paths.strings(_bound(node, "Method")) or ["get"]).lower()
        # A computed address, headers or sign-in can carry anything out.
        sends = (name == "send-mailmessage" or method not in ("get", "head", "default") or targets is None
                 or any(_bound(node, p) is not None for p in ("Body", "InFile", "Form", "Headers", "UserAgent",
                                                              "Credential", "UseDefaultCredentials", "WebSession",
                                                              "Certificate", "Proxy"))
                 or "?" in target)
        out = []
        if _bound(node, "OutFile") is not None or _bound(node, "Destination") is not None:
            out, _, unresolved, _ = self.files(node, ("OutFile", "Destination"), True)
            if unresolved:
                self.add("unknown", "write", "saves a download under a computed name", unresolved=True, write=True)
        if _bound(node, "InFile") is not None:
            files, _, _, _ = self.files(node, ("InFile",), False)
            self.add("read", "read", "reads a file to send", paths=files)
        self.add("network", "net", f"reaches {host or 'the network'}" + (" and sends data" if sends else ""),
                 host=host or "?", sends=sends, paths=out, write=bool(out))

    def import_module(self, node: dict, name: str) -> None:
        modules = self.paths.strings(_bound(node, "Name"))
        if modules is None:
            self.add("hidden", "hidden", "loads a module whose name is computed")
            return
        for module in modules:
            if re.search(r"[\\/]|\.ps[md]?1$|\.dll$", module, re.IGNORECASE):
                self.add("program", "script", f"loads the module file {module}", name=module)
            elif module.lower() not in INBOX_MODULES and not module.lower().startswith("microsoft."):
                self.add("program", "script", f"loads the module {module}, whose code cannot be read first", name=module)


def _defeats_dry_run(node: dict) -> bool:
    """-WhatIf, or a parameter or value naming a preference that changes how deletes and confirmations work."""
    args = [a for a in _items(node.get("args")) if isinstance(a, dict)]
    switches = [str(a.get("v") or "").lower() for a in args if a.get("k") == "p"]
    return (any(DRY_DEFEATERS.search(k) for k in (node.get("bound") or {}))
            or any(DRY_DEFEATERS.search(str(a.get("v") or "")) for a in args)
            or any(p == "wi" or (len(p) >= 2 and "whatif".startswith(p)) for p in switches))


def _item_type(typed: str | None, name: str) -> str:
    """New-Item's -ItemType as PowerShell matches it (any leading part: "J" is a junction); "unknown" when
    computed."""
    if typed is None:
        return "unknown"
    typed = typed.strip().lower()
    if not typed:
        return "file" if name == "new-item" else "dir"
    for full, kind in (("directory", "dir"), ("container", "dir"), ("file", "file"), ("symboliclink", "link"),
                       ("junction", "link"), ("hardlink", "link")):
        if full.startswith(typed):
            return kind
    return "unknown"


def _replaces(what: str, paths: list[str], dest: str, force: bool, recurse: bool) -> bool:
    """Copying, moving, renaming, zipping or unzipping `paths` to `dest` would replace a file already there."""
    for src in paths:
        if what == "unzip":
            if force and _unzip_overwrites(src, dest):
                return True
            continue
        target = os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) and what != "rename" else dest
        replaces = os.path.isfile(target) and os.path.normcase(target) != os.path.normcase(src) and (
            what == "copy" or force or what == "zip")
        # A folder copied with -Recurse replaces any file of the same name already there.
        merges = what == "copy" and os.path.isdir(src) and recurse and _copy_overwrites(src, target)
        if replaces or merges:
            return True
    return False
