"""The skill market: a catalog of public skills, each entry pointing at where the skill lives, never a copy of it.

The catalog is one JSON file (data/market/skills.json, shipped as a snapshot and refreshed at most once a day from
CATALOG_URL through the guarded fetch). It is data from the network: an entry that does not hold the fixed shape,
or points anywhere but a public https git host, is dropped, and nothing in it is read as an instruction.

Installing an entry fetches its repository's archive at the entry's commit from its own host, takes the skill's
folder out of it, checks the folder's hash against the entry, scans what arrived, and writes it through the store's
add path with the entry recorded, so an update can be told. Nothing in it is run. An entry whose licence does not
allow it, or whose scan finds a high risk, is never installed from here; a repository with no stated licence is
installed only when the person agreed to that on the page.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import pick, store
from ..storage import atomic_write_text

logger = logging.getLogger("mibo.skills")

# Where the app refreshes the catalog from: the present repository, which is to be renamed.
CATALOG_URL = "https://raw.githubusercontent.com/wangkant/mibo/main/data/market/skills.json"
REFRESH_S = 24 * 3600
MAX_CATALOG = 8 * 1024 * 1024
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_PREVIEW = 512 * 1024
CATEGORIES = ("documents", "writing", "research", "data", "design", "development", "productivity", "media",
              "learning", "life", "tools")
RISKS = ("none", "low", "high")
# Licences that allow use and redistribution (share-alike ones included), as tools/skillmarket/build.py reads them.
OPEN = frozenset({"MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense",
                  "CC0-1.0", "CC-BY-4.0", "BSL-1.0", "Zlib", "CC-BY-SA-4.0", "GPL-2.0", "GPL-3.0", "AGPL-3.0",
                  "LGPL-2.1", "LGPL-3.0", "MPL-2.0"})
FITS = ("ready", "partial", "no")
# Public git hosts an entry may point at, with the archive of a repository at a commit and a file's raw text.
HOSTS = {
    "github.com": (lambda repo, sha: f"https://codeload.github.com/{repo}/zip/{sha}",
                   lambda repo, sha, path: f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"),
    "gitlab.com": (lambda repo, sha: f"https://gitlab.com/{repo}/-/archive/{sha}/{repo.rsplit('/', 1)[1]}-{sha}.zip",
                   lambda repo, sha, path: f"https://gitlab.com/{repo}/-/raw/{sha}/{path}"),
    "codeberg.org": (lambda repo, sha: f"https://codeberg.org/{repo}/archive/{sha}.zip",
                     lambda repo, sha, path: f"https://codeberg.org/{repo}/raw/commit/{sha}/{path}"),
    "gitee.com": (lambda repo, sha: f"https://gitee.com/{repo}/repository/archive/{sha}.zip",
                  lambda repo, sha, path: f"https://gitee.com/{repo}/raw/{sha}/{path}"),
}
_REPO = re.compile(r"^[\w.-]+(?:/[\w.-]+){1,4}$")
_ID = re.compile(r"^[\w.-]{1,80}/[\w.-]{1,80}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_PATH = re.compile(r"^[\w.@+ -]+(?:/[\w.@+ -]+)*$")
_UA = {"User-Agent": "Mibo"}
_lock = asyncio.Lock()


# ------------------------------------------------------------------- hashing

def folder_hash(files: dict[str, bytes]) -> str:
    """The hash a catalog entry records for a skill's folder: sha256 over one line per file, sorted by the file's
    path inside the folder (POSIX, UTF-8), each line `path NUL sha256-of-its-bytes-in-hex LF`."""
    total = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.encode("utf-8")):
        total.update(path.encode("utf-8") + b"\0" + hashlib.sha256(files[path]).hexdigest().encode() + b"\n")
    return total.hexdigest()


# ---------------------------------------------------------------------- scan

# What a skill's files may hold that matters before it is installed: (code, high, pattern). A skill's text is
# guidance the model reads, and its scripts run only through the command gate; these are what would turn either
# against the person.
_SCRIPT = re.compile(r"(?<!\.d)\.(py|js|mjs|cjs|ts|sh|bash|zsh|ps1|psm1|bat|cmd|rb|pl|php|lua)$", re.I)
_CHECKS = [(code, high, re.compile(p, re.I)) for code, high, p in (
    ("model_against_person", True,
     r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier|preceding|system) (?:instructions|messages|rules"
     r"|prompts?)|disregard (?:all |any )?(?:the |your )?(?:previous|prior|above|system) (?:instructions|rules|prompt)"
     r"|(?:do not|don't|never) (?:tell|inform|notify|alert|show) the (?:user|human|person|owner)(?! to\b| they\b)"
     r"|without (?:telling|informing|asking|notifying) the (?:user|human|person|owner)"
     r"|keep (?:this|it) (?:secret|hidden) from the (?:user|human|person)"
     r"|pretend (?:that )?(?:you are|to be) (?:the user|a human|the system|an? (?:admin|administrator|developer))"
     r"|pretend (?:that )?(?:the user|they) (?:has|have) (?:approved|agreed|confirmed)"
     r"|忽略(?:之前|以上|上面|先前|所有|系统)的?(?:指令|指示|说明|规则|提示)|不要(?:告诉|通知|告知|让)用户|瞒着用户|对用户隐瞒"
     r"|假装(?:你是用户|用户已|是系统)"),
    ("sends_data", True,
     r"webhook\.site|requestbin|pipedream\.net|ngrok(?:-free)?\.(?:io|app)|burpcollaborator|interact\.sh|\boast\."
     r"|discord(?:app)?\.com/api/webhooks|api\.telegram\.org/bot|hooks\.slack\.com/services|transfer\.sh"
     r"|(?:send|upload|post|forward) (?:all |the )?(?:user'?s? )?(?:files|credentials|cookies|tokens|api keys"
     r"|passwords|browser history|env(?:ironment)? variables|\.env) to "),
    ("encoded_run", True,
     r"(?:eval|exec)\s*\(\s*(?:atob|base64\.b64decode|bytes\.fromhex|Buffer\.from|codecs\.decode)"
     r"|FromBase64String[^\n]*(?:iex|Invoke-Expression)|base64 (?:-d|--decode)[^\n|]*\|\s*(?:ba|z)?sh\b"
     r"|marshal\.loads|-EncodedCommand\b|powershell[^\n]* -enc\s"),
    ("download_run", True,
     r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b|(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^\n|]*"
     r"\|\s*(?:iex|Invoke-Expression)\b|Invoke-Expression\s*\(?\s*\(?\s*(?:New-Object|iwr|irm|Invoke-WebRequest)"
     r"|(?:urlopen|requests\.get)\([^\n]*\)[^\n]*\b(?:exec|eval)\("),
    ("credentials", True,
     r"\.ssh[/\\](?:id_|authorized_keys)|\bid_(?:rsa|ed25519)\b|\.aws[/\\]credentials|(?-i:Login Data|Local State)"
     r"|cookies\.sqlite|Network\.get(?:All)?Cookies|Storage\.getCookies|User Data[/\\]Default[/\\](?:Network[/\\])?Cookies|browser[_-]?cookie3|pycookiecheat"
     r"|chrome-cookies-secure|find-generic-password|CredRead|cmdkey /list|wallet\.dat|\.git-credentials"),
    ("system_settings", True,
     r"\breg(?:\.exe)? add\b|Set-ItemProperty[^\n]*HK(?:LM|CU)|CurrentVersion\\+Run\b|schtasks(?:\.exe)? /create"
     r"|\bcrontab -|launchctl (?:load|bootstrap)|systemctl (?:enable|disable)|Set-MpPreference|netsh (?:advfirewall"
     r"|firewall)|\bbcdedit\b|Set-ExecutionPolicy\s+(?:Unrestricted|Bypass)"),
    ("encoded_blob", False, r"[A-Za-z0-9+/]{600,}={0,2}"),
    ("installs_packages", False,
     r"\b(?:pip3? install|npm (?:i|install)\b|npx -y\b|pnpm add|yarn add|brew install|apt(?:-get)? install"
     r"|winget install|choco install|cargo install|go install|sudo\b)"),
)]
# A skill that warns the model about injected text quotes it ("ignore previous instructions"): an example to refuse,
# not an instruction to the model.
_QUOTED = re.compile(r"[\"'“‘「『`(]\s*$")
_WARNS = re.compile(r"inject|not instructions|as data|flag it|malicious|disguis|steer you|not (?:system )?directives"
                    r"|伪装|注入|不是指令|视为数据|一律", re.I)


def _found(code: str, pattern: re.Pattern, text: str) -> bool:
    for m in pattern.finditer(text):
        if code == "model_against_person" and _QUOTED.search(text[max(0, m.start() - 3):m.start()]) \
                and _WARNS.search(text[max(0, m.start() - 300):m.end() + 300]):
            continue
        return True
    return False


_NETWORK = re.compile(r"requests\.(?:get|post)|urllib\.request|\bfetch\(|axios|http\.request|https?\.get\(|\bcurl |"
                      r"\bwget |Invoke-WebRequest|Invoke-RestMethod|httpx\.", re.I)
_DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+")


def scan(files: dict[str, bytes]) -> dict:
    """The risk of a skill's files and why: high for anything in _CHECKS marked so, low for scripts, packages
    installed, the network or a long encoded blob, none otherwise. Notes are `code` or `code:path`."""
    notes: dict[str, str] = {}
    scripts = sorted(p for p in files if _SCRIPT.search(p))
    if scripts:
        notes["scripts"] = scripts[0]
    for path in sorted(files):
        raw = files[path]
        if b"\0" in raw[:4096] or len(raw) > 4 * 1024 * 1024:
            continue
        text = raw.decode("utf-8", "replace")
        # Pictures inlined as data: addresses are not hidden code.
        plain = _DATA_URI.sub("", text)
        for code, _, pattern in _CHECKS:
            if code not in notes and _found(code, pattern, plain if code == "encoded_blob" else text):
                notes[code] = path
        if path in scripts and "network" not in notes and _NETWORK.search(text):
            notes["network"] = path
    high = {code for code, is_high, _ in _CHECKS if is_high}
    risk = "high" if high & notes.keys() else "low" if notes else "none"
    order = [c for c, _, _ in _CHECKS] + ["scripts", "network"]
    return {"risk": risk, "notes": [f"{c}:{notes[c]}" for c in sorted(notes, key=order.index)]}


# ------------------------------------------------------------------- catalog

def _text(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def _pair(value, limit: int) -> dict:
    value = value if isinstance(value, dict) else {}
    return {"zh": _text(value.get("zh", ""), limit), "en": _text(value.get("en", ""), limit)}


def _https(url, host: str = "") -> str:
    url = str(url or "") if isinstance(url, str) else ""
    m = re.match(r"^https://([a-z0-9.-]+)(?:/[^\s\"'<>]*)?$", url, re.I)
    if not m or (host and m.group(1).lower().removeprefix("www.") != host):
        return ""
    return url[:500]


def entry(raw) -> dict | None:
    """One catalog entry in the fixed shape, its strings clipped, or None when it does not hold that shape or
    points anywhere but a public https git host."""
    if not isinstance(raw, dict):
        return None
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    licence = raw.get("licence") if isinstance(raw.get("licence"), dict) else {}
    found = raw.get("scan") if isinstance(raw.get("scan"), dict) else {}
    needs = raw.get("needs") if isinstance(raw.get("needs"), dict) else {}
    popular = raw.get("popularity") if isinstance(raw.get("popularity"), dict) else {}
    ident, name = str(raw.get("id") or ""), str(raw.get("name") or "")
    repo, path, sha = str(source.get("repo") or ""), str(source.get("path") or "").strip("/"), str(
        source.get("commit") or "")
    url = str(source.get("url") or "")
    # The page a person opens must be the repository's own, on the host the archive comes from.
    link = url.lower().removeprefix("https://").removeprefix("www.") if url.startswith("https://") else ""
    host = link.split("/", 1)[0]
    if (not _ID.match(ident) or not store.NAME.match(name) or len(name) > store.MAX_NAME or host not in HOSTS
            or not _REPO.match(repo) or ".." in repo.split("/") or not _https(url, host)
            or not (link == f"{host}/{repo.lower()}" or link.startswith(f"{host}/{repo.lower()}/"))
            or (path and (not _PATH.match(path) or ".." in path.split("/"))) or not _SHA.match(sha)
            or not _HASH.match(str(raw.get("hash") or "")) or found.get("risk") not in RISKS
            or raw.get("fit") not in FITS):
        return None
    spdx = _text(licence.get("spdx", ""), 60) or "NONE"
    count = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    return {
        "id": ident, "name": name, "title": _pair(raw.get("title"), 60), "about": _pair(raw.get("about"), 300),
        "publisher": _text(raw.get("publisher", ""), 80) or repo.split("/")[0],
        "source": {"host": host, "repo": repo, "path": path, "commit": sha, "url": _https(url, host)},
        "licence": {"spdx": spdx, "url": _https(licence.get("url")),
                    "installable": licence.get("installable") is True, "note": _text(licence.get("note", ""), 300)},
        "category": raw.get("category") if raw.get("category") in CATEGORIES else "tools",
        "tags": [_text(t, 30) for t in (raw.get("tags") if isinstance(raw.get("tags"), list) else [])[:12]
                 if _text(t, 30)],
        "needs": {"scripts": needs.get("scripts") is True,
                  "runtimes": [_text(t, 20) for t in (needs.get("runtimes") or [])[:6] if _text(t, 20)]
                  if isinstance(needs.get("runtimes"), list) else [],
                  "tools": [_text(t, 40) for t in (needs.get("tools") or [])[:12] if _text(t, 40)]
                  if isinstance(needs.get("tools"), list) else []},
        "fit": raw["fit"], "fit_note": _text(raw.get("fit_note", ""), 300),
        "popularity": {"stars": count(popular.get("stars")), "installs": count(popular.get("installs")),
                       "as_of": _text(popular.get("as_of", ""), 30)},
        "hash": raw["hash"],
        "scan": {"risk": found["risk"], "notes": [_text(n, 300) for n in (found.get("notes") or [])[:12]
                                                  if _text(n, 300)] if isinstance(found.get("notes"), list) else []},
        "updated": _text(raw.get("updated", ""), 30),
    }


def _catalog(data) -> dict | None:
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("skills"), list):
        return None
    entries, seen = [], set()
    for raw in data["skills"][:5000]:
        one = entry(raw)
        if one and one["id"] not in seen:
            seen.add(one["id"])
            entries.append(one)
    sources = [{"id": _text(s.get("id", ""), 80), "name": _text(s.get("name", ""), 80), "url": _https(s.get("url")),
                "note": _text(s.get("note", ""), 300)}
               for s in (data.get("sources") if isinstance(data.get("sources"), list) else []) if isinstance(s, dict)]
    return {"version": 1, "built_at": _text(data.get("built_at", ""), 40), "sources": sources[:200],
            "skills": entries}


def snapshot_path() -> Path:
    from ..home import resource
    return resource("data", "market", "skills.json")


def _cache_path(home: Path) -> Path:
    return store._records_path(home).parent / "market" / "skills.json"


_loaded: dict[tuple, dict] = {}


def _read(path: Path) -> dict | None:
    try:
        info = path.stat()
    except OSError:
        return None
    key = (str(path), info.st_mtime_ns, info.st_size)
    if key not in _loaded:
        try:
            _loaded.clear()
            _loaded[key] = _catalog(json.loads(path.read_text(encoding="utf-8"))) or {}
        except (OSError, ValueError):
            _loaded[key] = {}
    return _loaded[key] or None


def catalog(home: Path) -> tuple[dict, str]:
    """(the catalog, "live" or "snapshot" or "none"): the refreshed one when it reads and is not older than the
    snapshot, else the snapshot shipped with the app."""
    live, shipped = _read(_cache_path(home)), _read(snapshot_path())
    if live and (not shipped or live["built_at"] >= shipped["built_at"]):
        return live, "live"
    if shipped:
        return shipped, "snapshot"
    return {"version": 1, "built_at": "", "sources": [], "skills": []}, "none"


def _refresh_state(home: Path) -> dict:
    try:
        data = json.loads((_cache_path(home).parent / "refresh.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def refresh(home: Path, force: bool = False) -> bool:
    """Fetches the catalog from CATALOG_URL at most once a day; True when a new one was kept."""
    from ..ingestion import safe_fetch_url
    state = _refresh_state(home)
    if not force and time.time() - float(state.get("tried") or 0) < REFRESH_S:
        return False
    place = _cache_path(home)
    place.parent.mkdir(parents=True, exist_ok=True)
    result = await safe_fetch_url(CATALOG_URL, timeout=30, max_wire_bytes=MAX_CATALOG, max_decoded_bytes=MAX_CATALOG,
                                  headers=_UA, max_redirects=3)
    ok = False
    if result is not None:
        try:
            ok = _catalog(json.loads(result.content.decode("utf-8"))) is not None
        except ValueError:
            ok = False
        if ok:
            atomic_write_text(place, result.content.decode("utf-8"))
    atomic_write_text(place.parent / "refresh.json", json.dumps({"tried": time.time(), "ok": ok}))
    if not ok:
        logger.info("[Skills] the market catalog was not refreshed")
    return ok


def by_id(home: Path, ident: str) -> dict | None:
    return next((e for e in catalog(home)[0]["skills"] if e["id"] == ident), None)


# ------------------------------------------------------------------ installed

def installed(home: Path) -> dict[str, dict]:
    """Entries installed from the market: id -> {folder, commit, hash, at}, for folders still there."""
    rows = store.records(home).get("sources") or {}
    there = store.skills_dir(home)
    return {row["market"]["id"]: {"folder": folder, **row["market"]} for folder, row in rows.items()
            if isinstance(row, dict) and isinstance(row.get("market"), dict) and (there / folder).is_dir()}


def can_install(one: dict, unlicensed_ok: bool) -> str:
    """"" when the entry may be installed from here, else the reason's code."""
    if one["scan"]["risk"] == "high":
        return "market_high_risk"
    # The flag is taken only with a licence that allows use and redistribution.
    if one["licence"]["installable"] and one["licence"]["spdx"] in OPEN:
        return ""
    if one["licence"]["spdx"].upper() == "NONE":
        return "" if unlicensed_ok else "market_unlicensed"
    return "market_not_installable"


