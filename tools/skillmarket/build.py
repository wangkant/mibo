"""Builds the skill market's catalog, data/market/skills.json:

    python tools/skillmarket/build.py --cache <folder>

It walks the public repositories in sources.json, finds every skill (a folder holding SKILL.md), and records facts
about it: its front matter, the licence that governs it, the files beside it, the commit it was read at and the
last commit that touched it, its popularity where a public count exists, a category, what it needs, how well it
fits Mibo, and what a safety scan of its files found. The catalog points at skills; no skill's text or files are
written into it, only the title and one sentence about each, written for the catalog (texts.json beside this
file). Every download is kept under --cache, so a second run asks the network only for what changed.

Each repository costs one `git ls-remote`, one archive at its commit (codeload.github.com, not the rate-limited
API), one blobless clone for folder dates (deleted after), one GitHub API call for stars, and one skills.sh page
for install counts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mibo.skills import market  # noqa: E402
from places import place  # noqa: E402
from mibo.skills.store import (MAX_MEMBER, MAX_MEMBERS, MAX_UNPACKED, NAME, SKILL_FILE,  # noqa: E402
                                        _front, _member_path)

HERE = Path(__file__).resolve().parent
OUT = ROOT / "data" / "market"
AGENT = "skill-catalog-builder (+https://github.com/wangkant/mibo)"
# The coarse labels category_of gives when no reading has; places.place turns them into the market's categories.
READINGS = ("documents", "writing", "research", "data", "design", "development", "productivity", "media",
              "learning", "life", "tools")
# Folders that hold a project's tests or examples, never skills offered to people.
NOT_SKILLS = re.compile(r"(^|/)(node_modules|tests?|__tests__|fixtures|snapshots|testdata|evals?|\.git)(/|$)")
TEXT = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh", ".ps1",
        ".psm1", ".bat", ".cmd", ".rb", ".pl", ".php", ".go", ".json", ".yaml", ".yml", ".toml", ".html", ".htm",
        ".css", ".xml", ".csv", ".ini", ".cfg", ".sql", ".r", ".lua", ".swift", ".kt", ".java", ".rs", ".mdx", ""}
SCRIPT = {".py": "python", ".js": "node", ".mjs": "node", ".cjs": "node", ".ts": "node", ".tsx": "node",
          ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell", ".psm1": "powershell",
          ".bat": "cmd", ".cmd": "cmd", ".rb": "ruby", ".pl": "perl", ".php": "php", ".go": "go", ".r": "r",
          ".lua": "lua", ".swift": "swift", ".java": "java", ".kt": "kotlin", ".rs": "rust"}


def log(*parts) -> None:
    print(*parts, flush=True)


# ---------------------------------------------------------------- the network, cached

class Net:
    def __init__(self, cache: Path, today: str, offline: bool):
        self.cache, self.today, self.offline = cache, today, offline
        self.api_left = 60

    def _path(self, kind: str, key: str) -> Path:
        safe = re.sub(r"[^\w.@-]+", "_", key)[:120]
        return self.cache / kind / safe

    def get(self, url: str, kind: str, key: str, daily: bool = True, headers: dict | None = None) -> bytes | None:
        """The body at url, from the cache when fetched today (or ever, when not daily); None on 404."""
        path = self._path(kind, key + (f"@{self.today}" if daily else ""))
        if path.exists():
            data = path.read_bytes()
            return None if data == b"\0404" else data
        if self.offline:
            older = sorted(path.parent.glob(re.sub(r"@\d{4}-\d\d-\d\d$", "", path.name) + "@*")) if daily else []
            return older[-1].read_bytes() if older else None
        req = urllib.request.Request(url, headers={"User-Agent": AGENT, **(headers or {})})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                    if "api.github.com" in url:
                        self.api_left = int(r.headers.get("X-RateLimit-Remaining", self.api_left))
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    data = b"\0404"
                    break
                if e.code in (403, 429) and "api.github.com" in url:
                    log("  GitHub API limit reached; stars left empty for", url)
                    return None
                if attempt == 2:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(3 * (attempt + 1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        time.sleep(0.5)
        return None if data == b"\0404" else data

    def download(self, url: str, dest: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as out:
                    shutil.copyfileobj(r, out, 1 << 20)
                return
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", check=True, timeout=1800).stdout


def head_commit(net: Net, repo: str) -> str:
    path = net._path("heads", f"{repo}@{net.today}")
    if path.exists() or net.offline:
        found = path if path.exists() else max(path.parent.glob(path.name.split("@")[0] + "@*"))
        return found.read_text().strip()
    sha = git("ls-remote", f"https://github.com/{repo}", "HEAD").split()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sha)
    return sha


# ---------------------------------------------------------------- licences

def _has(text: str, *phrases: str) -> bool:
    flat = " ".join(text.split()).lower()
    return all(" ".join(p.split()).lower() in flat for p in phrases)


def licence_of(text: str) -> str:
    """The SPDX identifier a licence text is, read from its own words; CUSTOM when it is none of the public ones."""
    t = text
    if _has(t, "permission is hereby granted, free of charge"):
        return "MIT" if _has(t, "shall be included in all copies") else "MIT-0"
    if _has(t, "apache license") and _has(t, "version 2.0"):
        return "Apache-2.0"
    if _has(t, "redistribution and use in source and binary forms"):
        return "BSD-3-Clause" if _has(t, "neither the name") else "BSD-2-Clause"
    if _has(t, "permission to use, copy, modify, and/or distribute this software for any purpose"):
        return "ISC" if _has(t, "provided that the above copyright notice") else "0BSD"
    if _has(t, "this is free and unencumbered software released into the public domain"):
        return "Unlicense"
    if _has(t, "gnu affero general public license"):
        return "AGPL-3.0"
    if _has(t, "gnu lesser general public license"):
        return "LGPL-3.0" if _has(t, "version 3") else "LGPL-2.1"
    if _has(t, "gnu general public license"):
        return "GPL-3.0" if _has(t, "version 3") else "GPL-2.0"
    if _has(t, "mozilla public license") and _has(t, "2.0"):
        return "MPL-2.0"
    if _has(t, "boost software license"):
        return "BSL-1.0"
    if _has(t, "cc0 1.0") or _has(t, "creative commons zero"):
        return "CC0-1.0"
    if _has(t, "noncommercial") or _has(t, "non-commercial") or re.search(r"\bBY[- ]NC\b", t, re.I):
        return "CC-BY-NC-4.0" if re.search(r"creative commons|\bCC[- ]BY", t, re.I) else "CUSTOM"
    if _has(t, "attribution-sharealike 4.0") or _has(t, "cc by-sa 4.0") or _has(t, "cc-by-sa-4.0"):
        return "CC-BY-SA-4.0"
    if _has(t, "attribution 4.0 international") or _has(t, "cc by 4.0") or _has(t, "cc-by-4.0"):
        return "CC-BY-4.0"
    # A short file or field that only names its licence.
    short = " ".join(t.split())
    if len(short) < 400:
        for spdx, pattern in (("MIT", r"\bMIT\b"), ("Apache-2.0", r"\bApache[- ]?(License,? )?(Version )?2(\.0)?\b"),
                              ("BSD-3-Clause", r"\bBSD[- ]3"), ("CC-BY-4.0", r"\bCC[- ]BY[- ]4"),
                              ("CC0-1.0", r"\bCC0\b"), ("ISC", r"^ISC\b")):
            if re.search(pattern, short, re.I) and not re.search(r"propriet|all rights reserved", short, re.I):
                return spdx
    return "CUSTOM"


OPEN = {"MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense", "CC0-1.0",
        "CC-BY-4.0", "BSL-1.0", "Zlib"}
SHARE_ALIKE = {"CC-BY-SA-4.0", "GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0", "MPL-2.0"}
LICENCE_FILE = re.compile(r"^(licen[cs]e|copying|unlicense)(\.(md|txt|rst))?$", re.I)


def governing_licence(names: set[PurePosixPath], read, root: PurePosixPath, front: dict, readme: str) -> dict:
    """The licence that governs a skill: a licence file in its own folder, else its front matter's license field,
    else the nearest licence file above it, else what the repository's README states. read(path) gives a file."""
    def nearest(start: PurePosixPath, stop_at_own: bool):
        folder = start
        while True:
            for p in sorted(names):
                if p.parent == folder and LICENCE_FILE.match(p.name):
                    return p
            if stop_at_own or not folder.parts:
                return None
            folder = folder.parent
    field = front.get("license")
    field = " ".join(field.split()) if isinstance(field, str) else ""
    own = nearest(root, True)
    if own:
        return {"spdx": licence_of(read(own)), "file": str(own)}
    if field and re.search(r"propriet", field, re.I):
        return {"spdx": "CUSTOM", "file": "SKILL.md", "field": field}
    named = licence_of(field) if field and not re.search(r"licen[cs]e\.(txt|md)|see |terms", field, re.I) else ""
    above = nearest(root.parent, False) if root.parts else None
    governs = licence_of(read(above)) if above else ""
    # A field and a file above that disagree on whether it is open: the narrower one governs. A field that names
    # no licence ("Unknown", a link) is not a disagreement.
    if named.startswith("CC-BY-NC") or (named == "CUSTOM" and re.search(r"commercial|\bNC\b", field, re.I)):
        return {"spdx": named, "file": "SKILL.md", "field": field}
    if named and named != "CUSTOM" and (governs.startswith("CC-BY-NC") or governs == "CUSTOM"):
        return {"spdx": governs, "file": str(above)}
    if named and named != "CUSTOM":
        return {"spdx": named, "file": "SKILL.md", "field": field}
    if above:
        return {"spdx": governs, "file": str(above)}
    m = re.search(r"^#+\s*(licen[cs]e|许可|开源协议)[^\n]*\n+(.{0,300})", readme, re.I | re.M | re.S)
    if m:
        spdx = licence_of(m.group(2).split("\n\n")[0])
        if spdx != "CUSTOM":
            return {"spdx": spdx, "file": "README"}
    return {"spdx": "NONE", "file": ""}


