"""The file tools' own work, done in the page server after the gate let it through (panel.Shell.file).

Each file tool is judged by path rules alone, as coding agents gate their file tools: its full paths become the
acts a command doing the same would be sorted into (`acts`), and the judge a command goes through (read.judge)
holds them against the grants and the never list, so a folder, a card or a refusal comes the same way with no
PowerShell between. What runs afterwards is Python, which can do what PowerShell 5.1 does badly for a model:
read text in whatever encoding it is in, list and search without following links or opening protected files,
show an edit as a difference, and delete to the Recycle Bin.
"""
from __future__ import annotations

import codecs
import contextlib
import difflib
import fnmatch
import io
import mimetypes
import os
import re
import shutil
import sys
import time
import zipfile
from urllib.parse import urlsplit
from xml.etree import ElementTree

from . import office
from .grants import norm
from .read import EXE_NEVER, EXE_OPEN, INSTALLERS, OPEN_RISKY, VERBED, Act, Sorter, _base, _copy_overwrites, _local_host

# Lines a read returns when no limit is given, and the most it may ask for; characters kept of one line.
READ_LINES = 400
READ_MAX = 2000
LINE_CHARS = 500
# Characters of one tool answer, rows of a listing, matches of a search, entries walked at most.
ANSWER_CHARS = 24000
LIST_ROWS = 300
SEARCH_ROWS = 120
WALK_MOST = 50000
# Files larger than this are not searched, nor read whole for an edit.
TEXT_MAX = 10 * 1024 * 1024
# Lines of a difference shown on a card and in the list of a turn's changes.
DIFF_LINES = 1500
# Kinds Windows opens with a program that cannot run code of its own.
DOC_KINDS = {".docx": "Word", ".xlsx": "Excel", ".pptx": "PowerPoint", ".pdf": "PDF"}


# ---------------------------------------------------------------- what the gate holds a file tool to

TOOL_NAMES = {"read": "read_file", "list": "list_files", "search": "search_files", "open": "open",
              "move": "move_files", "delete": "delete_files"}


def call(job: dict) -> str:
    """A file tool's call as its card and the log show it: the tool and the full paths it works on."""
    op = job["op"]
    if op == "write":
        return f"{job['kind']}_file {job['path']}"
    if op == "move":
        return "move_files " + "; ".join(f"{m['from']} -> {m['to']}" for m in job["moves"]) + (" (copy)" if job["copy"] else "")
    if op == "delete":
        return "delete_files " + "; ".join(job["paths"])
    return f"{TOOL_NAMES[op]} {job['path']}" + (f" “{job['text']}”" if op == "search" else "")


