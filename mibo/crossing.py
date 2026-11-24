"""The gate between the compartments the character works across: the web (pages, messages, mail, MCP servers'
answers), this computer (files, commands, other programs' windows, past chats) and the person's own chat.

What a tool brings back from the web or this computer is material, never an instruction: only the person's own
message typed in the app's chat box asks for anything or answers a question (cardwait.py). Nothing here relies on
the model telling an injection from a request; it keeps a fooled model from causing a loss:
- the turn keeps what material it read (`Read`, on the turn's ChatLookups), and the turn record carries its summary
  to the gates in the app's page (`turn_read`);
- after the turn read material, an act that sends something out (a message, a post, a comment, a like or follow, a
  form, an upload, a program's send) to a place the person did not name is asked, whatever the reviewer says
  (`held`, from review.decide); in the app's browser the page itself is outside material, always;
- a command whose text arrives verbatim from material read in the turn, or that runs a script written from it, is
  asked (`Read.verbatim`, `Read.runs_written`); a program or script downloaded from the web is never opened or run
  (`downloaded`);
- a standing request acts only within the scope the person stored (`within`), and a change that widens the
  character's own permissions takes effect only on the person's own words (`widening`).
Model keys, the browser pane's profile and the app's own home are readable by no tool (shell/grants.py, Places).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .review import _compact, _fold

OUTSIDE, LOCAL = "outside", "local"
# What each tool's result is: outside material (the web, a third party) or local material (this computer, the
# person's own record). A tool that reads mid-call calls Read.saw itself; an MCP server's answer is outside material.
MATERIAL = {
    "web_search": OUTSIDE, "read_page": OUTSIDE, "read_with_their_session": OUTSIDE, "find_on_site": OUTSIDE,
    "read_messages": OUTSIDE,
    # open gives a first look of what it opened out of sight, a page as often as a file.
    "bring_find": OUTSIDE, "open": OUTSIDE, "look": OUTSIDE, "act": OUTSIDE,
    "pages_they_read": LOCAL, "search_past_chats": LOCAL, "read_file": LOCAL, "list_files": LOCAL,
    "search_files": LOCAL, "use_computer": LOCAL, "use_program": LOCAL,
    # A skill is a file on this computer, often one fetched from the skills market: its commands are material too.
    "use_skill": LOCAL,
}
# The material text a turn keeps for the verbatim check, newest last.
KEPT_CHARS = 400_000
# A command, or one line of it, at least this long found inside material read is taken as coming from there.
VERBATIM_MIN = 12
# What runs when opened: programs, installers, scripts and their shortcuts.
RUNNABLE = (".exe", ".msi", ".msix", ".appx", ".bat", ".cmd", ".com", ".scr", ".pif", ".ps1", ".psm1", ".vbs", ".vbe",
            ".js", ".jse", ".wsf", ".wsh", ".hta", ".lnk", ".url", ".jar", ".py", ".pyw", ".sh", ".reg", ".cpl",
            ".dll", ".application", ".appref-ms")
# Windows' zones for a file's Mark of the Web: 3 the internet, 4 restricted sites.
WEB_ZONES = ("3", "4")
# The readings of an outward act whose destination is checked, per area (the gates' kinds before review.judged). A
# bare press, whose name says no sending, is the reviewer's.
SENDS = {"browser": frozenset({"send", "comment", "like", "post", "submit", "outward", "upload"}),
         "programs": frozenset({"send", "post", "submit", "outward"})}
# Readings whose recipient must be named too, not only the site.
TO_SOMEONE = frozenset({"send", "upload"})


def _squeeze(text: str) -> str:
    return " ".join(_fold(text).split())


@dataclass
class Read:
    """The material one turn has read: where outside and local material came from, its text for the verbatim check,
    and the scripts written from it."""
    outside: list[str] = field(default_factory=list)
    local: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    scripts: set[str] = field(default_factory=set)

    def saw(self, material: str, where: str = "", text: str = "") -> None:
        """One read of `material` (OUTSIDE or LOCAL) from `where`, with the text it brought."""
        places = self.outside if material == OUTSIDE else self.local
        places.append(str(where or material)[:200])
        if text:
            self.texts.append(_squeeze(text))
            while sum(map(len, self.texts)) > KEPT_CHARS and len(self.texts) > 1:
                self.texts.pop(0)

    def summary(self) -> dict:
        """What the turn record carries to the gates: the places each kind of material came from."""
        return {OUTSIDE: list(dict.fromkeys(self.outside))[-20:], LOCAL: list(dict.fromkeys(self.local))[-20:]}

    def verbatim(self, text: str, words: str = "") -> bool:
        """`text` (a command, a script), whole or one of its lines, is found in material read this turn and not in
        the person's own `words`."""
        said = _squeeze(words)
        whole = _squeeze(text)
        parts = [whole, *(_squeeze(line) for line in re.split(r"[\r\n;]+", str(text or "")))]
        return any(len(part) >= VERBATIM_MIN and part not in said and any(part in seen for seen in self.texts)
                   for part in dict.fromkeys(parts))

    def wrote(self, path: str, content: str, words: str = "") -> None:
        """A file written this turn: a script whose text came from material read is remembered by its name."""
        if os.path.splitext(path)[1].lower() in RUNNABLE and self.verbatim(content, words):
            self.scripts.add(os.path.basename(path).casefold())

    def runs_written(self, command: str) -> bool:
        """`command` names a script this turn wrote from material read."""
        said = _fold(command)
        return any(name in said for name in self.scripts)


