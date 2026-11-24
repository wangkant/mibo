"""What code shows it does past running, read before it runs: code written out on the command line, and the file an
interpreter or a runner is given (pstables.RUNNERS), whichever turn wrote it. Python is read as its tree (`python`);
PowerShell as a command (read.read); other languages by their words (`words`: pstables.CODE_NET, CODE_PIECES,
CODE_RUN, CODE_STARTS).

Python code counts as off the network only when every module it imports is in SAFE_MODULES (or a file of its own
folder, read the same way) and nothing in it is imported, looked up or run by a name worked out as it runs. Code that
names the network (an address, a network module) is asked every time as a costly step and runs online on the person's
yes; so is code not shown to be off the network, unless the network hardening holds now (netguard.blocking), when it
runs off the network on the reviewer's word. Code that runs or imports what it decoded is never run; a program it
starts is read as a command where it is written out, and asked where it is not.
"""
from __future__ import annotations

import ast
import json
import os
import re
import threading

from .acts import COMMAND_MAX, Act
from .pstables import CODE_NET, CODE_PIECES, CODE_RUN, CODE_STARTS

# Modules whose code opens nothing on the network by design: the standard library's file, text and number work, and
# the libraries scripts for documents, tables and charts use. os and subprocess are here because what their calls
# start is read as a command (RUN_CALLS). Kept out: anything that opens a socket, fetches an address it is given, or
# loads code by name (pickle, marshal, ctypes, importlib, urllib, http, socket, ssl, asyncio, multiprocessing).
SAFE_MODULES = frozenset({
    "__future__", "math", "cmath", "json", "re", "os", "os.path", "pathlib", "csv", "datetime", "time", "calendar",
    "collections", "itertools", "functools", "statistics", "random", "sys", "shutil", "glob", "fnmatch", "zipfile",
    "tarfile", "gzip", "bz2", "lzma", "hashlib", "textwrap", "string", "decimal", "fractions", "sqlite3", "argparse",
    "typing", "dataclasses", "enum", "io", "struct", "unicodedata", "locale", "pprint", "copy", "operator", "bisect",
    "heapq", "html", "xml.etree", "xml.dom.minidom", "xml.parsers.expat", "configparser", "difflib", "tempfile",
    "logging", "traceback", "warnings", "uuid", "contextlib", "abc", "numbers", "array", "subprocess", "pandas",
    "numpy", "openpyxl", "xlrd", "xlsxwriter", "docx", "pptx", "PIL", "matplotlib", "pypdf", "PyPDF2", "fitz",
    "reportlab", "yaml", "toml", "tomllib", "chardet", "dateutil", "tabulate", "tqdm", "scipy", "sklearn"})
# Parts of those that do reach the network or load code: xml.sax and xmlbuilder fetch external entities, logging's
# handlers and config open sockets and build handlers by name, tqdm's contrib posts to chat services, scipy's
# datasets download, matplotlib's web backend serves.
NOT_SAFE = ("xml.sax", "xml.dom.xmlbuilder", "xml.dom.pulldom", "logging.handlers", "logging.config", "tqdm.contrib",
            "scipy.datasets", "matplotlib.backends.backend_webagg")
# Modules that reach the network by name: code importing one is asked every time.
NET_MODULES = frozenset({
    "socket", "ssl", "urllib", "urllib3", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "poplib",
    "imaplib", "nntplib", "telnetlib", "xmlrpc", "socketserver", "wsgiref", "webbrowser", "websocket", "websockets",
    "paramiko", "pycurl", "dns", "asyncssh", "grpc", "zmq", "boto3", "botocore", "selenium", "playwright",
    "mechanize", "scrapy", "pysftp", "smbclient", "smbprotocol", "impacket", "scapy", "twisted", "tornado", "flask",
    "fastapi", "uvicorn", "aiosmtplib", "pyftpdlib"})
# Calls that start a program: what they are given is read as a command.
RUN_CALLS = {"os": {"system", "popen", "startfile", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp",
                    "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
                    "posix_spawn", "posix_spawnp"},
             "subprocess": {"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"}}
# Names that run text as code, or import or look up by a name worked out as it runs.
DYNAMIC = {"exec", "eval", "compile", "execfile", "__import__", "import_module", "breakpoint"}
# Attributes that reach past what the code names: the interpreter's own tables, a module's globals, code loaded from
# a pickle or a native library.
ESCAPES = {"__builtins__", "__dict__", "__globals__", "__subclasses__", "__code__", "__closure__", "__getattribute__",
           "__loader__", "__spec__", "modules", "read_pickle", "unsafe_load", "full_load", "enable_load_extension",
           "load_extension", "DataSource"}