def acts(job: dict, cwd: str) -> list[Act]:
    """What a file tool does, as the acts the judge holds against the grants: the kinds, places and flags a command
    doing the same is sorted into (read.Sorter), found from the tool's full paths."""
    sorter = Sorter({"nodes": []}, cwd)

    def places(raws: list[str], write: bool) -> tuple[list[str], bool]:
        """The paths as the judge takes them, and whether any has a wildcard; a share or a device path is an act
        of its own."""
        out, globs, given, wild = [], [], [], False
        for raw in raws:
            provider, place = sorter.paths.place(raw)
            if provider != "file":
                sorter.provider(provider, place, write, {})
                continue
            base, has = _base(place)
            out.append(base)
            globs.append(place)
            given.append(raw)
            wild = wild or has
        sorter.last_raw, sorter.last_globs = given, globs
        return out, wild

    def made(folder: str) -> None:
        paths, _ = places([folder], True)
        sorter.add("change", "mkdir", f"creates {', '.join(paths)}", paths=paths, write=True)

    op = job["op"]
    if op in ("read", "list", "search"):
        paths, wild = places([job["path"]], False)
        # A search is of the folder as one named place: what is searched inside it skips protected files (_walk).
        sorter.add("read", op, f"{op}s {', '.join(paths)}", paths=paths, wild=wild,
                   recurse=op == "list" and bool(job["recursive"]))
    elif op == "write":
        if not os.path.isdir(job["folder"]):
            made(job["folder"])
        paths, wild = places([job["path"]], True)
        sorter.add("overwrite" if any(os.path.isfile(p) for p in paths) else "change", "write",
                   f"writes {', '.join(paths)}", paths=paths, write=True, wild=wild)
    elif op == "open" and re.match(r"^https?://", job["path"], re.IGNORECASE):
        host = (urlsplit(job["path"]).hostname or "").lower()
        if _local_host(host):
            sorter.add("system", "loopback", f"opens this computer's own services at {host}")
        else:
            sorter.add("network", "browse", f"opens {job['path'][:120]} in the browser", host=host or job["path"][:40],
                       sends=True)
    elif op == "open":
        # Opened as a double-click would: a program, a script or an installer runs code, a document only shows.
        target = job["path"]
        base, ext = os.path.splitext(os.path.basename(target))[0].lower(), os.path.splitext(target)[1].lower()
        place = sorter.paths.place(target)[1]
        exists = os.path.exists(place)
        if base in EXE_NEVER:
            sorter.add(EXE_NEVER[base], EXE_NEVER[base], f"starts {base}")
        elif ext in INSTALLERS:
            sorter.add("install", "install", f"starts the installer {target}", name=target, paths=[place] if exists else [])
        elif (ext in OPEN_RISKY or (not exists and not ext)) and base in EXE_OPEN:
            sorter.add("read", "open", f"opens {base}", name=base)
        elif ext in OPEN_RISKY or (not exists and not ext):
            sorter.add("program", "program", f"starts {target}"[:160], name=target[:160], paths=[place] if exists else [])
        else:
            sorter.add("read", "open", f"opens {place} in its own program", paths=[place], name=os.path.basename(place))
    elif op == "move":
        for folder in dict.fromkeys(m["folder"] for m in job["moves"] if m["folder"] and not os.path.isdir(m["folder"])):
            made(folder)
        for m in job["moves"]:
            # A move within one folder is a rename; a folder copied takes what is inside it.
            what = "copy" if job["copy"] else (
                "rename" if os.path.dirname(m["from"].rstrip("\\/")).lower() == os.path.dirname(m["to"]).lower() else "move")
            recurse = what == "copy" and os.path.isdir(m["from"])
            paths, wild = places([m["from"]], True)
            if what == "rename":
                dest = os.path.join(os.path.dirname(paths[0]) if len(paths) == 1 else cwd, os.path.basename(m["to"]))
            else:
                provider, dest = sorter.paths.place(m["to"])
                if provider != "file":
                    sorter.provider(provider, dest, True, {})
                    continue
            overwrite = False
            for src in paths if not wild else []:
                target = os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) and what != "rename" else dest
                overwrite = overwrite or (what == "copy" and os.path.isfile(target)
                                          and os.path.normcase(target) != os.path.normcase(src)) or (
                    recurse and os.path.isdir(src) and _copy_overwrites(src, target))
            sorter.add("overwrite" if overwrite else "change", what,
                       f"{VERBED.get(what, what + 's')} {', '.join(paths) or 'items'} to {dest}", paths=paths, dest=dest,
                       write=what in ("move", "rename"), wild=wild, recurse=recurse)
    elif op == "delete":
        paths, wild = places(job["paths"], True)
        sorter.add("delete", "delete", f"deletes {', '.join(paths)}", paths=paths, write=True, wild=wild,
                   recurse=any(os.path.isdir(p) for p in job["paths"]))
    else:
        raise ValueError(op)
    return sorter.acts


# ---------------------------------------------------------------- text in whatever encoding it is in

def decode(data: bytes) -> tuple[str, str] | None:
    """(text, encoding name) for text bytes, or None for a binary file. UTF-8 with or without a BOM, UTF-16
    with a BOM or without one (by its zero bytes), then GB18030 (which holds GBK), as Chinese Windows writes."""
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace"), "utf-16"
    head = data[:4096]
    if len(head) >= 4 and head[1::2].count(0) > len(head) // 4 and head[0::2].count(0) < len(head) // 16:
        return data.decode("utf-16-le", errors="replace"), "utf-16-le"
    if b"\x00" in head:
        return None
    for name in ("utf-8", "gb18030"):
        try:
            return data.decode(name), name
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace"), "cp1252"


def encode(text: str, encoding: str) -> bytes:
    if encoding == "utf-8-sig":
        return codecs.BOM_UTF8 + text.encode("utf-8")
    if encoding == "utf-16":
        return codecs.BOM_UTF16_LE + text.encode("utf-16-le")
    return text.encode(encoding, errors="replace")


def size(n: int) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    guess = mimetypes.guess_type(path)[0] or ""
    return DOC_KINDS.get(ext) or guess or (ext.lstrip(".").upper() + " file" if ext else "file without an extension")


