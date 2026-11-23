"""Sorting a bash command that runs programs, code or the network: the part of bashread.Sorter that knows
shells, interpreters, install tools, system tools and fetchers."""
from __future__ import annotations

import posixpath
import re
from urllib.parse import urlsplit

from .acts import Act
from .bashtables import (
    BUILD_WORDS,
    CURL_VALUES,
    DANGEROUS_VARS,
    DOWNLOAD_RUN,
    FACTS,
    FETCH_IN,
    FETCH_LONG,
    FETCH_OUT,
    FETCH_SENDS,
    INLINE,
    INLINE_LONG,
    INSTALL_READ,
    INSTALL_SEARCH,
    NET_VALUES,
    OPEN_RISKY_POSIX,
    PACKAGES,
    PIPE,
    SCRIPTS,
    SYSTEM_BARE,
    SYSTEM_READ,
    SYSTEM_VERBS,
    WGET_VALUES,
    WRAPPERS,
)
from .bashwords import Word, _bundles, _short, _texts, _tree
from .paths import _local_host
from .pstables import GIT_NET

# How deep `bash -c` inside `bash -c` is read before it counts as hidden.
DEPTH_MAX = 4


class Programs:
    """Mixed into bashread.Sorter, whose add(), touch(), blocked(), resolve(), args(), reach() and run() these use."""

    def program(self, name: str, words: list[Word | None]) -> None:
        place = self.resolve(name)
        if place == PIPE:
            self.add("hidden", "hidden", "runs commands handed over through a pipe, which cannot be read first")
            return
        if place is None:
            self.add("unknown", "program", f"runs {name} from a folder known only as it runs")
            return
        low = place.lower()
        if low.endswith(SCRIPTS) or "." not in posixpath.basename(place):
            refused = self.blocked(place, False)
            if refused:
                self.add(refused, refused, f"runs {place}, which is protected", paths=[place])
                return
        if low.endswith(PACKAGES):
            self.add("install", "install", f"runs the installer {place}", name=place)
        elif low.endswith(SCRIPTS):
            self.add("program", "script", f"runs the script {place}", name=place, paths=[place])
        else:
            texts = [t or "?" for t in _texts(words)]
            self.add("program", "program", f"runs the program {place}", name=f"{place} {' '.join(texts)}"[:160],
                     paths=[place], args=texts)

    def named_places(self, base: str, words: list[Word | None]) -> list[str] | None:
        """Every argument that could be a place, taken as written to; None, with a never act, when one is
        protected."""
        places = []
        for word in words:
            if word is None or "://" in word.text or not re.search(r"/|\.\w{1,5}$|^\.|^~", word.text):
                continue
            place = self.resolve(word.text.split("=", 1)[-1])
            if place is None:
                continue
            refused = self.blocked(place, True)
            if refused:
                self.add(refused, refused, f"runs {base} on {place}, which is protected", paths=[place])
                return None
            places.append(place)
        return places

    def unknown(self, base: str, words: list[Word | None]) -> None:
        """A command the tables do not know: asked, and every argument that could be a place counts as written,
        so a key or a system file named there is still refused."""
        places = self.named_places(base, words)
        if places is not None:
            self.add("unknown", "unknown", f"runs {base}, which the app does not know", paths=places, write=True,
                     name=f"{base} {_short(_texts(words))}"[:160])

    def wrapper(self, low: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        rest, take = list(words), False
        while rest and rest[0] is not None:
            text = rest[0].text
            if take:
                take = False
            elif low == "env" and re.fullmatch(r"[A-Za-z_]\w*=.*", text, re.DOTALL):
                var = text.split("=", 1)[0]
                if DANGEROUS_VARS.match(var):
                    self.add("hidden", "redefine", f"sets {var}, which changes what the command runs or loads")
                    return
            elif text.startswith("-") and len(text) > 1:
                if low in ("command", "builtin") and text in ("-v", "-V"):
                    return
                if (low == "env" and text in ("-S", "--split-string")) or text.startswith("-S"):
                    self.add("hidden", "hidden", "env -S splits a string into a command")
                    return
                take = re.fullmatch(r"-[A-Za-z]+", text) is not None and text[-1] in WRAPPERS[low]
            elif not (low in ("timeout", "watch") and re.fullmatch(r"[\d.]+[smhd]?", text)):
                break
            rest.pop(0)
        if not rest:
            if low == "env":
                self.add("read", "info", "lists the environment variables")
            return
        if rest[0] is None:
            self.add("hidden", "hidden", f"{low} runs a command whose name is computed")
            return
        self.run(rest[0].text, rest[1:], upstream, stdin)

    def location(self, low: str, texts: list[str | None]) -> None:
        if low == "popd":
            self.cwd = self.stack.pop() if self.stack else None
            return
        targets = [t for t in texts if t is None or not t.startswith("-") or t == "-"]
        if low == "pushd":
            self.stack.append(self.cwd)
        if not targets:
            if low == "cd":
                self.cwd = self.home
            return
        place = self.resolve(targets[0]) if targets[0] not in (None, "-") else None
        self.cwd = place
        if place is not None:
            self.touch("read", "look", f"works in {place}", [place])

    def source(self, texts: list[str | None]) -> None:
        place = self.resolve(texts[0]) if texts and texts[0] is not None else None
        if place in (None, PIPE):
            self.add("hidden", "hidden", "runs commands read from a place computed as it runs")
            return
        refused = self.blocked(place, False)
        if refused:
            self.add(refused, refused, f"runs commands from {place}, which is protected", paths=[place])
            return
        self.add("program", "script", f"runs the commands in {place}", name=place, paths=[place])

    @staticmethod
    def fed(upstream: list[Act], stdin: dict) -> str:
        """Where a shell or an interpreter reads its code from: "fetched" (the network or a decoder upstream),
        "pipe", "text" (a here-document or here-string), "file", or ""."""
        if any(a.kind == "network" or a.what == "decode" for a in upstream):
            return "fetched"
        return stdin.get("kind") or ""

    def shell(self, base: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        texts = _texts(words)
        code_at = next((n for n, t in enumerate(texts) if t is not None and (t == "-c" or _bundles(t, "c"))), None)
        if code_at is not None:
            if code_at + 1 >= len(words) or words[code_at + 1] is None:
                self.add("hidden", "hidden", f"runs {base} -c with code computed as it runs")
            else:
                self.inner(words[code_at + 1].text, base)
            return
        source = self.fed(upstream, stdin)
        if source == "fetched":
            self.add("hidden", "download_run", f"runs what the network or a decoder hands to {base}")
            return
        script = next((t for t in texts if t is None or not t.startswith("-")), "")
        if script == PIPE:
            self.add("hidden", "hidden", f"runs commands handed to {base} through a pipe, which cannot be read first")
        elif script:
            place = self.resolve(script)
            refused = self.blocked(place, False) if place else ""
            if refused:
                self.add(refused, refused, f"runs {place} with {base}, which is protected", paths=[place])
            else:
                self.add("program", "script", f"runs {script} with {base}", name=f"{base} {_short(texts)}",
                         paths=[place] if place else [], unresolved=place is None)
        elif script is None:
            self.add("hidden", "hidden", f"runs {base} on a script whose name is computed")
        elif source == "text" and stdin.get("text") is not None:
            self.inner(stdin["text"], base)
        else:
            self.add("hidden", "hidden", f"runs commands given to {base} on its input, which cannot be read first")

    def inner(self, code: str, base: str) -> None:
        """`bash -c '...'` and a here-document into bash: the code is read as a command of its own."""
        if self.depth >= DEPTH_MAX:
            self.add("hidden", "hidden", f"runs {base} inside {base} too deeply to read")
            return
        root = _tree(code)
        if root.has_error:
            self.add("unknown", "unknown", f"gives {base} code that does not parse")
            return
        sub = type(self)(self.cwd, self.home, self.depth + 1)
        sub.survey(root)
        sub.statement(root)
        self.acts += sub.acts

    def interpreter(self, low: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        texts = _texts(words)
        letters = INLINE.get(low, "e")
        if (texts and texts[0] is None) or any(t is not None and (_bundles(t, letters) or t in INLINE_LONG or any(
                t.startswith(f"{x}=") for x in INLINE_LONG)) for t in texts):
            self.add("hidden", "hidden", f"runs {low} with code given on the command line")
            return
        lowered = [t.lower() for t in texts if t is not None]
        if lowered[:2] == ["-m", "pip"]:
            self.pip(lowered[2:])
            return
        if lowered[:1] in (["--version"], ["-v"], ["-version"], ["--help"], ["-h"]):
            self.add("read", "info", f"asks {low} its version")
            return
        source = self.fed(upstream, stdin)
        if source == "fetched":
            self.add("hidden", "download_run", f"runs what the network or a decoder hands to {low}")
            return
        script = next((t for t in texts if t is None or not t.startswith("-")), "")
        if script is None or script == PIPE:
            self.add("hidden", "hidden", f"runs {low} on a script whose name is computed")
            return
        place = self.resolve(script) if script and lowered[:1] != ["-m"] else None
        refused = self.blocked(place, False) if place else ""
        if refused:
            self.add(refused, refused, f"runs {place}, which is protected", paths=[place])
            return
        self.add("program", "script", f"runs {low} {_short(texts)[:80]}".strip() + (
            "" if script else " with code given on its input"), name=f"{low} {_short(texts)}"[:160],
            paths=[place] if place else [])

    def pip(self, words: list[str]) -> None:
        if words and words[0] in ("list", "show", "freeze", "check", "--version", "-v", "inspect"):
            self.add("read", "apps", "lists what pip installed")
        elif words and words[0] in ("search", "index", "download"):
            self.add("network", "net", f"runs pip {' '.join(words)[:60]}", host="pypi.org", sends=False)
        else:
            self.add("install", "install", f"runs pip {' '.join(words)[:80]}", name=f"pip {' '.join(words)}"[:120])

    def install(self, low: str, texts: list[str | None]) -> None:
        words = [t for t in texts if t is not None]
        first = next((t for t in words if not t.startswith("-") or t in INSTALL_READ or t in INSTALL_SEARCH), "")
        said = " ".join(words)
        if low in DOWNLOAD_RUN or f"{low} {first}" in DOWNLOAD_RUN:
            self.add("hidden", "download_run", f"{low} downloads a package and runs it")
        elif low in ("pip", "pip3") or (low == "uv" and first == "pip"):
            self.pip(words[1:] if low == "uv" else words)
        elif low == "brew" and first == "services":
            self.add("system", "system", "changes background services with brew")
        elif first in BUILD_WORDS and low not in ("apt", "apt-get", "brew", "dnf", "yum", "pacman", "snap"):
            self.add("program", "program", f"runs {low} {said[:80]}", name=f"{low} {said}"[:160])
        elif first in INSTALL_READ or (not words and low in ("brew", "apt", "go", "cargo")):
            self.add("read", "apps", f"lists what {low} installed")
        elif first in INSTALL_SEARCH or (low == "softwareupdate" and first in ("-l", "--list")):
            self.add("network", "net", f"searches the {low} catalogue online", host=low, sends=False)
        else:
            self.add("install", "install", f"runs {low} {said[:80]}", name=f"{low} {said}"[:120])

    def facts(self, low: str, texts: list[str | None]) -> None:
        if low == "nvidia-smi" and any(t is None or (t.startswith("-") and not t.startswith(
                ("-q", "--query", "-L", "--list", "--format", "-i", "--id", "-d", "--display", "-h", "--help", "-l")))
                for t in texts):
            self.add("system", "system", "changes the graphics card's settings with nvidia-smi")
        else:
            self.add("read", FACTS[low], f"reads {low}")

    def system_tool(self, low: str, texts: list[str | None]) -> None:
        """A system tool that reads with some words and changes the system with the rest."""
        allowed = SYSTEM_READ[low]
        if any(t is None for t in texts):
            self.add("system", "system", f"runs {low} with computed arguments")
            return
        words = list(texts)
        if not words:
            changes = low not in SYSTEM_BARE
        elif low == "date":
            changes = any(w in ("-s", "--set") or re.fullmatch(r"\d{4,12}(\.\d\d)?", w) for w in words)
        elif low == "hostname":
            changes = any(w not in allowed for w in words)
        elif low == "ifconfig":
            changes = len([w for w in words if not w.startswith("-")]) > 1
        elif low == "networksetup":
            changes = not all(w.startswith(("-get", "-list", "-print", "-version", "-help")) or not w.startswith("-")
                              for w in words)
        elif low in ("ip", "nmcli"):
            changes = bool(set(words) & SYSTEM_VERBS) or words[0] not in allowed
        elif low == "sysctl":
            changes = any("=" in w for w in words) or any(w.startswith("-") and w not in allowed for w in words)
        elif low in ("mount", "xattr"):
            changes = any(w.startswith("-") and w not in allowed for w in words) or (
                low == "mount" and any(not w.startswith("-") for w in words))
        else:
            changes = words[0] not in allowed
        if low in ("systemctl", "launchctl") and words and words[0] in ("poweroff", "reboot", "halt", "suspend",
                                                                        "hibernate", "kexec", "soft-reboot"):
            self.add("shutdown", "shutdown", f"runs {low} {words[0]}")
        elif changes:
            self.add("system", "system", f"runs {' '.join([low, *words])[:80]}, which changes the system")
        else:
            self.add("read", "info", f"reads {' '.join([low, *words])[:80]}")

    def network(self, low: str, words: list[Word | None]) -> None:
        texts = _texts(words)
        if low in ("curl", "wget", "http", "https", "xh", "aria2c", "axel"):
            self.fetch(low, texts)
            return
        if any(t is None for t in texts):
            self.reach("?", True, f"runs {low} with computed arguments")
            return
        _, positional = self.args(words, NET_VALUES.get(low, ""))
        hosts = [p.text.split("@")[-1] for p in positional if not p.text.startswith("@")
                 and (re.search(r"[.:]", p.text) or p.text.lower() == "localhost" or "://" in p.text)]
        host = (urlsplit(hosts[0]).hostname or hosts[0]) if hosts and "://" in hosts[0] else (hosts[0] if hosts else "")
        sends = low in ("nc", "ncat", "netcat", "socat", "ftp", "tftp", "lftp")
        self.reach(host, sends, f"runs {low} to reach {host or 'the network'}", name=f"{low} {_short(texts)}"[:120])

    def fetch(self, low: str, texts: list[str | None]) -> None:
        """curl, wget and their kind: the addresses reached, what is sent, the files read to send and written."""
        if any(t is None for t in texts):
            self.reach("?", True, f"runs {low} with computed arguments")
            return
        pairs, urls = _fetch_options(low, texts)
        outs, reads, sends = self.fetch_effects(low, pairs, urls)
        for raw in reads:
            place = self.resolve(raw) if raw else None
            if place is None:
                self.add("read", "read", f"{low} reads a file to send whose name is computed", unresolved=True)
            else:
                self.touch("read", "read", f"reads {place} to send", [place])
        hosts = []
        for url in urls:
            parts = urlsplit(url if re.match(r"^[a-z][\w+.-]*://", url, re.IGNORECASE) else "http://" + url)
            scheme = parts.scheme.lower()
            if scheme == "file":
                self.touch("read", "read", f"reads {parts.path or '/'}", [parts.path or "/"])
            elif scheme in ("http", "https", "ftp", "ftps", "sftp", "scp", "ws", "wss", "tftp"):
                hosts.append(((parts.hostname or "").lower(), bool(parts.query)))
            else:
                self.add("unknown", "unknown", f"{low} reaches {url[:60]}, a kind of address the app does not know")
        paths = []
        for raw in outs:
            place = self.resolve(raw.replace("*", "") or ".") if raw else None
            if place is None:
                self.add("unknown", "write", f"{low} saves a download under a computed name", unresolved=True,
                         write=True)
                continue
            refused = self.blocked(place, True)
            if refused:
                self.add(refused, refused, f"{low} saves a download to {place}, which is protected", paths=[place])
                return
            paths.append(place)
        for host, query in hosts or [("", True)]:
            self.reach(host, sends or query, f"runs {low} to reach {host or 'the network'}" + (
                " and sends data" if sends or query else ""), paths=paths, write=bool(paths),
                name=f"{low} {' '.join(texts)}"[:120])

    def fetch_effects(self, low: str, pairs: list[tuple[str, str]], urls: list[str]) -> tuple[list, list, bool]:
        """(files written, files read to send, whether anything is sent) by a fetch's options; --url adds to
        `urls`, and options read from a file are asked."""
        outs, reads, sends = [], [], False
        for key, value in pairs:
            if key in FETCH_OUT and value != "-" and not (low == "curl" and key == "-c" and not value):
                outs.append(value)
            elif (key in ("-P", "--directory-prefix", "--dir", "-d") and low != "curl") or key == "--output-dir":
                outs.append(posixpath.join(value, "*"))
            elif key in ("-O", "--remote-name", "--remote-name-all") and low == "curl":
                outs.append("*")
            elif key == "-O" and low == "wget" and value != "-":
                outs.append(value)
            elif key == "--url":
                urls.append(value)
            elif key == "item":
                sends = sends or bool(re.search(r"[=:@]", value)) or value.upper() in ("POST", "PUT", "PATCH",
                                                                                         "DELETE")
            if key in FETCH_IN:
                reads.append(value)
            if key in FETCH_SENDS or (key in ("-X", "--request", "--method") and value.upper() not in ("GET", "HEAD")):
                sends = True
                reads += _sent_file(key, value)
            if key in ("-K", "--config", "-e", "--execute") and low in ("curl", "wget") and (
                    key != "-e" or low == "wget"):
                self.add("unknown", "unknown", f"{low} takes more options from {value or 'a file'}")
        if low in ("wget", "aria2c", "axel") and not outs and not any(
                k in ("--spider", "-O") or (k == "-O" and v == "-") for k, v in pairs):
            outs.append("*")
        if low == "wget" and any(k == "-O" and v == "-" for k, v in pairs):
            outs = [o for o in outs if o != "*"]
        return outs, reads, sends
    def git(self, texts: list[str | None]) -> None:
        if any(t is None for t in texts):
            self.add("unknown", "unknown", "runs git with computed arguments")
            return
        lowered = [t.lower() for t in texts]
        if any(t in ("-c", "--config-env", "--exec-path") or t.startswith(("--upload-pack", "--receive-pack",
                                                                            "--exec=", "--config-env="))
               for t in lowered):
            self.add("hidden", "hidden", "runs git with settings given on the command line, which can run programs")
        elif set(lowered) & GIT_NET or any("://" in t or t.startswith("--remote") for t in lowered):
            self.add("network", "net", f"runs git {' '.join(texts)[:80]}", host="git", sends="push" in lowered,
                     name=f"git {' '.join(texts)}"[:120])
        else:
            # Local git still runs the repository's own hooks and filters: a program run, as read.py has it.
            self.add("program", "program", f"runs git {' '.join(texts)[:80]}", name=f"git {' '.join(texts)}"[:160],
                     args=list(texts))

    def open(self, low: str, texts: list[str | None]) -> None:
        if any(t is None for t in texts):
            self.add("unknown", "program", f"{low} opens something whose name is computed")
            return
        if low == "gio" and texts[:1] != ["open"]:
            self.add("unknown", "unknown", f"runs gio {' '.join(texts)[:60]}")
            return
        if any(t in ("-a", "-b", "--args", "-e", "-t") for t in texts):
            self.add("program", "program", f"opens a program: {' '.join(texts)[:100]}", name=" ".join(texts)[:160])
            return
        for target in [t for t in texts[1 if low == "gio" else 0:] if not t.startswith("-")]:
            scheme = re.match(r"^([a-z][a-z0-9+.-]+):", target, re.IGNORECASE)
            if scheme and scheme.group(1).lower() in ("http", "https"):
                host = (urlsplit(target).hostname or "").lower()
                if host and _local_host(host):
                    self.add("system", "loopback", f"opens this computer's own services at {host}")
                else:
                    self.add("network", "browse", f"opens {target[:120]} in the browser", host=host or target[:40],
                             sends=True)
                continue
            if scheme:
                self.add("program", "program", f"{low} opens {target[:120]}", name=target[:160])
                continue
            place = self.resolve(target)
            if place is None:
                self.add("unknown", "program", f"{low} opens something in a folder known only as it runs")
            elif target.lower().rstrip("/").endswith(OPEN_RISKY_POSIX):
                self.add("program", "program", f"{low} runs {target}", name=target[:160], paths=[place])
            else:
                self.touch("read", "open", f"opens {place} in its own program", [place],
                           name=posixpath.basename(place))


    def container(self, base: str, texts: list[str | None]) -> None:
        """docker and its kind: a program run, unless given the computer's own rights."""
        joined = _short(texts)
        if re.search(r"--privileged|--pid[= ]host|--net(work)?[= ]host|--cap-add|-v\s*/:|--volume[= ]/:|--device",
                     joined):
            self.add("elevate", "elevate", f"runs {base} with the computer's own rights")
        else:
            self.add("program", "program", f"runs {base} {joined[:80]}", name=f"{base} {joined}"[:160])


def _fetch_options(low: str, texts: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """(each option with its value, the addresses) of a fetch's words; httpie's words after the address are
    items ("item", word)."""
    shorts = CURL_VALUES if low == "curl" else WGET_VALUES if low == "wget" else ("-o", "-d", "-P")
    pairs, urls, n = [], [], 0
    while n < len(texts):
        t = texts[n]
        nxt = texts[n + 1] if n + 1 < len(texts) else ""
        if t.startswith("--"):
            key, eq, value = t.partition("=")
            if eq:
                pairs.append((key, value))
            elif key in FETCH_LONG:
                pairs.append((key, nxt))
                n += 1
            else:
                pairs.append((key, ""))
        elif t.startswith("-") and len(t) > 1:
            bundle, took = _short_options(t, nxt, shorts)
            pairs += bundle
            n += took
        elif low in ("http", "https", "xh") and urls:
            pairs.append(("item", t))
        else:
            urls.append(t)
        n += 1
    return pairs, urls


def _short_options(word: str, nxt: str, shorts) -> tuple[list[tuple[str, str]], int]:
    """The options in one bundle of short ones (-sSLo out), and whether the last took the next word (1) or not."""
    pairs = []
    for i, c in enumerate(word[1:], 1):
        if f"-{c}" in shorts:
            pairs.append((f"-{c}", word[i + 1:] or nxt))
            return pairs, 0 if word[i + 1:] else 1
        pairs.append((f"-{c}", ""))
    return pairs, 0


def _sent_file(key: str, value: str) -> list[str]:
    """The file a sending option names with @ (-d @body.json), read to send."""
    at = value.split("@", 1)[1] if "@" in value and key not in ("--data-raw", "-u", "--user") else ""
    if at and at != "-" and key not in ("-H", "--header", "-A", "--user-agent", "-e", "--referer"):
        return [at.split(";")[0]]
    return []