# Attributes that reach the network whatever the module.
NET_ATTRS = re.compile(r"^(?:urlopen|urlretrieve|create_connection|gethostbyname\w*|getaddrinfo|open_connection|"
                       r"start_server|fetch_\w+)$")
# Calls that turn bytes or numbers into the text of a name or code.
DECODERS = {"fromhex", "b64decode", "b32decode", "b16decode", "a85decode", "b85decode", "urlsafe_b64decode",
            "decodebytes", "unhexlify", "a2b_base64", "a2b_hex", "decompress", "chr"}
# An address in a string: a scheme's, or a share's (\\host\, //host/).
ADDRESS = re.compile(r"^(?!file:)[a-z][a-z0-9+.-]*://([^/\s'\"?#]*)|^(?:\\\\|//)([\w.$-]+)[\\/]", re.IGNORECASE)
# Notebook magics that only set how output shows; any other, and a line given to the shell (!), runs more than Python.
QUIET_MAGICS = re.compile(r"^%{1,2}(?:matplotlib|config|time|timeit|pylab|precision|load_ext autoreload|autoreload)\b")
# How far code is followed into its own modules and the commands it starts, and how many files are read.
DEPTH_MAX, FILES_MOST, READ_MOST = 3, 30, 1 << 18
_depth = threading.local()


def _act_net(host: str, why: str) -> Act:
    return Act("network", "code", why, host=host or "?", sends=True)


def words(code: str) -> list[Act]:
    """Code read by its words: text it fetched or decoded run as code (never done), the network reached (asked
    every time; it runs online on the person's yes), what it reads or runs built from pieces, a program it starts
    (asked every time)."""
    net, pieces = CODE_NET.search(code), CODE_PIECES.search(code)
    if CODE_RUN.search(code) and (net or pieces):
        return [Act("hidden", "download_run", "runs code it fetched or decoded as it runs")]
    host = re.search(r"://([^/\s'\"?#]+)", code)
    return ([_act_net(host.group(1) if host else "?", "its code reaches the network")] if net else []) + (
        [Act("unknown", "pieces", "its code builds what it reads or runs from pieces")] if pieces else []) + (
        [Act("unknown", "started", "its code starts a program it names only as it runs")]
        if CODE_STARTS.search(code) else [])


