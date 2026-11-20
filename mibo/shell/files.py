"""The file tools' own work, done in the page server after the gate let it through (panel.Shell.file).

Each file tool is judged as the PowerShell command that does the same thing (`equivalent`), by the same
read and judge as a command the model writes, so a folder, a card or a refusal comes the same way. What runs
afterwards is Python, which can do what PowerShell 5.1 does badly for a model: read text in whatever encoding
it is in, list and search without following links or opening protected files, show an edit as a difference,
and delete to the Recycle Bin.
"""
from __future__ import annotations

import codecs
import difflib
import fnmatch
import mimetypes
import os
import re
import shutil
import time
import zipfile
from xml.etree import ElementTree

from .grants import norm

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


def quoted(text: str) -> str:
    """A PowerShell single-quoted string."""
    return "'" + text.replace("'", "''") + "'"


# ---------------------------------------------------------------- the equivalent commands the gate judges

def equivalent(op: str, args: dict) -> str:
    """The PowerShell command doing what the file tool `op` does, with absolute paths, as the gate reads it."""
    if op == "read":
        return f"Get-Content -LiteralPath {quoted(args['path'])}"
    if op == "list":
        return (f"Get-ChildItem -LiteralPath {quoted(args['path'])}" + (" -Recurse" if args.get("recursive") else "")
                + (f" -Filter {quoted(args['pattern'])}" if args.get("pattern") else ""))
    if op == "search":
        # The folder as one named place: what is searched inside it skips protected files one by one (_walk).
        return f"Select-String -LiteralPath {quoted(args['path'])} -Pattern {quoted(args['text'])} -SimpleMatch"
    if op == "write":
        parent = os.path.dirname(args["path"])
        made = "" if os.path.isdir(parent) else f"New-Item -ItemType Directory -Path {quoted(parent)} -Force; "
        return f"{made}Set-Content -LiteralPath {quoted(args['path'])} -Value ''"
    if op == "open":
        target = args["path"]
        if re.match(r"^https?://", target, re.IGNORECASE):
            return f"Start-Process {quoted(target)}"
        return f"Invoke-Item -LiteralPath {quoted(target)}"
    if op == "move":
        parts = []
        for folder in dict.fromkeys(m["folder"] for m in args["moves"] if m["folder"] and not os.path.isdir(m["folder"])):
            parts.append(f"New-Item -ItemType Directory -Path {quoted(folder)} -Force")
        for m in args["moves"]:
            if args.get("copy"):
                parts.append(f"Copy-Item -LiteralPath {quoted(m['from'])} -Destination {quoted(m['to'])}"
                             + (" -Recurse" if os.path.isdir(m["from"]) else ""))
            elif os.path.dirname(m["from"].rstrip("\\/")).lower() == os.path.dirname(m["to"]).lower():
                parts.append(f"Rename-Item -LiteralPath {quoted(m['from'])} -NewName {quoted(os.path.basename(m['to']))}")
            else:
                parts.append(f"Move-Item -LiteralPath {quoted(m['from'])} -Destination {quoted(m['to'])}")
        return "; ".join(parts)
    if op == "delete":
        deep = any(os.path.isdir(p) for p in args["paths"])
        return f"Remove-Item -LiteralPath {', '.join(quoted(p) for p in args['paths'])}" + (" -Recurse" if deep else "")
    raise ValueError(op)


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


def document_lines(path: str) -> list[str] | None:
    """The text of a .docx, .xlsx or .pptx (they are zip files of XML, read with what Python ships); None for
    other kinds or a file that is not what its name says."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".docx", ".xlsx", ".pptx"):
        return None
    try:
        with zipfile.ZipFile(path) as z:
            if ext == ".docx":
                return _xml_text(z.read("word/document.xml"), "t", "p")
            if ext == ".xlsx":
                return _xlsx(z)
            slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[0]))
            rows = []
            for n, name in enumerate(slides, 1):
                rows.append(f"[slide {n}]")
                rows += _xml_text(z.read(name), "t", "p")
            return rows
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError):
        return None


# ---------------------------------------------------------------- read, list, search

def read(path: str, offset: int = 1, limit: int = READ_LINES) -> str:
    """A file for the model: numbered lines of text in any common encoding, a document's text, or a sentence
    saying what a binary file is."""
    if os.path.isdir(path):
        return f"{path} is a folder, not a file: list it with list_files."
    if not os.path.isfile(path):
        return f"There is no file {path}. List the folder with list_files to see what is there."
    stat = os.stat(path)
    lines = document_lines(path)
    how = ""
    if lines is None:
        if os.path.splitext(path)[1].lower() == ".pdf":
            return (f"{os.path.basename(path)} is a PDF of {size(stat.st_size)}. Its text cannot be read with what "
                    "this app has; open_file opens it for them in their PDF reader.")
        with open(path, "rb") as f:
            data = f.read(TEXT_MAX + 1)
        text = decode(data[:TEXT_MAX])
        if text is None:
            return (f"{os.path.basename(path)} is not text: a {kind_of(path)} of {size(stat.st_size)}, last changed "
                    f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))}. open_file opens it in its "
                    "own program.")
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
        if needle in os.path.basename(entry.path).lower():
            hits.add(entry.path)
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