# ---------------------------------------------------------------- documents a person has

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# The main part of each kind of Office package, by which a copy kept under another name is known too.
_MAIN_PARTS = {"word/document.xml": ".docx", "xl/workbook.xml": ".xlsx", "ppt/presentation.xml": ".pptx"}
# What a tab and a line break in a Word paragraph read as.
_BREAKS = {_W + "tab": "\t", _W + "br": "\n", _W + "cr": "\n"}
# Pages of a PDF read at most.
PDF_PAGES = 300


def _xml_text(data: bytes, tag: str, para: str) -> list[str]:
    """Paragraphs of an Office XML part: the text of each `para` element, its `tag` runs joined."""
    root = ElementTree.fromstring(data)
    rows = []
    for p in root.iter():
        if p.tag.endswith("}" + para):
            words = "".join(t.text or "" for t in p.iter() if t.tag.endswith("}" + tag))
            if words.strip():
                rows.append(words)
    return rows


def _word(part: bytes) -> list[str]:
    """A Word part's paragraphs in reading order, each table row as one line of its cells: | a | b |."""
    root = ElementTree.fromstring(part)
    rows = []

    def walk(parent) -> None:
        for child in parent:
            if child.tag == _W + "p":
                # Tabs as tabs and a line break as a new line, as edit_file reads the paragraph.
                words = "".join(node.text or "" if node.tag == _W + "t" else _BREAKS.get(node.tag, "")
                                for run in child.iter(_W + "r") for node in run)
                rows.extend(line for line in words.split("\n") if line.strip())
            elif child.tag == _W + "tbl":
                for tr in child.iter(_W + "tr"):
                    cells = [" ".join("".join(t.text or "" for t in p.iter(_W + "t")) for p in tc.iter(_W + "p")).strip()
                             for tc in tr if tc.tag == _W + "tc"]
                    if any(cells):
                        rows.append("| " + " | ".join(cells) + " |")
            elif child.tag in (_W + "body", _W + "sdt", _W + "sdtContent", _W + "customXml"):
                walk(child)

    walk(root)
    return rows


def _xlsx(z: zipfile.ZipFile) -> list[str]:
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in root if si.tag.endswith("}si")]
    sheets = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[0]))
    rows = []
    for name in sheets:
        rows.append("[sheet " + re.findall(r"\d+", name)[0] + "]")
        for row in ElementTree.fromstring(z.read(name)).iter():
            if not row.tag.endswith("}row"):
                continue
            cells = []
            for c in row:
                v = next((x.text for x in c if x.tag.endswith("}v")), None)
                inline = "".join(t.text or "" for t in c.iter() if t.tag.endswith("}t"))
                if c.get("t") == "s" and v is not None:
                    v = shared[int(v)] if int(v) < len(shared) else v
                cells.append(f"{c.get('r', '')}={inline or v or ''}")
            rows.append("\t".join(cells))
    return rows


def document_lines(path: str, data: bytes | None = None) -> list[str] | None:
    """The text of a Word, Excel or PowerPoint document (they are zip files of XML, read with what Python ships),
    from the file at `path` or from its bytes; None for anything else. The kind is told by what the package holds
    when the name does not say it, so a copy kept under another name (checkpoint.py) reads as the document it is."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if data is None:
            with open(path, "rb") as f:
                if f.read(4) != b"PK\x03\x04":
                    return None
        with zipfile.ZipFile(io.BytesIO(data) if data is not None else path) as z:
            names = set(z.namelist())
            kind = ext if ext in office.KINDS else next((k for part, k in _MAIN_PARTS.items() if part in names), "")
            if kind == ".docx":
                rows = _word(z.read("word/document.xml"))
                # Headers and footers after the body, as edit_file reaches them too; a page number alone is left out.
                for name in sorted(n for n in names if re.match(r"word/(header|footer)\d*\.xml$", n)):
                    words = [line for line in _word(z.read(name)) if not line.strip().isdigit()]
                    if words:
                        rows += [f"[{'header' if 'header' in name else 'footer'}]", *words]
                return rows
            if kind == ".xlsx":
                return _xlsx(z)
            if kind != ".pptx":
                return None
            slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[0]))
            rows = []
            for n, name in enumerate(slides, 1):
                rows.append(f"[slide {n}]")
                rows += _xml_text(z.read(name), "t", "p")
            return rows
    except (OSError, zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError):
        return None


def pdf_lines(path: str) -> list[str] | str:
    """A PDF's text page by page, each page under a [page n] line; or a sentence for the model when there is none
    to give (pages that are pictures, a password, a damaged file)."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    name = os.path.basename(path)
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            return f"{name} is protected with a password, so its text cannot be read."
        rows, pages, empty = [], len(reader.pages), 0
        for n, page in enumerate(reader.pages[:PDF_PAGES], 1):
            lines = [line.rstrip() for line in (page.extract_text() or "").splitlines() if line.strip()]
            empty += not lines
            rows += [f"[page {n}]", *lines]
    except (PyPdfError, ValueError, KeyError, TypeError) as e:
        return f"{name} could not be read as a PDF ({type(e).__name__}): the file may be damaged."
    if empty == min(pages, PDF_PAGES):
        return (f"{name} is a PDF of {pages} page{'s' if pages != 1 else ''} with no text in it: its pages are "
                "pictures (a scan or photos), so their words cannot be read here. open with show true opens it for "
                "them in their PDF reader.")
    if pages > PDF_PAGES:
        rows.append(f"[{pages - PDF_PAGES} more pages not read]")
    return rows