class _Python(ast.NodeVisitor):
    """One Python file's tree: what it imports, what it builds from pieces, what it runs or looks up by a worked-out
    name, what it starts, the addresses it names."""

    def __init__(self, where: str, seen: set[str]):
        self.where, self.seen = where, seen
        self.aliases: dict[str, str] = {}
        self.unproven: list[str] = []
        self.hosts: list[str] = []
        self.started: list[str | None] = []
        self.fed = False
        self.tainted: set[str] = set()
        self.docs: set[int] = set()

    # ---------------------------------------------------------------- what a value is built from

    def pieces(self, node) -> bool:
        """`node` holds text fetched from the network, decoded or put together from pieces, or a name holding such."""
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id in self.tainted:
                return True
            if isinstance(n, ast.Call):
                name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                source = self.module_of(n.func.value if isinstance(n.func, ast.Attribute) else n.func)
                if NET_ATTRS.match(name) or source.split(".")[0] in NET_MODULES:
                    return True
                if name in DECODERS or (name == "decode" and (
                        self.module_of(n.func.value) == "codecs" or isinstance(n.func.value, ast.Call))):
                    return True
                if name == "join" and n.args and isinstance(n.args[0], (ast.List, ast.Tuple)) and all(
                        isinstance(e, ast.Constant) for e in n.args[0].elts):
                    return True
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and all(
                    isinstance(s, ast.Constant) and isinstance(s.value, str) for s in (n.left, n.right)):
                return True
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice) and isinstance(n.value, ast.Constant) \
                    and n.slice.step is not None:
                return True
        return False

    def module_of(self, node) -> str:
        """The module a name or an attribute chain stands for, by the code's imports ("" for none)."""
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, "")
        if isinstance(node, ast.Attribute):
            base = self.module_of(node.value)
            return f"{base}.{node.attr}" if base else ""
        return ""

    # ---------------------------------------------------------------- imports

    def imported(self, name: str) -> None:
        top = name.split(".")[0]
        own = next((p for p in (os.path.join(self.where, top + ".py"), os.path.join(self.where, top, "__init__.py"))
                    if os.path.isfile(p)), "")
        if own:
            self.own(own)
        elif top in NET_MODULES:
            self.hosts.append("?")
        elif not (any(name == m or name.startswith(m + ".") for m in SAFE_MODULES) or top in SAFE_MODULES) or any(
                name == m or name.startswith(m + ".") for m in NOT_SAFE):
            self.unproven.append(f"it imports {name}")

    def own(self, path: str) -> None:
        """A module of the code's own folder, which shadows any other of its name: read the same way."""
        key = os.path.normcase(os.path.abspath(path))
        if key in self.seen:
            return
        self.seen.add(key)
        if len(self.seen) > FILES_MOST:
            self.unproven.append("it imports more of its own modules than are read")
            return
        sub = _Python(os.path.dirname(path), self.seen)
        if not sub.read(_text(path)):
            self.unproven.append(f"its module {os.path.basename(path)} does not parse")
        self.unproven += sub.unproven
        self.hosts += sub.hosts
        self.started += sub.started
        self.fed = self.fed or sub.fed

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imported(alias.name)
            self.aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level:
            # A relative import: the code's own package.
            for alias in node.names:
                self.own_named(module or alias.name)
            return
        for alias in node.names:
            if alias.name == "*":
                self.unproven.append(f"it takes every name of {module}")
            elif NET_ATTRS.match(alias.name):
                self.hosts.append("?")
            self.imported(f"{module}.{alias.name}" if f"{module}.{alias.name}".startswith(NOT_SAFE) else module)
            self.aliases[alias.asname or alias.name] = f"{module}.{alias.name}"

    def own_named(self, name: str) -> None:
        top = os.path.join(self.where, *name.split("."))
        path = next((p for p in (top + ".py", os.path.join(top, "__init__.py")) if os.path.isfile(p)), "")
        if path:
            self.own(path)
        else:
            self.unproven.append(f"it imports {name} from its package")

    # ---------------------------------------------------------------- the rest

    def visit_Assign(self, node) -> None:
        if self.pieces(node.value):
            for target in node.targets:
                self.tainted |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        self.generic_visit(node)

    def _one(self, node) -> None:
        if node.value is not None and self.pieces(node.value):
            self.tainted |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
        self.generic_visit(node)

    visit_AnnAssign = visit_AugAssign = visit_NamedExpr = _one

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self.docs:
            found = ADDRESS.search(node.value.strip())
            if found:
                self.hosts.append(found.group(1) or found.group(2) or "?")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in ESCAPES or (node.attr == "path" and self.module_of(node.value) == "sys"):
            self.unproven.append(f"it reaches {node.attr}")
        elif NET_ATTRS.match(node.attr):
            self.hosts.append("?")
        elif node.attr in RUN_CALLS.get(self.module_of(node.value), ()) and not getattr(node, "called", False):
            self.unproven.append(f"it takes {node.attr} by name")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        module, _, name = self.aliases.get(node.id, "").rpartition(".")
        if not getattr(node, "called", False) and (node.id in {"__builtins__", "globals", "locals", "vars", *DYNAMIC}
                                                   or name in RUN_CALLS.get(module, ())):
            self.unproven.append(f"it reaches {node.id}")

    def visit_Call(self, node: ast.Call) -> None:
        node.func.called = True
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        module = self.module_of(node.func.value) if isinstance(node.func, ast.Attribute) else ""
        full = self.aliases.get(name, "") if isinstance(node.func, ast.Name) else f"{module}.{name}"
        first = node.args[0] if node.args else None
        literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
        if full.rsplit(".", 1)[0] in RUN_CALLS and full.rsplit(".", 1)[-1] in RUN_CALLS[full.rsplit(".", 1)[0]]:
            self.start(node)
        elif name in ("__import__", "import_module") and literal:
            self.imported(first.value)
        elif name in DYNAMIC or (name in ("globals", "locals", "vars") and isinstance(node.func, ast.Name)):
            self.dynamic(node, name)
        elif name == "getattr" and isinstance(node.func, ast.Name):
            key = node.args[1] if len(node.args) > 1 else None
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                self.dynamic(node, "getattr")
            elif key.value in DYNAMIC | ESCAPES or any(key.value in names for names in RUN_CALLS.values()):
                self.dynamic(node, f"getattr {key.value}")
            elif NET_ATTRS.match(key.value) or CODE_NET.fullmatch(key.value):
                self.hosts.append("?")
        elif name == "load" and module.split(".")[0] == "yaml" and not any(
                k.arg == "Loader" and "Safe" in ast.unparse(k.value) for k in node.keywords):
            self.unproven.append("it loads YAML that can build objects")
        elif any(k.arg == "allow_pickle" for k in node.keywords):
            self.unproven.append("it loads pickled objects")
        self.generic_visit(node)

    def dynamic(self, node: ast.Call, what: str) -> None:
        """Code run, imported or looked up by a name worked out as it runs: never done when that came from pieces."""
        if any(self.pieces(a) for a in [*node.args, *(k.value for k in node.keywords)]):
            self.fed = True
        self.unproven.append(f"it uses {what}")

    def start(self, node: ast.Call) -> None:
        """A program started: its command when it is written out, else None (asked)."""
        first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg in ("args", "cmd")), None)
        if first is not None and any(self.pieces(a) for a in [first, *node.args[1:]]):
            self.fed = True
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            self.started.append(first.value)
        elif isinstance(first, (ast.List, ast.Tuple)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in first.elts):
            self.started.append(" ".join(f'"{e.value}"' if " " in e.value else e.value for e in first.elts))
        else:
            self.started.append(None)

    def read(self, code: str) -> bool:
        """Reads `code`; False when it does not parse."""
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            return False
        for holder in ast.walk(tree):
            body = getattr(holder, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                self.docs.add(id(body[0].value))
        self.visit(tree)
        return True


def python(code: str, where: str) -> list[Act]:
    """Python code read as its tree (module docstring above): what it does past running, as acts."""
    reader = _Python(where, set())
    if not reader.read(code):
        return [Act("unknown", "unparsed", "its code does not parse, so it cannot be read first")]
    if reader.fed:
        return [Act("hidden", "download_run", "runs or imports code it decoded as it runs")]
    acts: list[Act] = []
    for command in reader.started:
        acts += _command(command, where) if command is not None else [
            Act("unknown", "started", "its code starts a program it names only as it runs")]
    if reader.hosts:
        acts.append(_act_net(next((h for h in reader.hosts if h != "?"), "?"), "its code reaches the network"))
    elif reader.unproven and not _blocking():
        acts.append(_act_net("?", f"its code may reach the network: {reader.unproven[0]}"))
    return acts


def _blocking() -> bool:
    from .netguard import blocking
    return blocking()


def _command(command: str, cwd: str) -> list[Act]:
    """A command code starts, read as one (read.read), not past DEPTH_MAX."""
    depth = getattr(_depth, "n", 0)
    if depth >= DEPTH_MAX:
        return [Act("unknown", "started", "its code starts a program too deep to read first")]
    if len(command) > COMMAND_MAX:
        return words(command)
    from .read import read
    _depth.n = depth + 1
    try:
        reading = read(command, cwd)
    finally:
        _depth.n = depth
    return reading.acts + [Act("unknown", "invalid", e) for e in reading.errors][:1]


def _text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(READ_MOST)


def notebook(text: str) -> str:
    """A notebook's code cells as one Python file; a magic that runs more than Python stands as a call to exec."""
    try:
        cells = json.loads(text).get("cells") or []
    except (ValueError, AttributeError):
        return "\0"
    lines = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source") or ""
        for line in ("".join(source) if isinstance(source, list) else str(source)).splitlines():
            stripped = line.strip()
            if stripped.startswith(("!", "%")):
                line = "" if QUIET_MAGICS.match(stripped) else "exec(_)"
            lines.append(line)
    return "\n".join(lines)


def file_acts(path: str, python_: bool) -> list[Act]:
    """What a file of code shows it does (`python_`: run by Python): read as its language is. A file not there yet
    shows nothing; the command that writes it is read with it (shell/panel.py)."""
    if not os.path.isfile(path):
        return []
    text = _text(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ipynb":
        return python(notebook(text), os.path.dirname(path))
    if python_ or ext in (".py", ".pyw"):
        return python(text, os.path.dirname(path))
    if ext in (".ps1", ".psm1"):
        return _command(text, os.path.dirname(path))
    if os.path.basename(path).lower() == "package.json":
        try:
            scripts = json.loads(text).get("scripts") or {}
        except (ValueError, AttributeError):
            scripts = {"": text}
        return words("\n".join(map(str, scripts.values())))
    return words(text)


def scripts(acts: list[Act]) -> list[Act]:
    """The last pass over a command's reading (read.read, bashread.read): what each file of code it runs shows."""
    found: list[Act] = []
    for act in acts:
        if act.what == "script" and act.paths and os.path.isfile(act.paths[0]):
            found += file_acts(act.paths[0], act.name.lower().startswith(("python", "py ", "pythonw", "ipython")))
    return found
