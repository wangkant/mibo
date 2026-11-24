"""Reading a bash command before it runs, and sorting what it would do (macOS and Linux).

tree-sitter-bash parses it, the grammar other coding agents read bash with. Every command at any depth is sorted
into the acts of acts.py: lists, pipelines, subshells, loops, function bodies, command and process substitutions,
here-documents, `bash -c '...'` and what `find -exec` and `xargs` run. Paths are made absolute with `~`, $HOME,
`..` and the folder each `cd` reaches; a name, path or code computed only as it runs is unresolved. The tables
are pstables.py's, with the POSIX commands and places beside them in bashtables.py; bashfiles.py and
bashprograms.py sort the kinds of command. Whatever the grammar or the tables do not know is "unknown", and a
command that does not parse comes back with errors: neither runs without the person's press. `read.judge` then
holds the acts against the grants as it does for PowerShell.

The app does not call it yet: the shell tool reads every command with read.py, on every system. The tests and
tools/xplat/bashjudge_check.py hold it to the labelled bash corpus.
"""
from __future__ import annotations

import fnmatch
import glob as globlib
import os
import posixpath
import re

from .acts import COMMAND_MAX, NEVER_KINDS, Act, Reading, download_run
from .bashfiles import Files
from .bashprograms import Programs
from .bashtables import (
    ARCHIVERS,
    BIN_DIRS,
    BRACES,
    DANGEROUS_VARS,
    FACTS,
    INSTALL,
    INTERPRETERS_POSIX,
    NETWORK,
    NEVER,
    NOT_FILES,
    OTHER_SHELLS,
    OWN_TOPS,
    PIPE,
    PROGRAMS,
    PURE,
    READS,
    SEARCHERS,
    SECRET_PATTERNS,
    SECRET_PLACES,
    SHELLS,
    SYSTEM_PLACES,
    SYSTEM_READ,
    TEMP_PLACES,
    WRAPPERS,
)
from .bashwords import Word, _descendants, _numeric, _short, _text, _texts, _tree
from .code import scripts
from .grants import SECRET_NAMES, SECRET_SUFFIXES
from .paths import _local_host


def _reaches(p: list[str], root: list[str], deep: bool) -> bool:
    """A wildcard path, split into its parts, matches `root` or something inside it (or, with `deep`, a folder
    above it)."""
    n = min(len(p), len(root))
    if not all(fnmatch.fnmatchcase(root[i], p[i]) for i in range(n)):
        return False
    return len(p) >= len(root) or deep


def _under(path: str, root: str) -> bool:
    """`path` is `root` or inside it."""
    return path == root or path.startswith(root.rstrip("/") + "/")


# Nodes whose variables are set apart from the rest of the command: loops, functions and subshells.
APART = ("for_statement", "c_style_for_statement", "while_statement", "function_definition", "subshell",
         "command_substitution", "process_substitution")
# Commands that set the variables they name.
SETS_BY_NAME = ("read", "mapfile", "readarray", "getopts", "printf", "declare", "local", "export")
# The nodes of a statement that are words, not commands: what runs inside them is sorted by nested().
WORD_NODES = ("word", "string", "raw_string", "concatenation", "simple_expansion", "expansion", "number",
              "extglob_pattern", "variable_name", "command_substitution", "arithmetic_expansion", "ansi_c_string",
              "regex", "brace_expression", "process_substitution")
# Statements that hold others, sorted one by one.
BLOCKS = ("program", "list", "compound_statement", "subshell", "do_group", "negated_command", "if_statement",
          "elif_clause", "else_clause", "while_statement", "for_statement", "case_statement", "case_item")
# Those of them whose body may run or not, or more than once.
BRANCHES = ("if_statement", "elif_clause", "else_clause", "case_statement", "case_item", "while_statement",
            "for_statement")