# ---------------------------------------------------------------- read, list, search

def read(path: str, offset: int = 1, limit: int = READ_LINES) -> str:
    """A file for the model: numbered lines of text in any common encoding, a document's text, or a sentence
    saying what a binary file is."""
    if os.path.isdir(path):
        return f"{path} is a folder, not a file: list it with list_files."
    if not os.path.isfile(path):
        return f"There is no file {path}. List the folder with list_files to see what is there."
    stat = os.stat(path)
    pdf = os.path.splitext(path)[1].lower() == ".pdf"
    lines = pdf_lines(path) if pdf else document_lines(path)
    if isinstance(lines, str):
        return lines
    how = ""
    if pdf:
        how = f", text of the PDF, {sum(line.startswith('[page ') for line in lines)} pages read"
    elif lines is None:
        with open(path, "rb") as f:
            data = f.read(TEXT_MAX + 1)
        text = decode(data[:TEXT_MAX])
        if text is None:
            return (f"{os.path.basename(path)} is not text: a {kind_of(path)} of {size(stat.st_size)}, last changed "
                    f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))}. open with show true opens it "
                    "in its own program.")
        lines = text[0].splitlines()
        how = f", {text[1]}" + (", first 10 MB only" if len(data) > TEXT_MAX else "")
    else:
        how = f", text of the {kind_of(path)} document"
    total = len(lines)
    start = max(1, offset)
    chosen = lines[start - 1:start - 1 + max(1, min(limit, READ_MAX))]
    body, used = [], 0
    for n, line in enumerate(chosen, start):
        row = f"{n:>5}\t{line[:LINE_CHARS]}" + (" […]" if len(line) > LINE_CHARS else "")
        used += len(row) + 1
        if used > ANSWER_CHARS:
            break
        body.append(row)
    end = start + len(body) - 1
    head = f"{path} ({size(stat.st_size)}{how}; lines {start}-{end} of {total})"
    more = f"\n[{total - end} more lines: read again with offset {end + 1}]" if end < total else ""
    return head + "\n" + "\n".join(body) + more