def view(home: Path) -> dict:
    """What the page shows: the catalog, how it was got, and per entry whether it is installed or has an update."""
    data, came = catalog(home)
    have = installed(home)
    names = {s.name for s in store.all_skills(home)}
    state = _refresh_state(home)
    skills = []
    for one in data["skills"]:
        mine = have.get(one["id"])
        skills.append({**one, "installed": bool(mine), "folder": mine["folder"] if mine else "",
                       "installed_commit": mine["commit"] if mine else "",
                       "update": bool(mine) and (mine["commit"], mine["hash"]) != (one["source"]["commit"], one["hash"]),
                       "name_taken": not mine and one["name"] in names,
                       # Why it may not be installed from here ("" when it may, after a word on a missing licence).
                       "blocked": can_install(one, True)})
    return {"built_at": data["built_at"], "from": came, "refresh_failed": state.get("ok") is False,
            "sources": data["sources"], "categories": categories(), "skills": skills}


def categories() -> dict:
    """The fixed categories' names in Chinese and English, kept beside the catalog."""
    from ..home import resource
    return json.loads(resource("data", "market", "categories.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------- fetching

async def _get(url: str, limit: int, timeout: float = 60):
    from ..ingestion import safe_fetch_url
    return await safe_fetch_url(url, timeout=timeout, max_wire_bytes=limit, max_decoded_bytes=limit, headers=_UA,
                                max_redirects=5)


def folder_files(data: bytes, path: str) -> dict[str, bytes]:
    """The files of one folder of a host's repository archive, by their paths inside that folder."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    top = store.archive_top(data)
    inside = PurePosixPath(top, path) if path else PurePosixPath(top)
    files: dict[str, bytes] = {}
    size = 0
    for info in archive.infolist():
        member, plain = store._member_path(info)
        if info.is_dir() or not store._under(member, inside) or member == inside:
            continue
        if not plain:
            raise ValueError("skill_bad_archive")
        size += info.file_size
        if len(files) >= store.MAX_MEMBERS or size > store.MAX_UNPACKED or info.file_size > store.MAX_MEMBER:
            raise ValueError("skill_too_large")
        files[member.relative_to(inside).as_posix()] = archive.read(info)
    if store.SKILL_FILE not in files:
        raise ValueError("skill_none_found")
    return files


def zip_of(name: str, files: dict[str, bytes]) -> bytes:
    """A zip holding `files` in one folder `name`, for the store's add path."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(f"{name}/{path}", data)
    return out.getvalue()


async def _github_files(src: dict) -> dict[str, bytes] | None:
    """A GitHub folder at a commit file by file: its tree in one call of GitHub's API, then each file's raw bytes.
    A skill is small and its repository often is not (one holds 170 skills in a 250 MB archive). None when the API
    does not answer (its hourly limit, the network) or the tree is cut short; ValueError for what cannot be a
    skill's files."""
    from urllib.parse import quote
    where = f"{src['commit']}:{src['path']}" if src["path"] else src["commit"]
    result = await _get(f"https://api.github.com/repos/{src['repo']}/git/trees/{quote(where)}?recursive=1",
                        4 * 1024 * 1024, 30)
    if result is None:
        return None
    try:
        tree = json.loads(result.content)
        rows = [(str(r["type"]), str(r["mode"]), str(r["path"]), int(r.get("size") or 0)) for r in tree["tree"]]
    except (ValueError, LookupError, TypeError):
        return None
    if tree.get("truncated"):
        return None
    files: dict[str, bytes] = {}
    size = 0
    for kind, mode, rel, length in rows:
        if kind == "tree":
            continue
        # The archive's rules for what may be written here: plain files only, no links or nested repositories.
        if kind != "blob" or mode not in ("100644", "100755") or not store._member_path(zipfile.ZipInfo(rel))[1]:
            raise ValueError("skill_bad_archive")
        size += length
        if len(files) >= store.MAX_MEMBERS or size > store.MAX_UNPACKED or length > store.MAX_MEMBER:
            raise ValueError("skill_too_large")
        path = f"{src['path']}/{rel}" if src["path"] else rel
        got = await _get(HOSTS["github.com"][1](src["repo"], src["commit"], quote(path)), store.MAX_MEMBER, 60)
        if got is None:
            raise ValueError("market_fetch_failed")
        files[rel] = got.content
    return files


async def fetch(one: dict) -> dict[str, bytes]:
    """The entry's folder at its commit, from its own host; ValueError when it cannot be fetched or does not match
    the entry's hash. On GitHub file by file, else (and when GitHub's API does not answer) the repository's
    archive."""
    src = one["source"]
    files = await _github_files(src) if src["host"] == "github.com" else None
    if files is not None and folder_hash(files) != one["hash"]:
        # The entry was read from an archive, which leaves out what a repository marks export-ignore.
        files = None
    if files is None:
        result = await _get(HOSTS[src["host"]][0](src["repo"], src["commit"]), MAX_ARCHIVE, 120)
        if result is None or not result.content.startswith(b"PK"):
            raise ValueError("market_fetch_failed")
        try:
            files = await asyncio.to_thread(folder_files, result.content, src["path"])
        except zipfile.BadZipFile:
            raise ValueError("skill_bad_archive") from None
    if store.SKILL_FILE not in files:
        raise ValueError("skill_none_found")
    if folder_hash(files) != one["hash"]:
        logger.warning("[Skills] %s does not match its catalog hash", one["id"])
        raise ValueError("market_hash_mismatch")
    return files


async def install(home: Path, ident: str, unlicensed_ok: bool = False) -> str:
    """Installs or updates one entry; returns its folder name. ValueError with a code when it may not be or did not
    arrive whole."""
    one = by_id(home, ident)
    if one is None:
        raise ValueError("market_gone")
    # Updating one the person installed keeps their word on a missing licence.
    why = can_install(one, unlicensed_ok or ident in installed(home))
    if why:
        raise ValueError(why)
    async with _lock:
        files = await fetch(one)
        # What arrived is scanned again; the entry's own result is not trusted for this.
        if scan(files)["risk"] == "high":
            raise ValueError("market_high_risk")
        mine = installed(home).get(ident)
        folder = mine["folder"] if mine else one["name"]
        added = await asyncio.to_thread(
            store.install_zip, home, zip_of(folder, files), "market", one["source"]["url"], "", one["source"]["commit"],
            {"id": ident, "commit": one["source"]["commit"], "hash": one["hash"], "at": time.time()})
        # The catalog's titles, abouts and tags in both languages are its search words: no model call to make them.
        skill = next(s for s in store.all_skills(home) if s.folder.name == added[0])
        store.keep_words(home, skill, {"title_zh": one["title"]["zh"], "description_zh": one["about"]["zh"],
                                       "words": " ".join([*one["tags"], one["title"]["zh"], one["title"]["en"]])})
    logger.info("[Skills] %s installed from the market at %s", ident, one["source"]["commit"][:12])
    return added[0]


def remove(home: Path, ident: str) -> None:
    mine = installed(home).get(ident)
    if mine is None:
        raise ValueError("skill_gone")
    store.remove(home, mine["folder"])


# The page's detail view: the SKILL.md at the reviewed commit, and whether the folder changed since, kept a while.
_seen: dict[str, tuple[float, object]] = {}
SEEN_S = 6 * 3600


async def preview(one: dict) -> str | None:
    key = f"preview:{one['id']}:{one['source']['commit']}"
    if key in _seen:
        return _seen[key][1]
    src = one["source"]
    path = f"{src['path']}/{store.SKILL_FILE}" if src["path"] else store.SKILL_FILE
    result = await _get(HOSTS[src["host"]][1](src["repo"], src["commit"], path), MAX_PREVIEW, 30)
    if result is None:
        return None
    text = result.content.decode("utf-8", "replace")
    _seen[key] = (time.time(), text)
    return text


async def changed(one: dict) -> bool | None:
    """Whether the folder changed upstream after the reviewed commit; None when it cannot be told (another host,
    the network, GitHub's hourly limit)."""
    src = one["source"]
    if src["host"] != "github.com":
        return None
    key = f"changed:{one['id']}:{src['commit']}"
    hit = _seen.get(key)
    if hit and time.time() - hit[0] < SEEN_S:
        return hit[1]
    from urllib.parse import quote
    url = f"https://api.github.com/repos/{src['repo']}/commits?per_page=1" + (
        f"&path={quote(src['path'])}" if src["path"] else "")
    result = await _get(url, 256 * 1024, 20)
    if result is None:
        return None
    try:
        rows = json.loads(result.content)
        sha = rows[0]["sha"]
        date = str(rows[0]["commit"]["committer"]["date"])
    except (ValueError, LookupError, TypeError):
        return None
    # The entry's commit may be the repository's head when it was read, later than the folder's own last commit.
    moved = sha != src["commit"] and bool(one["updated"]) and date[:len(one["updated"])] > one["updated"]
    _seen[key] = (time.time(), moved)
    return moved


async def mark(home: Path, owner: str) -> bytes | None:
    """A GitHub publisher's own picture, kept on disk once fetched."""
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", owner):
        return None
    place = _cache_path(home).parent / "marks" / f"{owner.lower()}.png"
    try:
        return place.read_bytes()
    except OSError:
        pass
    result = await _get(f"https://github.com/{owner}.png?size=96", 512 * 1024, 20)
    if result is None or not result.content.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")):
        return None
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_bytes(result.content)
    return result.content


# --------------------------------------------------------------------- offers

@dataclass
class _Listed:
    """A catalog entry read as a skill by the picker."""
    name: str
    description: str
    words: str
    title_zh: str
    description_zh: str
    entry: dict = field(repr=False, default_factory=dict)


# An offer needs a far clearer fit than a skill the person installed: it interrupts the reply.
OFFER_SCORE = 7.0
OFFER_LEAD = 1.4
_ASKED = re.compile(r"(技能|skill).{0,12}(找|有没有|推荐|安装|装|install|find|recommend|is there|any)"  # copy: voice
                    r"|(找|有没有|推荐|安装|装|install|find|recommend|is there|any).{0,12}(技能|skill)", re.I)  # copy: voice
_listed: dict[tuple, list] = {}


def asked_for(said: str) -> bool:
    return bool(_ASKED.search(said or ""))


def offer_for(home: Path, said: str) -> dict | None:
    """The one market entry a message plainly fits, when no skill the person has does: installable, of no high
    risk, ready for this app, and not installed. Else None."""
    data, _ = catalog(home)
    key = (data["built_at"], len(data["skills"]))
    if key not in _listed:
        _listed.clear()
        _listed[key] = [_Listed(e["name"], e["about"]["en"], " ".join([*e["tags"], e["title"]["en"]]),
                                e["title"]["zh"], e["about"]["zh"], e) for e in data["skills"]
                        if can_install(e, False) == "" and e["fit"] == "ready"]
    have = store.usable(home)
    taken = set(installed(home)) | {s.name for s in store.all_skills(home)}
    ranked = pick.score([*have, *_listed[key]], said)
    if not ranked or not isinstance(ranked[0][1], _Listed):
        return None
    (top, best), second = ranked[0], (ranked[1][0] if len(ranked) > 1 else 0.0)
    if top < OFFER_SCORE or second * OFFER_LEAD > top or best.entry["id"] in taken or best.name in taken:
        return None
    return best.entry


# ---------------------------------------------------------- other hosts' skills

# The folders other agents keep a person's skills in, under their profile.
HOST_FOLDERS = (
    ("Claude Code", (".claude", "skills")),
    ("Codex", (".codex", "skills")),
    ("Agent Skills", (".agents", "skills")),
    ("Cursor", (".cursor", "skills")),
    ("Gemini CLI", (".gemini", "skills")),
    ("GitHub Copilot", (".copilot", "skills")),
    ("OpenCode", (".config", "opencode", "skills")),
    ("OpenCode", (".config", "opencode", "skill")),
    ("Windsurf", (".codeium", "windsurf", "skills")),
)


def profile() -> Path:
    return Path.home()


def other_hosts() -> list[dict]:
    """The skills in other agents' folders in the person's profile, by name; read only when the person asks."""
    found, seen = [], set()
    for host, parts in HOST_FOLDERS:
        root = profile().joinpath(*parts)
        for folder in store._folders(root):
            skill, _ = store.read(folder)
            key = str(folder.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append({"host": host, "path": str(folder), "name": skill.name, "description": skill.description,
                          "problems": skill.problems})
    return found


def import_folders(home: Path, paths: list[str]) -> list[str]:
    """Copies the chosen ones of other_hosts() in through the store's add path; the originals are left as they are."""
    listed = {row["path"]: row for row in other_hosts() if not row["problems"]}
    added = []
    for path in paths:
        row = listed.get(path)
        if row is None:
            raise ValueError("skill_gone")
        folder = Path(path)
        files: dict[str, bytes] = {}
        size = 0
        for item in sorted(folder.rglob("*")):
            rel = item.relative_to(folder)
            if any(p.startswith(".") for p in rel.parts) or item.is_symlink() or not item.is_file():
                continue
            size += item.stat().st_size
            if len(files) >= store.MAX_MEMBERS or size > store.MAX_UNPACKED:
                raise ValueError("skill_too_large")
            files[rel.as_posix()] = item.read_bytes()
        added += store.install_zip(home, zip_of(folder.name, files), "import", f"{row['host']}: {folder}"[:300])
    return added