def turn_read(workspace) -> dict:
    """The material the turn under way has read, as its record carries it ({OUTSIDE: [...], LOCAL: [...]})."""
    from .cardwait import doing
    read = doing(workspace).get("read")
    return read if isinstance(read, dict) else {}


def _site_names(site: str) -> tuple[list[str], list[str]]:
    """What names a site: its full host and its registrable host, and the names the app knows for it (B站 for
    bilibili.com, 微博 for weibo.com, DeepL for deepl.com: web/signin_sites.json, web/seeds.json, web/places.json,
    platforms.py). Never a bare label of its address: "deepl" names deepl.com because the app knows that name for it,
    not deepl.xyz."""
    import json

    from .platforms import PLATFORMS
    from .resolve import PLACES
    from .situation import site_of
    from .web import signin, sites
    # The app's names are its own host's alone (douyin.example is not 抖音); a platform's other domains are the
    # platform (iesdouyin.com is Douyin's share pages).
    key = site_of(site) or site
    names = []
    for row in signin.hints():
        if row["site"] == key:
            names += [row["name"].get("zh", ""), row["name"].get("en", ""), *row.get("also", [])]
    names += [seed["name"] for host, seed in sites.SEEDS.items() if host == key]
    names += [row["name"] for row in json.loads(PLACES.read_text(encoding="utf-8")) if site_of(row["home"]) == key]
    names += [p.zh for p in PLATFORMS.values() if p.key == key] + [p.en for p in PLATFORMS.values() if p.key == key]
    # A place given by a name (微博 in a standing request's scope) is that name.
    hosts = [h for h in dict.fromkeys((site, key)) if h and "." in h]
    return hosts, [n for n in dict.fromkeys([*names, *([] if "." in site else [site])]) if n]