def _walk(root: str, places, deep: bool, most: int = WALK_MOST):
    """(entry, is a link) under `root`: links and junctions are named but never followed, protected places
    skipped; (None, False) last when it stopped at `most` entries."""
    from .run import _junction
    stack, seen = [root], 0
    while stack and seen < most:
        try:
            entries = sorted(os.scandir(stack.pop()), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if places.blocked(norm(entry.path), False):
                continue
            link = entry.is_symlink() or (entry.is_dir(follow_symlinks=False) and _junction(entry.path))
            yield entry, link
            if deep and not link and entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
    if stack:
        yield None, False


def _folder_total(path: str, places, most: int) -> tuple[int, int, bool]:
    """(files, bytes, whether it stopped at `most` entries) of everything in a folder."""
    files = total = 0
    for entry, link in _walk(path, places, True, most):
        if entry is None:
            return files, total, True
        if not link and entry.is_file(follow_symlinks=False):
            files += 1
            total += entry.stat(follow_symlinks=False).st_size
    return files, total, False


def listing(path: str, places, pattern: str = "", recursive: bool = False, sort: str = "name") -> str:
    """Files and folders under `path` with sizes and dates; a folder's own total when not recursive."""
    if not os.path.isdir(path):
        return f"There is no folder {path}." if not os.path.exists(path) else f"{path} is a file: read it with read_file."
    rows, cut, budget = [], False, WALK_MOST
    for entry, link in _walk(path, places, recursive):
        if entry is None:
            cut = True
            break
        is_dir = entry.is_dir(follow_symlinks=False) and not link
        if pattern and not fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
            continue
        if pattern and is_dir and recursive:
            continue
        stat = entry.stat(follow_symlinks=False)
        if link:
            rows.append((entry.path, 0, stat.st_mtime, "link"))
        elif is_dir and recursive:
            rows.append((entry.path, 0, stat.st_mtime, "folder"))
        elif is_dir:
            # Each folder's total, walked within what is left of one budget for the whole listing.
            count, total, cut_here = _folder_total(entry.path, places, max(1, budget))
            budget -= count + 1
            rows.append((entry.path, total, stat.st_mtime,
                         f"folder, {'at least ' if cut_here else ''}{count} files"))
        else:
            rows.append((entry.path, stat.st_size, stat.st_mtime, ""))
    key = {"size": lambda r: -r[1], "date": lambda r: -r[2]}.get(sort, lambda r: r[0].lower())
    rows.sort(key=key)
    files = [r for r in rows if not r[3]]
    head = (f"{path}: {len(files)} files ({size(sum(r[1] for r in files))})"
            + (f", {len(rows) - len(files)} folders or links" if len(rows) > len(files) else "")
            + (f" matching {pattern}" if pattern else "") + (", everything inside" if recursive else "")
            + f", sorted by {sort if sort in ('size', 'date') else 'name'}"
            + (f"; stopped after {WALK_MOST} entries" if cut else ""))
    lines = []
    for full, n, mtime, what in rows[:LIST_ROWS]:
        rel = os.path.relpath(full, path)
        shown = "" if what == "link" else size(n) if (not what or not recursive) else ""
        lines.append(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}  {shown:>9}  {rel}"
                     + (f"  [{what}]" if what else ""))
    more = f"\n[{len(rows) - LIST_ROWS} more not shown]" if len(rows) > LIST_ROWS else ""
    return head + "\n" + ("\n".join(lines) or "(empty)") + more


def search(path: str, text: str, places, pattern: str = "") -> str:
    """Lines holding `text` (any case) in the text files under `path`, in every common encoding."""
    if not os.path.isdir(path):
        return f"There is no folder {path}."
    found, files, hits = [], 0, set()
    needle = text.lower()
    for entry, link in _walk(path, places, True):
        if entry is None:
            found.append(f"[stopped after {WALK_MOST} entries]")
            break
        if link or not entry.is_file(follow_symlinks=False):
            continue
        if pattern and not fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
            continue
        # The name is matched first, so a binary or a large file is found by it too.
        if needle in entry.name.lower():
            hits.add(entry.path)
            if len(found) < SEARCH_ROWS:
                found.append(f"{os.path.relpath(entry.path, path)}: (the name holds it)")
        if entry.stat(follow_symlinks=False).st_size > TEXT_MAX:
            continue
        files += 1
        lines = document_lines(entry.path)
        if lines is None:
            try:
                with open(entry.path, "rb") as f:
                    decoded = decode(f.read())
            except OSError:
                continue
            if decoded is None:
                continue
            lines = decoded[0].splitlines()
        for n, line in enumerate(lines, 1):
            if needle in line.lower():
                hits.add(entry.path)
                if len(found) < SEARCH_ROWS:
                    found.append(f"{os.path.relpath(entry.path, path)}:{n}: {line.strip()[:300]}")
    head = f"Searched {files} files under {path} for {text!r}: {len(hits)} files hold it"
    return head + ("\n" + "\n".join(found) if found else "") + (
        "\n[more lines not shown]" if len(found) >= SEARCH_ROWS else "")


# ---------------------------------------------------------------- changes

def read_for_change(path: str) -> tuple[str, str, bytes]:
    """(text, encoding, the bytes as they are) of a text file about to be changed; ValueError says why not."""
    if not os.path.isfile(path):
        raise ValueError(f"There is no file {path}; write_file makes a new one.")
    if os.path.getsize(path) > TEXT_MAX:
        raise ValueError(f"{path} is larger than 10 MB, too large to edit this way.")
    with open(path, "rb") as f:
        data = f.read()
    decoded = decode(data)
    if decoded is None or document_lines(path) is not None:
        raise ValueError(f"{os.path.basename(path)} is not a plain text file ({kind_of(path)}), so it cannot be "
                         "edited as text.")
    return decoded[0], decoded[1], data