def licence_entry(found: dict, repo: str, commit: str) -> dict:
    spdx = found["spdx"]
    file = found.get("file") or ""
    url = f"https://github.com/{repo}/blob/{commit}/{file}" if file and file not in ("SKILL.md", "README") else \
        f"https://github.com/{repo}/tree/{commit}"
    if spdx in OPEN:
        return {"spdx": spdx, "url": url, "installable": True, "note": ""}
    if spdx in SHARE_ALIKE:
        return {"spdx": spdx, "url": url, "installable": True,
                "note": "开源许可，允许使用与再分发；修改后再分发须沿用相同许可。"}
    if spdx == "NONE":
        return {"spdx": "NONE", "url": url, "installable": True,
                "note": "未声明许可：作者未授予再分发许可，只能从其来源取得，仅供个人使用。"}
    if spdx.startswith("CC-BY-NC"):
        return {"spdx": spdx, "url": url, "installable": False,
                "note": "许可禁止商业用途，此处不提供安装，请前往来源查看条款。"}
    return {"spdx": "CUSTOM", "url": url, "installable": False,
            "note": "许可限定了使用范围或无法归入公开许可，此处不提供安装，请前往来源查看条款。"}


# ---------------------------------------------------------------- reading one repository

def walk_repo(net: Net, src: dict, commit: str, work: Path) -> dict:
    """Every skill in the repository at commit, with its facts. The cache keeps only the skills' folders, the
    licence files above them and the README, so a change to these rules never needs the network again."""
    repo = src["repo"]
    kept = net.cache / "skills" / f"{repo.replace('/', '__')}@{commit}.zip"
    if not kept.exists():
        keep_skills(net, src, commit, work, kept)
    zf = zipfile.ZipFile(kept)
    infos = {PurePosixPath(i.filename): i for i in zf.infolist() if not i.is_dir()}
    names = set(infos)
    left_out = [PurePosixPath(x.strip("/")) for x in src.get("exclude", [])]
    roots = [PurePosixPath(r) for r in json.loads(zf.comment.decode("utf-8"))["roots"]]
    roots = [r for r in roots if not any(_under(r, x) for x in left_out)]
    readme = next((zf.read(infos[p]).decode("utf-8", "replace") for p in sorted(names)
                   if len(p.parts) == 1 and p.name.lower() in ("readme.md", "readme")), "")
    skills = []
    for root in roots:
        members = {p: infos[p] for p in sorted(names) if _under(p, root)}
        files = {str(p.relative_to(root)): zf.read(i) for p, i in members.items()
                 if not stat.S_ISLNK(i.external_attr >> 16)}
        unusable = []
        if any(not _member_path(i)[1] for i in members.values()):
            unusable.append("archive_member_refused")
        if len(members) > MAX_MEMBERS or sum(i.file_size for i in members.values()) > MAX_UNPACKED \
                or any(i.file_size > MAX_MEMBER for i in members.values()):
            unusable.append("too_large")
        raw = files.get(SKILL_FILE, b"")
        try:
            front, body = _front(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            front, body = {}, ""
            unusable.append(str(e) if isinstance(e, ValueError) else "not_text")
        name = front.get("name").strip() if isinstance(front.get("name"), str) else ""
        description = " ".join(front["description"].split()) if isinstance(front.get("description"), str) else ""
        if not name or len(name) > 64 or not NAME.match(name):
            unusable.append("bad_name")
        if not description:
            unusable.append("no_description")
        if not body:
            unusable.append("no_body")
        texts, scripts = {}, set()
        for path, data in files.items():
            suffix = PurePosixPath(path).suffix.lower()
            if suffix in SCRIPT or data[:2] == b"#!":
                scripts.add(path)
            if suffix in TEXT and len(data) <= 2_000_000:
                texts[path] = data.decode("utf-8", "replace")
        licence = governing_licence(names, lambda p: zf.read(infos[p]).decode("utf-8", "replace"), root, front,
                                    readme)
        skills.append({
            "path": str(root) if root.parts else "",
            "name": name, "description": description[:1024],
            "hash": market.folder_hash(files),
            "files": {p: hashlib.sha256(d).hexdigest() for p, d in sorted(files.items())},
            "body_hash": hashlib.sha256(" ".join(body.split()).encode()).hexdigest(),
            "scripts": sorted(scripts),
            "runtimes": sorted({SCRIPT.get(PurePosixPath(p).suffix.lower(), "") for p in scripts} - {""}),
            "signals": signals(name, description, body, texts),
            "licence": licence,
            # The market's own scan, the one it runs again on what arrives before installing.
            "scan": market.scan(files),
            "unusable": unusable,
        })
    zf.close()
    dates = folder_dates(net, repo, commit, [s["path"] for s in skills], work)
    for s in skills:
        s["updated"] = dates.get(s["path"], "")
    return {"repo": repo, "commit": commit, "skills": skills}


def keep_skills(net: Net, src: dict, commit: str, work: Path, kept: Path) -> None:
    """Downloads the repository's archive at commit and keeps, in a small zip, the skill folders found in it."""
    repo = src["repo"]
    archive = work / f"{repo.replace('/', '__')}.zip"
    log("  archive", repo, commit[:10])
    net.download(f"https://codeload.github.com/{repo}/zip/{commit}", archive)
    with zipfile.ZipFile(archive) as zf:
        comment = zf.comment.decode("ascii", "ignore")
        if comment and comment != commit:
            raise SystemExit(f"{repo}: archive is at {comment}, not {commit}")
        infos: dict[PurePosixPath, zipfile.ZipInfo] = {}
        for info in zf.infolist():
            if not info.is_dir():
                infos[PurePosixPath(*PurePosixPath(info.filename.replace("\\", "/")).parts[1:])] = info
        prefixes = [PurePosixPath(p.strip("/")) for p in src.get("paths", [])]
        holders = sorted({p.parent for p in infos if p.name == SKILL_FILE}, key=lambda p: (len(p.parts), str(p)))
        roots: list[PurePosixPath] = []
        for r in holders:
            if NOT_SKILLS.search(str(r)) or (prefixes and not any(_under(r, x) for x in prefixes)):
                continue
            if not any(_under(r, c) for c in roots):
                roots.append(r)
        # Licence files on the way up from each skill, and the README that may state the licence.
        above = {r.parents[i] for r in roots for i in range(len(r.parts))} | {PurePosixPath()}
        wanted = [p for p in infos if any(_under(p, r) for r in roots)
                  or (p.parent in above and (LICENCE_FILE.match(p.name) or (not p.parent.parts
                                                                            and p.name.lower() in ("readme.md", "readme"))))]
        kept.parent.mkdir(parents=True, exist_ok=True)
        part = kept.with_suffix(".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as out:
            for p in wanted:
                info = infos[p]
                copy = zipfile.ZipInfo(str(p), info.date_time)
                copy.external_attr = info.external_attr
                out.writestr(copy, zf.read(info), zipfile.ZIP_DEFLATED)
            out.comment = json.dumps({"repo": repo, "commit": commit, "roots": [str(r) for r in roots]}).encode()
    part.replace(kept)
    archive.unlink()


def _under(path: PurePosixPath, root: PurePosixPath) -> bool:
    return not root.parts or path.parts[:len(root.parts)] == root.parts


def folder_dates(net: Net, repo: str, commit: str, paths: list[str], work: Path) -> dict:
    """The date of the last commit touching each folder, from a blobless clone that is removed afterwards."""
    kept = net.cache / "dates" / f"{repo.replace('/', '__')}@{commit}.json"
    if kept.exists():
        return json.loads(kept.read_text(encoding="utf-8"))
    if not paths:
        return {}
    # A short name: Windows refuses paths past 260 characters, and git's pack files are long.
    clone = work / ("c" + hashlib.sha256(repo.encode()).hexdigest()[:8])
    if clone.exists():
        shutil.rmtree(clone, onerror=_force)
    log("  history", repo)
    try:
        git("clone", "--bare", "--filter=blob:none", "--single-branch", "--quiet", f"https://github.com/{repo}",
            str(clone))
        # One pass over the history, newest first: a folder's date is that of the first commit touching it.
        spec = paths if sum(len(p) + 3 for p in paths) < 20000 and all(paths) else []
        history = git("log", "--format=%x00%cs", "--name-only", "--no-renames", commit, "--", *spec, cwd=clone)
        out, left = {}, {p: (p + "/" if p else "") for p in paths}
        for chunk in history.split("\0")[1:]:
            lines = chunk.strip("\n").split("\n")
            for name in lines[1:]:
                for p, prefix in list(left.items()):
                    if name.startswith(prefix):
                        out[p] = lines[0]
                        del left[p]
            if not left:
                break
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(json.dumps(out), encoding="utf-8")
        return out
    except subprocess.CalledProcessError as e:
        log("  history failed for", repo, e.stderr[-300:])
        return {}
    finally:
        shutil.rmtree(clone, onerror=_force)


def _force(func, path, _):
    Path(path).chmod(stat.S_IWRITE)
    func(path)


# ---------------------------------------------------------------- what a skill needs and how it fits

TOOL_SIGNS = {
    "web_search": r"\bweb ?search\b|\bsearch the web\b|\bWebSearch\b|搜索网页|联网搜索",
    "web_fetch": r"\bWebFetch\b|\bfetch (the )?(url|page|web ?page)\b|抓取网页",
    "browser": r"\bbrowser\b|\bplaywright\b|\bpuppeteer\b|\bchrome\b|\bCDP\b|浏览器",
    "shell": r"\bBash\b|\bterminal\b|\bcommand line\b|\bshell command|命令行|终端",
    "mcp": r"\bMCP\b|\bmcp__|model context protocol",
    "subagents": r"\bsub-?agents?\b|\bTask tool\b|子代理",
    "gh": r"`gh |\bgh (pr|issue|api|repo)\b",
    "git": r"`git |\bgit (commit|diff|log|status|checkout|branch|worktree)\b",
    "node": r"\bnpx\b|\bnpm (install|run|i)\b|\bnode \S+\.m?js\b|\bpnpm\b|\bbun\b",
    "python": r"\bpython3? \S+\.py\b|\bpip install\b|\buv (run|pip)\b|\buvx\b",
    "ffmpeg": r"\bffmpeg\b",
    "pandoc": r"\bpandoc\b",
    "libreoffice": r"\blibreoffice\b|\bsoffice\b",
    "docker": r"\bdocker\b",
    "image_generation": r"\b(image generation|generate (an )?images?|nano.?banana|gpt-image|dall-?e|imagen|seedream|"
                        r"midjourney|flux)\b|生图|生成图片",
    "api_key": r"\b[A-Z][A-Z0-9_]{2,}_(API_KEY|TOKEN|SECRET)\b|\bAPI key\b|API ?密钥",
}
TOOL_C = {k: re.compile(v, re.I if k not in ("shell", "api_key") else 0) for k, v in TOOL_SIGNS.items()}
CODING = re.compile(r"\b(codebase|pull requests?|PRs?\b|commits?\b|refactor\w*|unit tests?|TDD|test-driven|lint\w*|"
                    r"type ?script|react|next\.js|frontend|backend|api routes?|deploy\w*|repository|repo\b|"
                    r"debug\w*|stack trace|component|monorepo|ci\b|build errors?|migrations?|kubernetes|terraform|"
                    r"sdk|framework|compiler|code review|source code|implement\w*|programming|developer)", re.I)
HOST_ONLY = re.compile(r"\b(claude code|codex( cli)?|cursor|gemini cli|github copilot|claude\.ai|slash commands?|"
                       r"CLAUDE\.md|AGENTS\.md|sub-?agents?|/plugin)\b", re.I)


def signals(name: str, description: str, body: str, texts: dict[str, str]) -> dict:
    """What a skill relies on (from all its prose) and what it is for (from its name and description)."""
    blob = body + "\n" + "\n".join(v for k, v in texts.items() if k.endswith(".md"))[:200_000]
    purpose = name.replace("-", " ") + " " + description
    per = max(1.0, len(body) / 3000)
    return {
        "tools": sorted(k for k, rule in TOOL_C.items() if rule.search(blob)),
        "coding": len(CODING.findall(purpose)),
        "coding_body": round(len(CODING.findall(body)) / per, 1),
        "host": len(HOST_ONLY.findall(purpose)),
        "host_body": len(HOST_ONLY.findall(body)),
        "cjk": bool(re.search(r"[\u4e00-\u9fff]", purpose)),
    }


CATEGORY_WORDS = {
    "documents": r"\bpdf\b|\bdocx?\b|\bword documents?\b|\bpptx?\b|powerpoint|slides?\b|slide decks?|presentations?|"
                 r"\bxlsx\b|spreadsheets?|resumes?|\bcv\b|contracts?|office|文档|幻灯片|演示|简历|排版|ppt",
    "writing": r"\bwrit\w+|\bcopy(writing)?\b|\bblog\w*|articles?|essays?|humaniz\w+|\btone\b|\bvoice\b|newsletters?|"
               r"posts?\b|captions?|stor(y|ies)|novels?|fiction|scripts? for|写作|文章|公众号|小说|网文|文案|润色|去ai味",
    "research": r"\bresearch\w*|papers?\b|literature|academic|scientific|scien\w+|citations?|arxiv|pubmed|"
                r"bioinformatics|chemistry|论文|科研|调研|学术",
    "data": r"\bdata\b|datasets?|\bcsv\b|\bsql\b|analytics|charts?|dashboards?|statistic\w*|excel|metrics|"
            r"finance|financial|trading|stocks?|investment|数据|表格|分析|股票|财务",
    "design": r"\bdesign\w*|\bui\b|\bux\b|\bcss\b|figma|logos?|brand\w*|themes?|colou?rs?|typograph\w+|layouts?|"
              r"posters?|diagrams?|infographics?|visual\w*|\bart\b|artwork|generative|设计|海报|配色|信息图|图表",
    "media": r"\bvideos?\b|\bimages?\b|\baudio\b|music|podcasts?|animation|\bgifs?\b|speech|\btts\b|voices?\b|"
             r"photos?|illustrat\w+|motion|视频|图片|配图|播客|动画|短剧|分镜|音频|插图|封面",
    "learning": r"\blearn\w*|\bteach\w*|tutor\w*|quiz\w*|courses?|study|students?|flashcards?|explain\w*|"
                r"学习|教学|考研|高考|讲解|老师",
    "life": r"\btravel\w*|recipes?|cooking|health|fitness|weather|shopping|personal finance|careers?|jobs?\b|"
            r"relationships?|生活|旅行|健康|美食|职业|求职|志愿",
    "productivity": r"\bemails?\b|\bgmail\b|calendar|meetings?|\bnotes?\b|tasks?\b|todo|obsidian|notion|"
                    r"\bplan\w*|workflows?|feishu|\blark\b|slack|okr|project management|product managers?|"
                    r"sales|marketing|crm|飞书|会议|笔记|日程|任务|待办|周报|营销",
    "tools": r"\bbrowser\w*|\bsearch\w*|scrap\w+|crawl\w*|\bcli\b|automat\w+|\bmcp\b|\bapi\b|skills?\b|"
             r"浏览器|搜索|抓取|自动化",
    "development": r"\bcod(e|ing)\b|\bgit\b|\btest\w*|debug\w*|deploy\w*|react|frontend|backend|refactor\w*|"
                   r"\bpr\b|typescript|python|javascript|\bsdk\b|database|kubernetes|terraform|security|"
                   r"vulnerab\w+|engineer\w*|software|编程|代码|开发",
}
CATEGORY_C = {k: re.compile(v, re.I) for k, v in CATEGORY_WORDS.items()}


def category_of(name: str, description: str, product: str) -> str:
    text = f"{name.replace('-', ' ')} {name.replace('-', ' ')} {description}"
    scores = {k: len(rule.findall(text)) for k, rule in CATEGORY_C.items()}
    if product:
        scores["development"] += 2
    # A skill about skills or agents is a tool; plain "data" in a coding description is development.
    best = max(READINGS, key=lambda k: (scores[k], -READINGS.index(k)))
    return best if scores[best] else "productivity"


FIT_NOTES = {
    "product": "面向{product}的专用技能，需要该产品的账号或环境。",
    "cli": "需要本机安装并配置 {product} 命令行工具。",
    "coding": "面向编程智能体的代码工作流，在 Mibo 中用处有限。",
    "host": "依赖其他智能体宿主的功能（如插件、子代理或斜杠命令），在 Mibo 中无法完整使用。",
    "mcp": "需要连接 MCP 服务器，Mibo 尚未接入该服务器时只能使用说明部分。",
    "api_key": "需要第三方服务的 API 密钥。",
    "image_generation": "需要图像生成服务，Mibo 本身不提供。",
    "subagents": "依赖子代理并行工作，Mibo 只能按顺序完成其中一部分。",
    "runtime": "附带的脚本需要本机安装 {runtimes}。",
}


def fit_of(s: dict, product: str, cli: str) -> tuple[str, str]:
    sig, tools = s["signals"], set(s["signals"]["tools"])
    if product:
        return "no", FIT_NOTES["product"].format(product=product)
    if cli:
        return "partial", FIT_NOTES["cli"].format(product=cli)
    if sig["coding"] >= 2 or (sig["coding"] >= 1 and sig["coding_body"] >= 12):
        return "no", FIT_NOTES["coding"]
    if sig["host"] >= 2:
        return "no", FIT_NOTES["host"]
    for need in ("mcp", "subagents", "image_generation", "api_key"):
        if need in tools:
            return "partial", FIT_NOTES[need]
    if sig["host"] or sig["host_body"] >= 4:
        return "partial", FIT_NOTES["host"]
    odd = [r for r in s["runtimes"] if r not in ("python", "bash", "powershell", "cmd")]
    if odd:
        return "partial", FIT_NOTES["runtime"].format(runtimes="、".join(
            {"node": "Node.js"}.get(r, r.capitalize()) for r in odd))
    if sig["coding"] or sig["coding_body"] >= 12:
        return "partial", FIT_NOTES["coding"]
    return "ready", ""


# ---------------------------------------------------------------- popularity

def stars_of(net: Net, repo: str, seed: dict) -> int | None:
    if repo.lower() in seed:
        return seed[repo.lower()]
    data = net.get(f"https://api.github.com/repos/{repo}", "api", f"repo-{repo}",
                   headers={"Accept": "application/vnd.github+json"})
    if not data:
        return None
    return json.loads(data).get("stargazers_count")


def installs_of(net: Net, repo: str) -> dict[str, int]:
    """Per-skill install counts from the repository's public page on skills.sh, rounded as the page shows them."""
    data = net.get(f"https://www.skills.sh/{repo.lower()}", "skillssh", repo.lower())
    if not data:
        return {}
    page = data.decode("utf-8", "replace")
    out = {}
    for slug, count in re.findall(r'href="/' + re.escape(repo.lower()) + r'/([\w.:-]+)"[^>]*>.*?'
                                  r'font-mono[^>]*>([\d.,]+[KMB]?)</span>', page, re.I | re.S):
        if slug not in out:
            out[slug] = _count(count)
    return out


def _count(text: str) -> int:
    mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(text[-1:].upper(), 1)
    return int(round(float(text.rstrip("KMBkmb").replace(",", "")) * mult))


# ---------------------------------------------------------------- assembling

def humanize(name: str) -> str:
    small = {"pdf": "PDF", "docx": "DOCX", "pptx": "PPTX", "xlsx": "XLSX", "ui": "UI", "ux": "UX", "api": "API",
             "mcp": "MCP", "seo": "SEO", "ai": "AI", "cli": "CLI", "csv": "CSV", "sql": "SQL", "pr": "PR",
             "gif": "GIF", "svg": "SVG", "llm": "LLM", "okr": "OKR", "html": "HTML", "css": "CSS", "tdd": "TDD",
             "xhs": "XHS", "ppt": "PPT", "aws": "AWS", "gcp": "GCP", "sdk": "SDK", "url": "URL", "3d": "3D"}
    words = [small.get(w, w) for w in name.split("-")]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", required=True, type=Path, help="folder for downloads and per-repository results")
    ap.add_argument("--offline", action="store_true", help="use only what the cache holds")
    ap.add_argument("--only", default="", help="comma-separated repositories to walk (for trying a change)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    today = dt.date.today().isoformat()
    cache = args.cache.resolve()
    net = Net(cache, today, args.offline)
    work = cache / "work"
    work.mkdir(parents=True, exist_ok=True)
    config = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    texts = json.loads((HERE / "texts.json").read_text(encoding="utf-8")) if (HERE / "texts.json").exists() else {}
    seed = {}
    for f in (cache / "stars-seed").glob("*.json") if (cache / "stars-seed").exists() else []:
        for item in json.loads(f.read_text(encoding="utf-8")).get("items", []):
            seed[item["full_name"].lower()] = item["stargazers_count"]
    only = {r.strip().lower() for r in args.only.split(",") if r.strip()}
    walked, sources, failed = [], [], []
    for src in config["repos"]:
        repo = src["repo"]
        if only and repo.lower() not in only:
            continue
        if src.get("skip"):
            log(repo, "left out:", src["skip"])
            continue
        log(repo)
        try:
            commit = head_commit(net, repo)
            result = walk_repo(net, src, commit, work)
        except (subprocess.CalledProcessError, urllib.error.URLError, OSError, zipfile.BadZipFile) as e:
            log("  FAILED", repo, repr(e)[:200])
            failed.append(repo)
            continue
        stars = stars_of(net, repo, seed)
        installs = installs_of(net, repo)
        walked.append((src, result, stars, installs))
        sources.append({"id": repo, "name": f"{src['publisher']} · {repo.split('/')[1]}",
                        "url": f"https://github.com/{repo}", "note": {
                            "official": "Published by the maker of the product or model.",
                            "community": "A widely used community collection.",
                            "zh": "A Chinese-language collection."}[src["kind"]]})
    sources = [{"id": d["id"], "name": d["name"], "url": d["url"], "note": d["note"]}
               for d in config.get("directories", [])] + sources

    entries, seen_hash, seen_body, seen_desc, ids = [], {}, {}, {}, set()
    dropped = {"unusable": [], "duplicate": [], "removed": []}
    # Skills or whole repositories their publishers asked to have left out ("owner/repo" or "owner/repo/path").
    removed = set(config.get("removed", []))
    pending = {}
    for src, result, stars, installs in walked:
        repo, commit = src["repo"], result["commit"]
        owner = repo.split("/")[0].lower()
        for s in result["skills"]:
            where = f"{repo}/{s['path']}"
            if repo in removed or where in removed:
                dropped["removed"].append(where)
                continue
            if s["unusable"]:
                dropped["unusable"].append(f"{where}: {','.join(s['unusable'])}")
                continue
            twin = seen_hash.get(s["hash"]) or seen_body.get(s["body_hash"]) or \
                seen_desc.get((s["name"], s["description"]))
            if twin:
                dropped["duplicate"].append(f"{where} = {twin}")
                continue
            sid = f"{owner}/{s['name']}"
            if sid in ids:
                parent = PurePosixPath(s["path"]).parent.parent.name or repo.split("/")[1]
                sid = f"{owner}/{parent.lower()}-{s['name']}"
            n = 2
            while sid in ids:
                sid, n = f"{owner}/{s['name']}-{n}", n + 1
            ids.add(sid)
            seen_hash[s["hash"]] = seen_body[s["body_hash"]] = seen_desc[(s["name"], s["description"])] = sid
            text = texts.get(sid)
            # Texts are written once per description, kept by a digest of it so none of its words are stored here; a
            # changed description asks for them again.
            digest = hashlib.sha256(s["description"].encode("utf-8")).hexdigest()[:16]
            if not text or text.get("desc") != digest:
                pending[sid] = {"name": s["name"], "description": s["description"][:400], "repo": repo,
                                "desc": digest}
                text = {}
            fit, fit_note = fit_of(s, src.get("product", ""), src.get("cli", ""))
            if text.get("fit"):
                # A reading of the skill corrects the rule: "ready", or "<fit>:<note>" with product=<name>.
                fit, _, why = text["fit"].partition(":")
                key, _, product = why.partition("=")
                fit_note = FIT_NOTES[key].format(product=product, runtimes="") if fit != "ready" else ""
            path = s["path"]
            entry = {
                "id": sid,
                "name": s["name"],
                "title": {"zh": text.get("title_zh", ""), "en": text.get("title_en") or humanize(s["name"])},
                "about": {"zh": text.get("about_zh", ""), "en": text.get("about_en", "")},
                "publisher": src["publisher"],
                "source": {"repo": repo, "path": path, "commit": commit,
                           "url": f"https://github.com/{repo}/tree/{commit}/{path}".rstrip("/")},
                "licence": licence_entry(s["licence"], repo, commit),
                "category": "",
                "sub": "",
                "tags": sorted(set(text.get("tags", [])) | ({"中文"} if s["signals"]["cjk"] else set())),
                "needs": {"scripts": bool(s["scripts"]), "runtimes": s["runtimes"],
                          "tools": [t for t in s["signals"]["tools"] if t not in ("python", "node")]},
                "fit": fit,
                "fit_note": fit_note,
                "popularity": {"stars": stars, "installs": installs.get(s["name"]), "as_of": today},
                "hash": s["hash"],
                # Each file's sha256: the app fetches them one by one from any mirror and checks each.
                "files": s["files"],
                "scan": s["scan"],
                "updated": s["updated"],
            }
            reading = text.get("category") or category_of(s["name"], s["description"], src.get("product", ""))
            entry["category"], entry["sub"] = place(entry, reading, text.get("place", ""))
            entries.append(entry)
    (cache / "pending_texts.json").write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")
    (cache / "dropped.json").write_text(json.dumps(dropped, ensure_ascii=False, indent=1), encoding="utf-8")
    (cache / "draft.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    # What was read from each repository, for check.py.
    (cache / "facts.json").write_text(json.dumps([r for _, r, _, _ in walked], ensure_ascii=False), encoding="utf-8")
    log(f"\n{len(entries)} entries, {len(dropped['duplicate'])} duplicates and {len(dropped['unusable'])} "
        f"unreadable skills left out, {len(pending)} without written texts, failed: {failed or 'none'}")
    if pending:
        log("texts missing: see", cache / "pending_texts.json", "- the catalog is not written until every entry has them")
        return 2
    entries.sort(key=lambda e: (-(e["popularity"]["installs"] or 0), -(e["popularity"]["stars"] or 0), e["id"]))
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = {"version": market.VERSION, "built_at": today, "sources": sources, "skills": entries}
    (OUT / "skills.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                     newline="\n")
    log("wrote", OUT / "skills.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