def _says(name: str, said: str) -> bool:
    """A known name in the person's words as a whole: a Latin one between word boundaries, at least three letters
    ("ate" is not in "translate"); one with other letters (B站, 微博) whole, spaces aside ("B 站")."""
    name = " ".join(_fold(name).split())
    if name.isascii():
        return len(_compact(name)) >= 3 and bool(re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", said))
    return len(name) >= 2 and "".join(name.split()) in "".join(said.split())


def named(place: str, words, site: bool = False) -> bool:
    """Whether the person's own `words` (a string or a list of their messages) name `place`: a site by its full or
    registrable host or a name the app knows for it (with `site`, `_site_names`), else a recipient, a program, a window
    or a file by its name, a part of it between dashes, or a path's last part."""
    said = _fold(" ".join(words) if isinstance(words, (list, tuple)) else words)
    if not str(place or "").strip() or not said.strip():
        return False
    if site:
        hosts, known = _site_names(place.split(":")[0].strip().lower())
        return any(re.search(rf"(?<![\w.-]){re.escape(_fold(h))}(?![\w-]|\.\w)", said) for h in hosts) or any(
            _says(n, said) for n in known)
    names = [place, *re.split(r"\s+[—–-]\s+", place), os.path.basename(place.rstrip("\\/"))]
    for name in names:
        name = _fold(name).strip()
        if len(_compact(name)) >= 2 and (name in said or _compact(name) in _compact(said)):
            return True
    return False


# Quotes a person puts round words they want typed as they are.
QUOTES = (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』"), ("《", "》"), ("`", "`"))


def own_words(text: str, words) -> bool:
    """Whether `text` is the person's own words of `words`, to be typed as they are: quoted there, or a whole span of
    them between natural boundaries at least two characters long in Chinese, Japanese or Korean and four in other
    scripts (你好 in 将中文你好翻译成英文; never "1" or "ok" found inside other words)."""
    said = _fold(" ".join(words) if isinstance(words, (list, tuple)) else words)
    t = " ".join(_fold(text).split())
    if not t:
        return False
    if any(f"{a}{t}{b}" in said for a, b in QUOTES):
        return True
    if len(t) < (2 if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", t) else 4):
        return False
    edge = r"[a-z0-9]"
    head = rf"(?<!{edge})" if re.match(edge, t) else ""
    tail = rf"(?!{edge})" if re.match(edge, t[-1]) else ""
    return bool(re.search(head + re.escape(t) + tail, " ".join(said.split())))


def held(area: str, action: dict, words, read: dict) -> str:
    """Why code asks about an outward act whatever the reviewer says, or "": the turn read material ("outside", or
    "local" when only this computer's) and the act goes to a site, a recipient or a window the person's own words do
    not name. In the app's browser the page is outside material, always."""
    kind = str(action.get("kind") or "")
    if kind not in SENDS.get(area, ()):
        return ""
    outside = area == "browser" or bool(read.get(OUTSIDE))
    if not (outside or read.get(LOCAL)):
        return ""
    targets = [str(t) for t in action.get("target") or [] if str(t).strip()]
    if area == "browser":
        unnamed = not named(str(action.get("where") or ""), words, site=True) or (
            kind in TO_SOMEONE and any(not named(t, words) for t in targets))
    else:
        # A program's window, "Program — title": the title's parts besides the program's own name (the chat, the
        # document), or the program when its title says nothing else.
        program, _, title = str(action.get("where") or "").partition(" — ")
        parts = [p for p in re.split(r"\s+[—–-]\s+", title) if p.strip() and _fold(p) != _fold(program)] or [program]
        unnamed = not any(named(p, words) for p in parts)
    if not unnamed:
        return ""
    return OUTSIDE if outside else LOCAL


def downloaded(path: str) -> bool:
    """A program or a script that came from the web: a runnable file, or one that runs code or changes settings when
    its own program opens it (a macro document, a .reg: pstables.OPEN_RISKY), whose Mark of the Web names the internet
    zone (Windows' Zone.Identifier, the browsers' origin attribute elsewhere)."""
    from .shell.pstables import OPEN_RISKY
    if os.path.splitext(str(path))[1].lower() not in RUNNABLE + OPEN_RISKY:
        return False
    try:
        with open(f"{path}:Zone.Identifier", encoding="utf-8", errors="replace") as mark:
            zone = re.search(r"ZoneId\s*=\s*(\d+)", mark.read())
        return bool(zone) and zone.group(1) in WEB_ZONES
    except OSError:
        pass
    getxattr = getattr(os, "getxattr", None)
    if getxattr is None:
        return False
    try:
        return bool(getxattr(path, "user.xdg.origin.url"))
    except OSError:
        return False


def within(scope: dict, act: dict) -> bool:
    """Whether a standing request's stored scope covers one act, so it runs with no question. `scope` is what the
    person's own words set up: {"area": browser | programs | tools | commands, "kinds": the readings it may do (send,
    post, comment, like, submit...; empty for any non-costly one), "places": the sites, recipients, programs or
    folders it may act on}. `act` is {"area", "kind", "where", "target"} as the gates describe it. A costly act is
    never covered, and a place the scope does not name is not either."""
    from .cardwait import costly
    kind = str(act.get("kind") or "")
    if costly(kind) or act.get("area") != scope.get("area"):
        return False
    kinds = scope.get("kinds") or []
    if kinds and kind not in kinds:
        return False
    places = [str(p) for p in scope.get("places") or [] if str(p).strip()]
    site = act.get("area") == "browser"
    targets = [str(t) for t in act.get("target") or [] if str(t).strip()]
    return named(str(act.get("where") or ""), places, site=site) and all(named(t, places) for t in targets)


def widening(change: dict, words, read: dict) -> bool:
    """Whether a change that widens the character's own permissions (the acting mode, automatic review, the sites it
    may read, a folder or program granted) must be asked before it takes effect: always after the turn read outside
    material; otherwise unless the person's own words of this turn name it. `change["names"]` holds the words that
    name the setting or its new value (自动审查, a folder's path, a site), any one of which counts. Asked with the risk
    "widen" (cardwait.ALONE), which no other yes reaches."""
    if read.get(OUTSIDE):
        return True
    return not any(named(str(name), words) or named(str(name), words, site=True) for name in change.get("names") or [])


def widening_in(workspace, change: dict) -> bool:
    """`widening` for the turn under way in the app: the person's own message of this turn (an earlier one naming
    the setting is no request now) and the material the turn read."""
    from .acting import asked
    return widening(change, [m["text"] for m in asked(workspace)][-1:], turn_read(workspace))