def document_for_change(path: str) -> bytes:
    """The bytes of a Word, Excel or PowerPoint file about to be changed; ValueError says why not."""
    if not os.path.isfile(path):
        raise ValueError(f"There is no file {path}; write_file makes a new one.")
    if os.path.getsize(path) > TEXT_MAX:
        raise ValueError(f"{path} is larger than 10 MB, too large to change this way.")
    with open(path, "rb") as f:
        return f.read()


def replaced(text: str, old: str, new: str, every: bool) -> str:
    """`text` with `old` replaced by `new`: exactly once unless `every`; ValueError says what went wrong."""
    if not old:
        raise ValueError("old_string is empty: give the exact text to replace.")
    crlf = "\r\n" in text
    if old not in text and crlf and old.replace("\r\n", "\n").replace("\n", "\r\n") in text:
        old, new = old.replace("\r\n", "\n").replace("\n", "\r\n"), new.replace("\r\n", "\n").replace("\n", "\r\n")
    count = text.count(old)
    if count == 0:
        near = difflib.get_close_matches(old.strip().splitlines()[0] if old.strip() else old,
                                         [line.strip() for line in text.splitlines()], n=2, cutoff=0.5)
        hint = ("; the nearest lines are: " + " | ".join(near)) if near else ""
        raise ValueError(f"old_string was not found in the file (it must match exactly, without the line numbers "
                         f"read_file shows){hint}")
    if count > 1 and not every:
        raise ValueError(f"old_string is in the file {count} times: give more of the text around it so it is found "
                         "once, or set replace_all to change every one")
    return text.replace(old, new) if every else text.replace(old, new, 1)


def diff(before: list[str], after: list[str], name: str, most: int = DIFF_LINES) -> str:
    """The unified difference of two texts' lines, as coding agents show an edit: @@ hunks with three lines around
    each change, whole lines with their indentation; at most `most` lines, then how many more."""
    lines = list(difflib.unified_diff(before, after, name, name, lineterm=""))[2:]
    return "\n".join(lines[:most]) + (f"\n… +{len(lines) - most}" if len(lines) > most else "")


def recycle(paths: list[str]) -> bool:
    """Moves files and folders to the Recycle Bin (SHFileOperation with undo); True when Windows did it."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    # FO_DELETE; FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_WANTNUKEWARNING off.
    op = SHFILEOPSTRUCTW(None, 3, "\0".join(os.path.abspath(p) for p in paths) + "\0\0", None,
                         0x0004 | 0x0010 | 0x0040 | 0x0400, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


# The share of a drive its Recycle Bin holds when the person never set it (Windows' own default).
BIN_SHARE = 0.05
BIN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"


def bin_keeps(paths: list[str], size: int) -> bool:
    """Whether the Recycle Bin takes these `size` bytes back whole: each path on a fixed drive of this computer whose
    bin is not set to delete at once, and the bytes within what that bin holds. Past that Windows deletes for good,
    without a word, so such a delete is costly (cardwait.COSTLY)."""
    if sys.platform != "win32":
        return True
    import ctypes
    import winreg
    for path in paths:
        root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            return False
        volume = ctypes.create_unicode_buffer(64)
        if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(root, volume, 64):
            return False
        guid = volume.value[volume.value.find("{"):volume.value.find("}") + 1]
        set_to = {"NukeOnDelete": 0, "MaxCapacity": shutil.disk_usage(root).total * BIN_SHARE / 1024 / 1024}
        with contextlib.suppress(OSError), winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{BIN_KEY}\\{guid}") as key:
            for name in set_to:
                with contextlib.suppress(OSError):
                    set_to[name] = winreg.QueryValueEx(key, name)[0]
        if set_to["NukeOnDelete"] or size > set_to["MaxCapacity"] * 1024 * 1024:
            return False
    return True


def move(moves: list[dict], copy: bool) -> list[str]:
    """Does the moves or copies in turn, never replacing a file; what was done, as (from, to) lines."""
    done = []
    for m in moves:
        if m["folder"]:
            os.makedirs(m["folder"], exist_ok=True)
        if copy and os.path.isdir(m["from"]):
            shutil.copytree(m["from"], m["to"], symlinks=True)
        elif copy:
            shutil.copy2(m["from"], m["to"])
        else:
            shutil.move(m["from"], m["to"])
        done.append(m["to"])
    return done