class Sorter(Files, Programs):
    """Sorts one bash command into acts (`acts`), following the folder each `cd` reaches and the variables set."""

    def __init__(self, cwd: str | None, home: str, depth: int = 0):
        self.cwd = posixpath.normpath(cwd) if cwd else None
        self.home = posixpath.normpath(home)
        self.depth = depth
        self.acts: list[Act] = []
        self.consts: dict[str, str] = {}
        # Variables that may hold something other than a number written in the command: arithmetic on them can
        # run code written in their value.
        self.unsafe: set[str] = set()
        # Variables assigned once, outside loops, functions and subshells: their value is known where it is set.
        self.once: set[str] = set()
        self.stack: list[str | None] = []
        # Functions defined at the top level before this point: a call runs the body, sorted where it stands.
        self.funcs: set[str] = set()

    # ------------------------------------------------------------ before sorting

    def survey(self, root) -> None:
        """Before sorting: which variables are set once, outside loops, functions and subshells (`once`), and which
        may hold something other than a number (`unsafe`)."""
        counts: dict[str, int] = {}
        self._survey(root, False, counts)
        self.once = {name for name, n in counts.items() if n == 1}

    def _survey(self, node, apart: bool, counts: dict[str, int]) -> None:
        """survey() of `node` and all under it, in the order they stand; `apart`: inside a loop, function or
        subshell. A variable set more than once counts 2."""
        kind = node.type
        inside = apart or kind in APART or (kind == "pipeline" and node.named_child_count > 1)
        name = node.child_by_field_name("variable" if kind == "for_statement" else "name")
        if kind == "variable_assignment" and name is not None:
            prefix = node.parent is not None and node.parent.type == "command"
            counts[_text(name)] = counts.get(_text(name), 0) + (2 if inside or prefix else 1)
            value = node.child_by_field_name("value")
            if value is None or not _numeric(value):
                self.unsafe.add(_text(name))
        elif kind == "for_statement" and name is not None:
            values = node.children_by_field_name("value")
            counts[_text(name)] = 2
            if not values or not all(_numeric(v) for v in values):
                self.unsafe.add(_text(name))
        elif kind == "command" and name is not None and _text(name) in SETS_BY_NAME:
            for text in (_text(w) for w in node.children_by_field_name("argument")):
                if re.fullmatch(r"[A-Za-z_]\w*", text):
                    self.unsafe.add(text)
                    counts[text] = 2
        for child in node.children:
            self._survey(child, inside, counts)

    # ------------------------------------------------------------ acts

    def add(self, kind: str, what: str, why: str, **more) -> Act:
        act = Act(kind, what, why, **more)
        if act.wild and kind not in NEVER_KINDS:
            content = what in ("read", "search", "zip", "copy") or act.write or kind in ("change", "overwrite", "delete")
            for glob in act.globs:
                refused = self.blocked_glob(glob, act.write or kind in ("change", "overwrite", "delete"),
                                            content and act.recurse, content)
                if refused:
                    act = Act(refused, refused, f"{why}, whose pattern {glob} reaches a protected place",
                              paths=[glob])
                    break
        self.acts.append(act)
        return act

    def blocked_glob(self, pattern: str, write: bool, deep: bool, content: bool) -> str:
        """Why a wildcard may never be used ("secrets", "system"), or "": what it could match is held against the
        protected places, as read.py does for PowerShell, and what it matches now is checked one by one."""
        p = [c for c in pattern.split("/") if c]
        home = [c for c in self.home.split("/") if c]
        if len(p) > len(home) and _reaches(p, home, False):
            entry = p[len(home)]
            inside = len(p) > len(home) + 1
            if (entry.startswith((".", "[")) and (inside or content)) or (
                    fnmatch.fnmatchcase("Library", entry) and (inside or deep)):
                return "secrets"
        if len(p) >= 3 and p[0] == "proc" and (len(p) > 3 or content) and any(
                fnmatch.fnmatchcase(x, p[2]) for x in ("environ", "mem", "maps", "cmdline", "root", "cwd", "fd")):
            return "secrets"
        for root in SECRET_PLACES:
            if _reaches(p, [c for c in root.split("/") if c], deep):
                return "secrets"
        if deep and len(p) <= len(home) and _reaches(p, home, True):
            return "secrets"
        if write and not any(_under(re.split(r"[*?\[]", pattern)[0], t) for t in TEMP_PLACES):
            for root in SYSTEM_PLACES:
                if _reaches(p, [c for c in root.split("/") if c], False):
                    return "system"
        for place in globlib.glob(pattern)[:5000]:
            refused = self.blocked_place(place, write, deep)
            if refused:
                return refused
        return ""

    def resolve(self, text: str) -> str | None:
        """The absolute place a path names, or None when the folder it is relative to is not known."""
        if not text.startswith("/"):
            if self.cwd is None:
                return None
            text = posixpath.join(self.cwd, text)
        return "/" + posixpath.normpath(text).lstrip("/")

    def blocked(self, path: str, write: bool, deep: bool = False) -> str:
        """Why a command may never touch this place ("secrets", "system"), or "". `deep`: everything under it is
        read or changed, so a protected place inside counts too."""
        if re.search(r"[*?\[]", path):
            return self.blocked_glob(path, write, deep, True)
        return self.blocked_place(path, write, deep)

    def blocked_place(self, path: str, write: bool, deep: bool) -> str:
        if NOT_FILES.match(path):
            # /dev/null, /dev/stdout and a pipe's /dev/fd/N (on Linux links into /proc/self/fd) hold no file.
            return ""
        for place in dict.fromkeys((path, posixpath.realpath(path))):
            name = posixpath.basename(place).lower()
            if (name in SECRET_NAMES or name.startswith((".env", "id_rsa", "id_ed25519", "id_ecdsa"))
                    or name.endswith(SECRET_SUFFIXES)):
                return "secrets"
            if _under(place, self.home) and place != self.home:
                rest = place[len(self.home):].lstrip("/")
                if rest.startswith((".", "Library/")) or rest == "Library":
                    return "secrets"
            if any(_under(place, s) for s in SECRET_PLACES) or SECRET_PATTERNS.match(place):
                return "secrets"
            if _under(place, "/dev") and not NOT_FILES.match(place) and not place.startswith(("/dev/shm", "/dev/fd")):
                return "system"
            if deep and (_under(self.home, place) or any(_under(s, place) for s in SECRET_PLACES)):
                return "secrets"
            if write and not any(_under(place, t) for t in TEMP_PLACES) and (
                    any(_under(place, s) for s in SYSTEM_PLACES) or place == "/"
                    or (posixpath.dirname(place) == "/" and place not in OWN_TOPS)):
                return "system"
        return ""

    def touch(self, kind: str, what: str, why: str, paths: list[str], write: bool = False, recurse: bool = False,
              **more) -> Act:
        """An act on these places, or a never act when one of them is protected."""
        content = what in ("read", "search", "zip", "copy") or write
        for path in paths:
            refused = self.blocked(path, write, deep=recurse and content)
            if refused:
                reach = "" if why.endswith(path) else f", which reaches {path}"
                return self.add(refused, refused, f"{why}{reach}, which is protected", paths=[path])
        return self.add(kind, what, why, paths=paths, write=write, recurse=recurse, **more)

    # ------------------------------------------------------------ words

    def word(self, node) -> Word | None:
        """What one argument stands for after quotes and expansions, or None when it is computed as it runs."""
        kind = node.type
        if kind == "word":
            raw = _text(node)
            if BRACES.search(raw):
                return None
            wild = bool(re.search(r"(?<!\\)[*?\[]", raw))
            if raw.startswith("~"):
                head = raw.partition("/")[0]
                if head != "~":
                    return None
                raw = self.home + raw[1:]
            return Word(re.sub(r"\\(.)", r"\1", raw), wild)
        if kind == "number":
            return Word(_text(node))
        if kind == "raw_string":
            return Word(_text(node)[1:-1])
        if kind == "ansi_c_string":
            body = _text(node)[2:-1]
            return None if "\\" in body else Word(body)
        if kind in ("string", "translated_string"):
            return self.quoted(node)
        if kind in ("simple_expansion", "expansion"):
            names = [c for c in node.named_children if c.type == "variable_name"]
            plain = all(c.is_named or c.type in ("$", "${", "}") for c in node.children)
            if len(node.named_children) != 1 or not names or not plain:
                return None
            value = self.variable(_text(names[0]))
            quoted = node.parent is not None and node.parent.type == "string"
            if value is None or (not quoted and re.search(r"\s", value)):
                return None
            return Word(value, not quoted and bool(re.search(r"[*?\[]", value)))
        if kind == "concatenation":
            if BRACES.search(_text(node)):
                return None
            parts = [self.word(c) for c in node.named_children]
            if any(p is None for p in parts):
                return None
            return Word("".join(p.text for p in parts), any(p.wild for p in parts))
        if kind == "process_substitution":
            # <(...) and >(...) stand for a pipe the shell names under /dev/fd; what runs inside is sorted by nested.
            return Word(PIPE)
        return None

    def quoted(self, node) -> Word | None:
        """A double-quoted string: its text with escapes undone and expansions put in, never a pattern."""
        out = ""
        for child in node.named_children:
            if child.type == "string_content":
                out += re.sub(r"\\([$`\"\\\n])", r"\1", _text(child))
                continue
            got = self.word(child)
            if got is None:
                return None
            out += got.text
        return Word(out)

    def variable(self, name: str) -> str | None:
        if name in self.consts:
            return self.consts[name]
        if name == "HOME":
            return self.home
        if name == "PWD":
            return self.cwd
        return None

    def nested(self, node) -> None:
        """Commands run inside an argument (command and process substitution, here-document bodies), and
        arithmetic that evaluates a variable which may hold code."""
        stack = [node]
        while stack:
            item = stack.pop()
            if item.type in ("command_substitution", "process_substitution"):
                saved = self.cwd
                for child in item.named_children:
                    self.statement(child)
                self.cwd = saved
                continue
            if item.type in ("arithmetic_expansion", "subscript"):
                self.arithmetic(item)
            stack.extend(item.children)

    def arithmetic(self, node) -> None:
        names = set()
        stack = [node]
        while stack:
            item = stack.pop()
            if item.type == "variable_name" or (item.type == "word" and re.fullmatch(r"[A-Za-z_]\w*", _text(item))):
                names.add(_text(item))
            stack.extend(item.children)
        for name in sorted(names & self.unsafe)[:1]:
            self.add("hidden", "hidden", f"evaluates ${name} as arithmetic, which runs any command written in it")

    # ------------------------------------------------------------ statements

    def statement(self, node, upstream: list[Act] | None = None) -> None:
        """One statement and all it holds; `upstream`: the acts of the pipeline stages before it."""
        kind = node.type
        if kind == "&":
            self.add("hidden", "hidden", "leaves a command running in the background, out of sight")
        elif kind == "command":
            self.command(node, upstream, [])
        elif kind == "redirected_statement":
            self.redirected(node, upstream)
        elif kind == "pipeline":
            saved, before = self.cwd, len(self.acts)
            stages = node.named_children
            for n, stage in enumerate(stages):
                self.statement(stage, self.acts[before:] if n else upstream)
                if len(stages) > 1:
                    self.cwd = saved
        elif kind in ("variable_assignment", "variable_assignments"):
            for one in ([node] if kind == "variable_assignment" else node.named_children):
                self.assign(one, keep=True)
        elif kind == "declaration_command":
            self.declaration(node)
        elif kind == "unset_command":
            for child in node.named_children:
                self.consts.pop(_text(child), None)
        elif kind == "function_definition":
            self.function(node)
        elif kind == "test_command":
            self.nested(node)
            if node.children and node.children[0].type == "[[" and re.search(r"\s-(eq|ne|lt|le|gt|ge)\s",
                                                                             _text(node)):
                self.arithmetic(node)
        elif kind == "compound_statement" and node.children and node.children[0].type == "((":
            self.nested(node)
            self.arithmetic(node)
        elif kind == "c_style_for_statement":
            for child in node.named_children:
                if child.type in ("do_group", "compound_statement"):
                    self.statement(child)
                else:
                    self.nested(child)
        elif kind in BLOCKS:
            self.block(node)
        elif kind in ("file_redirect", "heredoc_redirect", "herestring_redirect"):
            self.redirect(node, {"kind": "", "text": None, "start": len(self.acts)})
        elif kind != "comment":
            self.add("unknown", "unknown", f"uses {kind.replace('_', ' ')}, which the app does not read")

    def redirected(self, node, upstream: list[Act] | None) -> None:
        """A statement with redirections: a command takes them as its own, anything else has them after it."""
        body = node.child_by_field_name("body")
        rest = [c for c in node.named_children if c != body]
        if body is not None and body.type == "command":
            self.command(body, upstream, rest)
            return
        if body is not None:
            self.statement(body, upstream)
        for redirect in rest:
            self.redirect(redirect, {"kind": "", "text": None, "start": len(self.acts)})

    def function(self, node) -> None:
        """A function's body is sorted where it stands; a call of one defined at the top level runs nothing new."""
        name = node.child_by_field_name("name")
        if name is not None and _text(name) in ("command_not_found_handle", "command_not_found_handler"):
            self.add("hidden", "hidden", "defines what runs for every unknown command")
        if name is not None and node.parent is not None and node.parent.type == "program":
            self.funcs.add(_text(name))
        saved = self.cwd
        body = node.child_by_field_name("body")
        if body is not None:
            self.statement(body)
        if self.cwd != saved:
            # Where a call of it leaves the command is known only as it runs.
            self.cwd = None

    def block(self, node) -> None:
        """A statement that holds others (BLOCKS), each sorted in turn, and the folder it leaves the command in."""
        kind = node.type
        saved = self.cwd
        either = kind == "list" and any(c.type == "||" for c in node.children)
        if kind in ("while_statement", "for_statement") and any(
                c.type == "command_name" and _text(c) in ("cd", "pushd", "popd") for c in _descendants(node)):
            # A loop that changes folder runs its next pass from wherever the last one ended.
            self.cwd = None
        for child in node.children:
            before = self.cwd
            if child.type in WORD_NODES:
                self.nested(child)
            elif child.is_named or child.type == "&":
                self.statement(child)
            # A cd that may fail leaves what follows in either folder; only `cd x && ...` is sure of x.
            if (self.cwd not in (before, None) and kind != "list" and not os.path.isdir(self.cwd)) or (
                    either and self.cwd != before):
                self.cwd = None
        if kind == "subshell":
            self.cwd = saved
        elif kind in BRANCHES and self.cwd != saved:
            self.cwd = None

    def assign(self, node, keep: bool) -> None:
        """One NAME=value: its value's own commands; a variable that changes what runs is hidden."""
        name_node, value = node.child_by_field_name("name"), node.child_by_field_name("value")
        name = _text(name_node) if name_node is not None else ""
        if value is not None:
            self.nested(value)
        if DANGEROUS_VARS.match(name) and not (name == "IFS" and not keep):
            self.add("hidden", "redefine", f"sets {name}, which changes what later commands run or load")
            return
        got = self.word(value) if keep and value is not None and name in self.once else None
        if got is not None:
            self.consts[name] = got.text
        else:
            self.consts.pop(name, None)

    def declaration(self, node) -> None:
        flags = "".join(_text(c)[1:] for c in node.children if c.type == "word" and _text(c).startswith("-"))
        if node.children and node.children[0].type == "export" and "f" in flags:
            self.add("hidden", "redefine", "exports a function to every program it starts")
        if "n" in flags:
            self.add("hidden", "redefine", "makes one variable's name stand for another's")
        for child in node.named_children:
            if child.type == "variable_assignment":
                self.assign(child, keep=True)
            elif child.type == "variable_name" and DANGEROUS_VARS.match(_text(child)):
                self.add("hidden", "redefine", f"exports {_text(child)}, which changes what later commands run")
            else:
                self.nested(child)

    # ------------------------------------------------------------ redirections

    def redirect(self, node, stdin: dict) -> None:
        """One redirection: a file written or read, a connection opened, or what a command reads on its input
        (here-document, here-string, file), noted in `stdin`."""
        if node.type == "herestring_redirect":
            for child in node.named_children:
                self.nested(child)
                got = self.word(child)
                stdin.update(kind="text", text=got.text if got is not None else None)
            return
        if node.type == "heredoc_redirect":
            start = next((c for c in node.named_children if c.type == "heredoc_start"), None)
            quoted = start is not None and bool(re.search(r"[\"'\\]", _text(start)))
            body = next((c for c in node.named_children if c.type == "heredoc_body"), None)
            expands = body is not None and any(c.type != "heredoc_content" for c in body.named_children)
            if body is not None and not quoted:
                self.nested(body)
            stdin.update(kind="text", text=None if expands and not quoted else (_text(body) if body else ""))
            for child in node.named_children:
                if child.type in ("file_redirect", "herestring_redirect"):
                    self.redirect(child, stdin)
                elif child.type not in ("heredoc_start", "heredoc_body", "heredoc_end"):
                    # The rest of a pipeline the here-document's command starts (cat <<EOF | sh).
                    self.statement(child, self.acts[stdin["start"]:])
            return
        op = next((_text(c) for c in node.children if not c.is_named), "")
        dest = node.child_by_field_name("destination") or (node.named_children[-1] if node.named_children else None)
        if dest is None or dest.type == "file_descriptor" or op in ("<&-", ">&-"):
            return
        self.nested(dest)
        if dest.type == "process_substitution" or (dest.type == "number" and op in (">&", "<&")):
            return
        got = self.word(dest)
        reading = op in ("<", "<&")
        if got is None or got.wild:
            if reading:
                self.add("read", "read", "reads a file whose name is computed", unresolved=True)
            else:
                self.add("unknown", "write", "writes its output to a file whose name is computed", unresolved=True,
                         write=True)
            return
        if reading:
            stdin.update(kind="file", text=None)
        if NOT_FILES.match(got.text):
            return
        net = re.match(r"^/dev/(tcp|udp)/([^/]+)/(\d+)", got.text)
        if net:
            self.reach(net.group(2), True, f"opens a connection to {net.group(2)} through /dev/{net.group(1)}")
            return
        place = self.resolve(got.text)
        if place is None:
            self.add("unknown", "write", f"uses {got.text} in a folder known only as it runs", unresolved=True,
                     write=not reading)
        elif reading:
            self.touch("read", "read", f"reads {place}", [place], globs=[place])
        else:
            append = ">>" in op
            self.touch("overwrite" if os.path.isfile(place) and not append else "change",
                       "append" if append else "write", f"{'appends' if append else 'writes'} its output to {place}",
                       [place], write=True)

    def reach(self, host: str, sends: bool, why: str, **more) -> None:
        host = host.lower().strip("[]")
        if host and host != "?" and _local_host(host):
            self.add("system", "loopback", f"reaches this computer's own services at {host}")
            return
        self.add("network", "net", why, host=host or "?", sends=sends, **more)

    # ------------------------------------------------------------ one command

    def command(self, node, upstream: list[Act] | None, redirects: list) -> None:
        stdin = {"kind": "pipe" if upstream is not None else "", "text": None, "start": len(self.acts)}
        name_node = node.child_by_field_name("name")
        words: list[Word | None] = []
        for child in node.named_children:
            if child.type == "variable_assignment":
                self.assign(child, keep=False)
            elif child.type in ("file_redirect", "heredoc_redirect", "herestring_redirect"):
                redirects = [*redirects, child]
            elif child != name_node:
                self.nested(child)
                words.append(self.word(child))
        for redirect in redirects:
            self.redirect(redirect, stdin)
        if name_node is None:
            return
        self.nested(name_node)
        head = name_node.named_children[0] if name_node.named_children else None
        named = self.word(head) if head is not None else None
        # A name pieced together from quotes or set by a variable in the command hides what runs, as read.py
        # takes `& $c`; only $HOME and $PWD, which the command does not set, may stand in a program's path.
        pieced = head is not None and head.type == "concatenation" and any(
            c.type in ("string", "raw_string", "ansi_c_string") for c in head.named_children)
        named_by = [_text(c) for c in _descendants(head) if c.type == "variable_name"] if head is not None else []
        if named is None or named.wild or pieced or any(n not in ("HOME", "PWD") or n in self.consts
                                                         for n in named_by):
            self.add("hidden", "hidden", f"runs a command whose name is computed ({_text(name_node)[:60]}), "
                                         "which cannot be read first")
            return
        if named.text in self.funcs:
            return
        self.run(named.text, words, upstream or [], stdin)

    def args(self, words: list[Word | None], values: str = "", files: str = "") -> tuple[list, list]:
        """(flags, positional words) of a command's arguments. A short option in `values` takes the next word,
        which is not positional, unless the option is in `files` (grep -f FILE): then that word is a file read."""
        flags, positional, take, ended = [], [], "", False
        for word in words:
            if take:
                if take in files:
                    positional.append(word)
                take = ""
                continue
            if word is None:
                positional.append(None)
                continue
            text = word.text
            if not ended and text == "--":
                ended = True
            elif not ended and text.startswith("-") and len(text) > 1:
                flags.append(text)
                if re.fullmatch(r"-[A-Za-z0-9]+", text) and text[-1] in values:
                    take = text[-1]
                else:
                    positional += self.joined_place(text)
            else:
                positional.append(word)
        return flags, positional

    def joined_place(self, option: str) -> list[Word]:
        """A value given in the same word as its option (--file=x, -f/x), when it may be a place."""
        if not ("=" in option or option[2:3] in ("/", "~", ".")):
            return []
        value = option.split("=", 1)[1] if "=" in option else option[2:]
        if not value.startswith(("/", "~/", "./", "../")):
            return []
        return [Word(self.home + value[1:] if value.startswith("~/") else value)]

    def places(self, words: list) -> tuple[list[str], list[str], bool, bool]:
        """(absolute places, the patterns among them, any pattern, any computed) of positional words. A pattern's
        place is the folder before its first wildcard."""
        out, globs, wild, unresolved = [], [], False, False
        for word in words:
            place = self.resolve(word.text) if word is not None else None
            if place is None:
                unresolved = True
                continue
            if word.wild:
                wild = True
                globs.append(place)
                base = re.split(r"[*?\[]", place)[0]
                place = (base if base.endswith("/") else posixpath.dirname(base)).rstrip("/") or "/"
            out.append(place)
        return out, globs, wild, unresolved

    def run(self, name: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        """Sorts one command by its name, with its arguments as they will be after expansion: first what decides
        what else runs (the never list, a program's own file, wrappers, shells, interpreters), then tool()."""
        folder, base = posixpath.split(name)
        low = base.lower()
        texts = _texts(words)
        never = NEVER.get(low) or NEVER.get(low.split(".")[0])
        if never:
            self.add(never, never, f"runs {base}")
        elif folder and posixpath.normpath(folder) not in BIN_DIRS:
            self.program(name, words)
        elif low in WRAPPERS:
            self.wrapper(low, words, upstream, stdin)
        elif low in ("alias", "trap"):
            if (low == "alias" and any(t is None or "=" in t for t in texts)) or (
                    low == "trap" and len(texts) >= 2 and texts[0] not in ("-", "-p", "-l")):
                self.add("hidden", "redefine", f"{base} makes later words run something else")
        elif low in ("source", "."):
            self.source(texts)
        elif low in ("cd", "pushd", "popd"):
            self.location(low, texts)
        elif low in SHELLS:
            self.shell(base, words, upstream, stdin)
        elif low in OTHER_SHELLS:
            self.add("hidden", "hidden", f"runs {base}, whose commands this app does not read")
        elif re.fullmatch(r"(python|pypy)[\d.]*w?", low) or low in INTERPRETERS_POSIX:
            self.interpreter("python" if low.startswith(("python", "pypy")) else low, words, upstream, stdin)
        elif low not in PURE:
            self.tool(low, base, words, texts)

    def tool(self, low: str, base: str, words: list[Word | None], texts: list[str | None]) -> None:
        """A command sorted by what its kind of tool does: reads, file changes, the network, installs."""
        if low in FACTS:
            self.facts(low, texts)
        elif low in SYSTEM_READ:
            self.system_tool(low, texts)
        elif low in READS or low in SEARCHERS:
            self.reads(low, words)
        elif low in ("sed", "gsed"):
            self.sed(words)
        elif low in ("awk", "gawk", "mawk", "nawk"):
            self.awk(words)
        elif low == "find":
            self.find(words)
        elif low == "xargs":
            self.xargs(words)
        elif low in ("cp", "mv", "install", "ditto", "rsync"):
            self.copy(low, words)
        elif low in ("rm", "unlink", "rmdir", "shred", "srm", "trash", "trash-put"):
            self.delete(low, words)
        elif low in ("mkdir", "touch", "truncate", "tee", "chmod", "dd", "mktemp", "split", "csplit", "patch"):
            self.change(low, words)
        elif low in ARCHIVERS:
            self.archive(low, words)
        elif low in NETWORK:
            self.network(low, words)
        elif low == "git":
            self.git(texts)
        elif low in ("open", "xdg-open", "gio", "gnome-open", "kde-open", "kde-open5", "wslview"):
            self.open(low, texts)
        elif low in ("kill", "pkill", "killall", "xkill", "skill"):
            self.add("program", "stop", f"ends a running program ({_short(texts)[:60]})",
                     name=f"{base} {_short(texts)}")
        elif low in ("pbpaste", "wl-paste", "xclip", "xsel"):
            if low in ("pbpaste", "wl-paste") or any(t in ("-o", "--output", "-out") for t in texts):
                self.add("outside", "clipboard", "reads what is on the clipboard")
        elif low in ("docker", "podman", "nerdctl", "kubectl", "lima", "colima", "vagrant"):
            self.container(base, texts)
        elif low in INSTALL or low in ("npx", "pnpx", "bunx", "uvx"):
            self.install(low, texts)
        elif low in PROGRAMS:
            if self.named_places(base, words) is not None:
                self.add("program", "program", f"runs {base} {_short(texts)[:80]}".strip(),
                         name=f"{base} {_short(texts)}", args=[t or "?" for t in texts])
        else:
            self.unknown(base, words)


def read(command: str, cwd: str, home: str | None = None) -> Reading:
    """Reads and sorts one bash command to be run in `cwd`; `home` is the person's home folder, which `~` and
    $HOME name. A command that does not parse comes back with errors."""
    if len(command) > COMMAND_MAX:
        return Reading(command, cwd, [], [f"the command is longer than {COMMAND_MAX} characters"])
    root = _tree(command)
    if root.has_error:
        stack, bad = [root], None
        while stack and bad is None:
            item = stack.pop()
            bad = item if item.is_error or item.is_missing else None
            stack.extend(reversed(item.children))
        near = command[bad.start_byte:bad.start_byte + 40] if bad is not None else command[:40]
        return Reading(command, cwd, [], [f"bash could not parse the command near {near!r}"])
    sorter = Sorter(cwd, home or os.path.expanduser("~"))
    sorter.survey(root)
    sorter.statement(root)
    acts = sorter.acts
    acts += scripts(acts) + download_run(acts)
    return Reading(command, cwd, acts, [])


def gist(reading: Reading) -> str:
    """What a reading comes to, as one word: "never", "ask", "delete", "network", "write" or "read"."""
    kinds = {a.kind for a in reading.acts}
    if kinds & set(NEVER_KINDS):
        return "never"
    if reading.errors or kinds & {"unknown", "program", "install", "outside", "move_out"}:
        return "ask"
    if "delete" in kinds:
        return "delete"
    if "network" in kinds:
        return "network"
    if any(a.unresolved for a in reading.acts):
        return "ask"
    if kinds & {"change", "overwrite"}:
        return "write"
    return "read"
