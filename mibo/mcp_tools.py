"""MCP servers as people already have them: the configuration, its secrets, the tools and the person's choices.

The servers are `<home>/mcp.json` in the shape Claude Desktop, Claude Code and
Cursor use (`{"mcpServers": {"name": {"command", "args", "env"} | {"url",
"headers"}}}`, `"disabled": true` to switch one off). Every `env` and `headers`
value is kept in the system's credential store (secretstore.py) as
`MIBO_MCP_<SERVER>_<NAME>`, the file holding only `${MIBO_MCP_…}` in its place:
never shown again, never sent to the model, never passed to another server.
A `${NAME}` the app does not hold is asked for in Settings, never read from
the app's own settings.

The person's choices per tool (auto, always, never), per server for its tools
that write or delete (auto or never), and the local programs allowed to start
live in `<home>/runtime/desktop/mcp-grants.json`. A tool is known by a
fingerprint of its whole description, so a tool renamed or changed after it was
allowed asks again. What a server says (descriptions, results) is third-party
material: fenced, cut to size, never obeyed (mcp_schema.py). Its annotations are
hints the specification says not to trust alone: they can only add a question,
never take one away. What a tool and each call of it does (whether it pays,
deletes or changes an account's security or access) is decided by code from
its name, parameters, description and the call's arguments (mcp_floor.py), and
such a call is always asked in the chat.

The page process runs the servers (mcp_hub.py); the reply model reaches them
through it (mcp_offer.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .mcp_floor import asks_each_time, group_of, hard
from .storage import atomic_write_text
from .textproc import scrub_third_party_text

CONFIG_FILE = "mcp.json"
GRANTS_FILE = "mcp-grants.json"
LOG_FILE = "mcp-log.jsonl"
SECRET_PREFIX = "MIBO_MCP_"
MAX_SERVERS = 30
#: Tools kept per server: a server listing more is cut here (and says so in Settings).
MAX_TOOLS = 200
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_.\-/]{1,128}")
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
HEADER_NAME_RE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}")
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
MAX_ARGS, MAX_ARG_CHARS, MAX_VALUE_CHARS, MAX_PAIRS = 64, 4096, 8192, 64
DESCRIPTION_CHARS = 1000
SCHEMA_CHARS = 20_000
LOG_KEPT = 500
# auto: a tool in the read group (group_of) runs; any other, the reviewer (review.py) looks first and the chat asks
# only where it does not pass. always; never.
AUTO, ALWAYS, NEVER = "auto", "always", "never"
MODES = (AUTO, ALWAYS, NEVER)


class ToolsError(ValueError):
    """A refusal the page names; `str()` is its code."""


# ------------------------------------------------------------------ files --

def config_path(home: Path) -> Path:
    return Path(home) / CONFIG_FILE


def desktop_dir(home: Path) -> Path:
    return Path(home) / "runtime" / "desktop"


def server_folder(home: Path, name: str) -> Path:
    """A local server's own working folder, and where its stderr is kept."""
    return Path(home) / "runtime" / "mcp" / name


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _raw_config(home: Path) -> dict:
    """The file as written, for a change that must keep everything else in it."""
    path = config_path(home)
    if not path.exists():
        return {"mcpServers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ToolsError("tools_file_damaged") from None
    if not isinstance(data, dict) or not isinstance(data.setdefault("mcpServers", {}), dict):
        raise ToolsError("tools_file_damaged")
    return data


def _save_config(home: Path, config: dict) -> None:
    try:
        atomic_write_text(config_path(home), json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        raise ToolsError("tools_write_failed") from None


def load_config(home: Path) -> dict:
    """{"mcpServers": {name: spec}}: the servers that read as one, `disabled` kept; `bad` names the rest."""
    raw = _read(config_path(home)).get("mcpServers")
    servers, bad = {}, []
    for name, spec in (raw.items() if isinstance(raw, dict) else ()):
        try:
            servers[_server_name(name)] = {**normalize(spec), "disabled": spec.get("disabled") is True}
        except ToolsError:
            bad.append(str(name)[:40])
    return {"mcpServers": servers, "bad": bad}


# -------------------------------------------------------------- parsing --

def _server_name(name) -> str:
    name = str(name or "").strip()
    if not NAME_RE.fullmatch(name):
        raise ToolsError("tools_bad_name")
    return name


def _text(value, limit: int) -> str:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        raise ToolsError("tools_bad_snippet")
    text = str(value)
    if len(text) > limit or "\x00" in text:
        raise ToolsError("tools_bad_snippet")
    return text


def _pairs(value, name_re: re.Pattern) -> dict:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or len(value) > MAX_PAIRS:
        raise ToolsError("tools_bad_snippet")
    out = {}
    for key, item in value.items():
        if not isinstance(key, str) or not name_re.fullmatch(key):
            raise ToolsError("tools_bad_snippet")
        out[key] = _text(item, MAX_VALUE_CHARS)
        if "\n" in out[key] or "\r" in out[key]:
            raise ToolsError("tools_bad_snippet")
    return out


def normalize(spec) -> dict:
    """One server as it is stored: a program (`command`, `args`, `env`, `cwd`) or an address (`url`,
    `headers`, and `type` "sse" for the older transport). Raises ToolsError."""
    if not isinstance(spec, dict):
        raise ToolsError("tools_bad_snippet")
    kind = str(spec.get("type") or spec.get("transport") or "").lower().replace("_", "-")
    url = spec.get("url") or spec.get("serverUrl") or spec.get("httpUrl")
    if spec.get("command"):
        command = _text(spec["command"], 1024).strip()
        args = spec.get("args") or []
        if isinstance(args, str) or not isinstance(args, list) or len(args) > MAX_ARGS or not command:
            raise ToolsError("tools_bad_snippet")
        out = {"command": command, "args": [_text(a, MAX_ARG_CHARS) for a in args]}
        env = _pairs(spec.get("env"), ENV_NAME_RE)
        if env:
            out["env"] = env
        if spec.get("cwd"):
            out["cwd"] = _text(spec["cwd"], 1024)
        return out
    if url:
        url = _text(url, 2048).strip()
        parts = urlsplit(url.replace("${", "").replace("}", ""))
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ToolsError("tools_bad_url")
        out = {"url": url}
        if kind == "sse" or (parts.path.rstrip("/").endswith("/sse") and kind not in ("http", "streamable-http")):
            out["type"] = "sse"
        headers = _pairs(spec.get("headers"), HEADER_NAME_RE)
        if headers:
            out["headers"] = headers
        return out
    raise ToolsError("tools_bad_snippet")


def _guess_name(spec: dict) -> str:
    """A name for a server pasted without one: its package or its host."""
    if spec.get("command"):
        words = [a for a in spec.get("args", []) if not a.startswith("-")]
        word = words[0] if words else spec["command"]
        # @scope/name@1.2 -> name; a path -> its last part.
        base = re.sub(r"(?<=.)@[^@/\\]*$", "", word).replace("\\", "/").split("/")[-1]
        base = re.sub(r"\.(exe|cmd|bat|py|js)$", "", base, flags=re.IGNORECASE)
        for prefix in ("mcp-server-", "server-", "mcp-"):
            if base.startswith(prefix) and len(base) > len(prefix):
                base = base[len(prefix):]
                break
        for suffix in ("-mcp-server", "-mcp"):
            if base.endswith(suffix) and len(base) > len(suffix):
                base = base[:-len(suffix)]
                break
    else:
        # mcp.deepwiki.com -> deepwiki: the first part of the host that names something.
        labels = (urlsplit(spec["url"]).hostname or "server").split(".")
        base = next((p for p in labels[:-1] if p not in ("mcp", "api", "www", "server")), labels[0])
    base = re.sub(r"[^A-Za-z0-9_.-]", "-", base).strip("-.") or "server"
    return base[:40]


def parse_snippet(text: str, name: str = "") -> dict:
    """{name: spec} from what a README or another app shows: the whole `{"mcpServers": …}` object, VS Code's
    `servers`, a bare `"name": {…}` entry, or one server's object (named `name`, else after its package); or one
    line that is a server's address or the command that starts it."""
    text = str(text or "").strip()
    if not text or len(text) > 200_000:
        raise ToolsError("tools_bad_snippet")
    data = None
    for attempt in (text, "{" + text.rstrip(",") + "}"):
        try:
            data = json.loads(attempt)
            break
        except ValueError:
            continue
    if data is None and "\n" not in text and not text.startswith(("{", "[")) and not re.search(r'"\s*:\s*[{\[]', text):
        import shlex
        try:
            words = [w[1:-1] if len(w) > 1 and w[0] == w[-1] == '"' else w for w in shlex.split(text, posix=False)]
        except ValueError:
            raise ToolsError("tools_bad_snippet") from None
        # An address, or a program with at least one argument ("uvx mcp-server-time"); a lone word is not taken.
        if not re.match(r"^https?://", text) and len(words) < 2:
            raise ToolsError("tools_bad_snippet")
        data = {"url": text} if re.match(r"^https?://", text) else {"command": words[0], "args": words[1:]}
    if not isinstance(data, dict):
        raise ToolsError("tools_bad_snippet")
    if isinstance(data.get("mcp"), dict) and isinstance(data["mcp"].get("servers"), dict):
        data = data["mcp"]
    for key in ("mcpServers", "servers", "context_servers"):
        if isinstance(data.get(key), dict):
            data = data[key]
            break
    if any(k in data for k in ("command", "url", "serverUrl", "httpUrl")):
        spec = normalize(data)
        return {_server_name(name) if name else _guess_name(spec): {**spec, "disabled": data.get("disabled") is True}}
    if not data or not all(isinstance(v, dict) for v in data.values()):
        raise ToolsError("tools_bad_snippet")
    servers = {_server_name(key): {**normalize(value), "disabled": value.get("disabled") is True}
               for key, value in data.items()}
    if name and len(servers) == 1:
        servers = {_server_name(name): next(iter(servers.values()))}
    return servers


# -------------------------------------------------------------- secrets --

def secret_key(server: str, kind: str, name: str) -> str:
    """The name a server's value is kept under: MIBO_MCP_<SERVER>_<NAME> (H_ before a header's)."""
    server, name = (re.sub(r"[^A-Z0-9]", "_", s.upper()) for s in (server, name))
    return f"{SECRET_PREFIX}{server}_{'H_' if kind == 'headers' else ''}{name}"


def stash(server: str, spec: dict) -> tuple[dict, dict]:
    """(the spec as the file keeps it, the values to keep): every env and header value that is not
    already a reference is kept, and its place holds the reference."""
    kept, values = dict(spec), {}
    for kind in ("env", "headers"):
        pairs = {}
        for name, value in (spec.get(kind) or {}).items():
            if REF_RE.fullmatch(value.strip()):
                pairs[name] = value.strip()
                continue
            key = secret_key(server, kind, name)
            values[key] = value
            pairs[name] = "${" + key + "}"
        if pairs:
            kept[kind] = pairs
    return kept, values


def expand(spec: dict, secrets: dict) -> tuple[dict, list[str]]:
    """The spec with every `${NAME}` filled from the values the app keeps for its servers (`secrets`, the
    MIBO_MCP_ names of the credential store), and the names it does not hold. A name of the app's own settings, the
    model key among them, is never filled."""
    missing: list[str] = []

    def fill(text: str) -> str:
        def one(m: re.Match) -> str:
            name, default = m.group(1), m.group(2)
            if name.startswith(SECRET_PREFIX) and secrets.get(name):
                return secrets[name]
            if default is not None:
                return default
            missing.append(name)
            return ""
        return REF_RE.sub(one, text)

    out = {k: v for k, v in spec.items() if k != "disabled"}
    for key in ("command", "url", "cwd"):
        if key in out:
            out[key] = fill(out[key])
    if "args" in out:
        out["args"] = [fill(a) for a in out["args"]]
    for kind in ("env", "headers"):
        if kind in out:
            out[kind] = {k: fill(v) for k, v in out[kind].items()}
    return out, sorted(set(missing))


def secret_names(spec: dict) -> list[dict]:
    """What Settings shows of a server's values: the names, whether each is a reference, and its text; a secret
    part of an address is one more, named by its reference."""
    rows = [{"kind": kind, "name": name, "ref": bool(REF_RE.fullmatch(value.strip())), "text": value}
            for kind in ("env", "headers") for name, value in (spec.get(kind) or {}).items()]
    rows += [{"kind": "url", "name": found.group(1), "ref": True, "text": found.group(0)}
             for found in REF_RE.finditer(spec.get("url") or "") if found.group(1).startswith(SECRET_PREFIX)]
    return rows


def write_servers(home: Path, servers: dict, write_env, *, replace: bool = False) -> list[str]:
    """Adds (or with `replace`, writes over) servers: secrets through `write_env`, the rest to
    mcp.json. Returns the names."""
    raw = _raw_config(home)
    have = raw["mcpServers"]
    if not replace and any(name in have for name in servers):
        raise ToolsError("tools_name_taken")
    if len({*have, *servers}) > MAX_SERVERS:
        raise ToolsError("tools_too_many")
    secrets: dict = {}
    for name, spec in servers.items():
        kept, values = stash(name, {k: v for k, v in spec.items() if k != "disabled"})
        secrets.update(values)
        old = have.get(name) if isinstance(have.get(name), dict) else {}
        # Keys this app does not read (another app's own fields) stay as written.
        extra = {k: v for k, v in old.items() if k not in ("command", "args", "env", "cwd", "url", "headers",
                                                             "type", "transport", "serverUrl", "httpUrl")}
        have[name] = {**extra, **kept, **({"disabled": True} if spec.get("disabled") else {})}
        if not spec.get("disabled"):
            have[name].pop("disabled", None)
    if secrets:
        write_env(secrets)
    _save_config(home, raw)
    return list(servers)


def set_value(home: Path, server: str, kind: str, name: str, value: str, write_env) -> None:
    """A value Settings asked for (a missing ${NAME}, or a new key): kept through `write_env`, referenced
    from the file."""
    raw = _raw_config(home)
    entry = raw["mcpServers"].get(server)
    if isinstance(entry, dict) and kind == "url" and name.startswith(SECRET_PREFIX) \
            and "${" + name + "}" in str(entry.get("url") or ""):
        # A secret part of the address: kept under the name the address refers to.
        write_env({name: _text(value, MAX_VALUE_CHARS)})
        return
    if not isinstance(entry, dict) or kind not in ("env", "headers"):
        raise ToolsError("tools_unknown_server")
    if not (ENV_NAME_RE if kind == "env" else HEADER_NAME_RE).fullmatch(name):
        raise ToolsError("tools_bad_snippet")
    value = _text(value, MAX_VALUE_CHARS)
    current = str((entry.get(kind) or {}).get(name) or "")
    found = REF_RE.fullmatch(current.strip())
    key = found.group(1) if found and found.group(1).startswith(SECRET_PREFIX) else secret_key(server, kind, name)
    if found and not found.group(1).startswith(SECRET_PREFIX):
        # A reference to a name of the person's own (${GITHUB_TOKEN}): the value is kept under that name's own key.
        key = SECRET_PREFIX + re.sub(r"[^A-Z0-9]", "_", found.group(1).upper())
    write_env({key: value})
    entry[kind] = {**(entry.get(kind) or {}), name: "${" + key + "}"}
    _save_config(home, raw)


def set_disabled(home: Path, server: str, disabled: bool) -> None:
    raw = _raw_config(home)
    entry = raw["mcpServers"].get(server)
    if not isinstance(entry, dict):
        raise ToolsError("tools_unknown_server")
    if disabled:
        entry["disabled"] = True
    else:
        entry.pop("disabled", None)
    _save_config(home, raw)


def remove_server(home: Path, server: str) -> list[str]:
    """Drops the server; returns the names its values were kept under, for the caller to clear."""
    raw = _raw_config(home)
    entry = raw["mcpServers"].pop(server, None)
    if entry is None:
        raise ToolsError("tools_unknown_server")
    _save_config(home, raw)
    keys = []
    for kind in ("env", "headers"):
        for value in ((entry.get(kind) or {}) if isinstance(entry, dict) else {}).values():
            found = REF_RE.fullmatch(str(value).strip())
            if found and found.group(1).startswith(SECRET_PREFIX):
                keys.append(found.group(1))
    keys += [m.group(1) for m in REF_RE.finditer(str(entry.get("url") or "") if isinstance(entry, dict) else "")
             if m.group(1).startswith(SECRET_PREFIX)]
    return keys


def start_key(spec: dict) -> str:
    """What starting a local program was allowed for: its command, arguments, folder and which values
    it gets (not the values). Any change asks again."""
    shown = {"command": spec.get("command", ""), "args": spec.get("args", []), "cwd": spec.get("cwd", ""),
             "env": sorted(spec.get("env") or {})}
    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode()).hexdigest()[:24]


def program_of(spec: dict) -> str:
    """A local server's program and what it runs, short, for a card's one line: "npx · @scope/server",
    "python · tiny_server.py"; folders left off."""
    def short(word: str) -> str:
        return word if word.startswith("@") else re.split(r"[\\/]", word.rstrip("\\/"))[-1]
    program = re.sub(r"\.(exe|cmd|bat)$", "", short(spec.get("command", "")), flags=re.IGNORECASE)
    runs = next((a for a in spec.get("args", []) if a and not a.startswith("-")), "")
    return f"{program} · {short(runs)}" if runs else program


def command_line(spec: dict) -> str:
    """The exact command a card names, quoted as a shell would show it."""
    def quote(word: str) -> str:
        return f'"{word}"' if not word or re.search(r'[\s"&|<>^]', word) else word
    return " ".join(quote(w) for w in [spec.get("command", ""), *spec.get("args", [])])


def masked(url: str) -> str:
    """An address as Settings shows it: values in its query hidden, since some servers put keys there."""
    head, _, query = url.partition("?")
    if not query:
        return url
    return head + "?" + "&".join(part.split("=", 1)[0] + "=…" for part in query.split("&"))


# ----------------------------------------------------------- tool lists --

_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def clean_tool(raw: dict) -> dict | None:
    """One tool as a server described it, bounded, with a fingerprint of the whole description; None when
    it has no usable name."""
    name = raw.get("name")
    # The characters the spec gives tool names: a name is shown to the model unfenced, so nothing else.
    if not isinstance(name, str) or not TOOL_NAME_RE.fullmatch(name):
        return None
    annotations = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {}
    title = raw.get("title") or annotations.get("title") or ""
    schema = raw.get("inputSchema")
    if not isinstance(schema, dict) or len(json.dumps(schema, ensure_ascii=False)) > SCHEMA_CHARS:
        schema = {"type": "object"}
    hints = {k: annotations[k] for k in _HINTS if isinstance(annotations.get(k), bool)}
    whole = json.dumps({"name": name, "title": title, "description": raw.get("description") or "",
                        "inputSchema": schema, "hints": hints}, sort_keys=True, ensure_ascii=False)
    tool = {"name": name,
            "title": scrub_third_party_text(title if isinstance(title, str) else "").strip()[:100],
            "description": scrub_third_party_text(raw.get("description") or "").strip()[:DESCRIPTION_CHARS],
            "inputSchema": schema, "hints": hints,
            "fp": hashlib.sha256(whole.encode()).hexdigest()[:16]}
    # What it does by its name, parameters and description: a floor kind asks every time.
    tool["hard"] = hard(tool)
    return tool


def clean_tools(raw: list) -> list[dict]:
    seen, out = set(), []
    for item in raw:
        tool = clean_tool(item) if isinstance(item, dict) else None
        if tool and tool["name"] not in seen:
            seen.add(tool["name"])
            out.append(tool)
    return out


# --------------------------------------------------------------- grants --

class Grants:
    """The person's choices, in the desktop folder: per tool, per server for its tools that write or delete (Claude's
    connectors set that group at once the same way), and local programs allowed to start. A tool's own choice comes
    before its group's. A tool its provider marks destructive, or one that pays, deletes or changes an account or
    access (`hard`), is never always allowed."""

    def __init__(self, home: Path):
        self.path = desktop_dir(home) / GRANTS_FILE
        self.lock = threading.Lock()

    def read(self) -> dict:
        data = _read(self.path)
        for key in ("tools", "start", "groups"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        return data

    def _change(self, change) -> None:
        with self.lock:
            data = self.read()
            change(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

    def mode(self, server: str, tool: dict) -> tuple[str, bool]:
        """(auto, always or never, and whether an "always" was given to a tool that has changed since)."""
        data = self.read()
        row = data["tools"].get(f"{server}/{tool['name']}")
        if isinstance(row, dict) and row.get("mode") in (ALWAYS, NEVER):
            if row["mode"] == ALWAYS and (row.get("fp") != tool["fp"] or asks_each_time(tool)):
                return AUTO, row.get("fp") != tool["fp"]
            return row["mode"], False
        return (self.group(server) if group_of(tool) == "write" else AUTO), False

    def set_mode(self, server: str, tool: dict, mode: str) -> None:
        def change(data: dict) -> None:
            key = f"{server}/{tool['name']}"
            if mode == AUTO:
                data["tools"].pop(key, None)
            else:
                data["tools"][key] = {"mode": mode, "fp": tool["fp"], "at": time.time()}
        self._change(change)

    def group(self, server: str) -> str:
        """The mode of the server's tools that write or delete: auto or never, never always."""
        return NEVER if (self.read()["groups"].get(server) or {}).get("write") == NEVER else AUTO

    def set_group(self, server: str, mode: str, tools: list[dict]) -> None:
        """One mode for the server's tools that write or delete, set at once: their own choices give way to it."""
        def change(data: dict) -> None:
            data["groups"].setdefault(server, {})["write"] = mode
            for tool in tools:
                if group_of(tool) == "write":
                    data["tools"].pop(f"{server}/{tool['name']}", None)
        self._change(change)

    def started(self, server: str, spec: dict) -> bool:
        return self.read()["start"].get(server) == start_key(spec)

    def allow_start(self, server: str, spec: dict) -> None:
        def change(data: dict) -> None:
            data["start"][server] = start_key(spec)
        self._change(change)

    def forget(self, server: str) -> None:
        def change(data: dict) -> None:
            data["start"].pop(server, None)
            data["groups"].pop(server, None)
            for key in [k for k in data["tools"] if k.startswith(server + "/")]:
                data["tools"].pop(key)
        self._change(change)

    def log(self, entry: dict) -> None:
        path = self.path.with_name(LOG_FILE)
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.time(), **entry}, ensure_ascii=False) + "\n")
            if path.stat().st_size > 2_000_000:
                lines = path.read_text(encoding="utf-8").splitlines()[-LOG_KEPT:]
                atomic_write_text(path, "\n".join(lines) + "\n")

    def log_rows(self, n: int = 40) -> list[dict]:
        try:
            lines = self.path.with_name(LOG_FILE).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in reversed(lines[-n:]):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def clear_log(self) -> None:
        self.path.with_name(LOG_FILE).unlink(missing_ok=True)
