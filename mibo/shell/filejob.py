"""A file tool's job (panel.Shell.file): made ready and checked before the gate, with absolute paths, so the
error a model can fix comes back at once with no question; then done in Python once the gate let it through."""
from __future__ import annotations

import os
import re

from . import files, office, words
from .grants import Grants, norm
from .run import _junction

# Items looked at in the granted folders when finding a file the model named badly.
FIND_MOST = 20000
_WEB = re.compile(r"^https?://", re.IGNORECASE)


def _missing(path: str) -> ValueError:
    return ValueError(f"There is no {path}. List the folder with list_files to find its exact name.")


def _found(raw: str, grants: Grants) -> str:
    """The one item in the granted folders named as a badly built path ends ("t27 里 预算.xlsx" finds
    t27/预算.xlsx), as coding agents point a missing path to the file that is there; "" for none or several.
    Folder names written before the name pick among several. Nothing outside the granted folders is looked at."""
    parts = [w.lower() for w in re.split(r"[\\/\s]+", raw) if w]
    hits: dict[str, str] = {}
    seen = 0
    for root in grants.folders():
        stack = [root]
        while stack and seen < FIND_MOST:
            try:
                entries = list(os.scandir(stack.pop()))
            except OSError:
                continue
            for entry in entries:
                seen += 1
                if entry.name.lower() == parts[-1]:
                    hits[norm(entry.path)] = entry.path
                if entry.is_dir(follow_symlinks=False) and not entry.is_symlink() and not _junction(entry.path):
                    stack.append(entry.path)
    found = list(hits.values())
    if len(found) > 1:
        found = [p for p in found if os.path.basename(os.path.dirname(p)).lower() in parts[:-1]]
    return found[0] if len(found) == 1 else ""


def _place(raw: str, base: str, grants: Grants, find: bool = False) -> str:
    """A path the model gave, absolute: relative ones from the working folder, ~ and %VARS% opened. With
    `find`, one that is not there is looked for in the granted folders by its name (_found)."""
    text = os.path.expandvars(os.path.expanduser(str(raw or "").strip().strip('"')))
    place = os.path.normpath(os.path.join(base, text)) if text else base
    return (_found(text, grants) or place) if find and text and not os.path.exists(place) else place


def _look(op: str, args: dict, base: str, grants: Grants) -> dict:
    """read, list, search or open."""
    raw = str(args.get("path") or "").strip()
    path = raw if op == "open" and _WEB.match(raw) else _place(args.get("path") or "", base, grants, True)
    if op == "read" and not os.path.exists(path) and grants.root_of(norm(path)):
        raise _missing(path)
    job = {"op": op, "path": path, "folder": path if op in ("list", "search") else os.path.dirname(path)}
    if op == "search":
        job["text"] = str(args.get("text") or "")
        if not job["text"]:
            raise ValueError("Give the text to look for.")
    if op in ("list", "search"):
        job.update(pattern=str(args.get("pattern") or ""), recursive=bool(args.get("recursive")),
                   sort=str(args.get("sort") or "name"))
    if op == "read":
        job.update(offset=int(args.get("offset") or 1), limit=int(args.get("limit") or files.READ_LINES))
    if op == "open" and not job["path"].lower().startswith("http") and not os.path.exists(path):
        raise _missing(path)
    return job


def _text_change(op: str, path: str, args: dict) -> tuple[dict, list[str], list[str]]:
    """write_file or edit_file on a text file: the new bytes in the file's own encoding and line ends, with the two
    texts' lines."""
    if op == "write":
        text = str(args.get("content") if args.get("content") is not None else "")
        before, encoding, data = files.read_for_change(path) if os.path.isfile(path) else ("", "utf-8", None)
        after = text.replace("\r\n", "\n").replace("\n", "\r\n") if "\r\n" in before else text
    else:
        before, encoding, data = files.read_for_change(path)
        after = files.replaced(before, str(args.get("old_string") or ""),
                               str(args.get("new_string") or ""), bool(args.get("replace_all")))
        if after == before:
            raise ValueError("old_string and new_string are the same: nothing would change.")
    job = {"op": "write", "kind": op, "path": path, "folder": os.path.dirname(path),
           "bytes": files.encode(after, encoding), "before": data}
    return job, before.splitlines(), after.splitlines()


def _document(op: str, path: str, ext: str, args: dict) -> tuple[dict, list[str], list[str]]:
    """write_file or edit_file on a Word, Excel or PowerPoint file (office/): the document made from the model's
    Markdown, or the one there changed by exact replacement inside it; with the two documents' text, from which
    the question's difference is taken."""
    name = os.path.basename(path)
    data = files.document_for_change(path) if op == "edit" or os.path.isfile(path) else None
    if op == "write":
        text = str(args.get("content") or "")
        if not text.strip():
            raise ValueError(f"content is empty: give what {name} holds, written as Markdown.")
        made = office.make(ext, text)
    else:
        old, new = str(args.get("old_string") or ""), str(args.get("new_string") or "")
        if old == new:
            raise ValueError("old_string and new_string are the same: nothing would change.")
        made = office.replaced(ext, data, old, new, bool(args.get("replace_all")), name)
    job = {"op": "write", "kind": op, "path": path, "folder": os.path.dirname(path), "bytes": made,
           "before": data, "document": office.summary(ext, made)}
    # A file there that is not a readable document is replaced whole; its question shows all of the new text.
    before = (files.document_lines(path, data) if data is not None else None) or []
    return job, before, files.document_lines(path, made) or []


def _write(op: str, args: dict, base: str, grants: Grants) -> dict:
    """write or edit, with the question's title and difference when a file there is replaced or changed."""
    path = _place(args.get("path") or "", base, grants, op == "edit")
    name, ext = os.path.basename(path), os.path.splitext(path)[1].lower()
    if os.path.isdir(path):
        raise ValueError(f"{path} is a folder.")
    if ext in office.OLD:
        raise ValueError(f"{ext} is the {office.NAMES[office.OLD[ext]]} format from before 2007, which is not "
                         f"written here. Write {os.path.splitext(name)[0]}{office.OLD[ext]} instead: it opens "
                         "in the same program.")
    if ext == ".pdf" and op == "write":
        raise ValueError("write_file does not make PDFs. Make the document as a .docx instead; Word saves it "
                         "as a PDF (另存为 PDF) when they need one.")
    if ext in office.KINDS:
        job, before_lines, after_lines = _document(op, path, ext, args)
    else:
        job, before_lines, after_lines = _text_change(op, path, args)
    if job["before"] is not None:
        job["card"] = {lang: {"title": (f"修改「{name}」的内容" if lang == "zh" else f"Change the text of “{name}”")
                              if op == "edit" else (f"用新内容替换「{name}」" if lang == "zh"
                                                    else f"Replace “{name}” with new text"),
                              "lines": []} for lang in ("zh", "en")}
        job["card"]["diff"] = files.diff(before_lines, after_lines, name)
        job["said"] = {"zh": f"修改「{name}」", "en": f"Changed “{name}”"}
    elif ext in office.KINDS:
        job["said"] = {"zh": f"生成「{name}」", "en": f"Made “{name}”"}
    return job


def _move(args: dict, base: str, grants: Grants) -> dict:
    moves, copy = [], bool(args.get("copy"))
    for item in args.get("moves") or []:
        if not isinstance(item, dict) or not item.get("from") or not item.get("to"):
            raise ValueError("Each move needs from and to.")
        src, raw_to = _place(item["from"], base, grants, True), str(item["to"])
        if not os.path.exists(src):
            raise _missing(src)
        dest = _place(raw_to, base, grants)
        into = raw_to.endswith(("\\", "/")) or os.path.isdir(dest)
        target = os.path.join(dest, os.path.basename(src.rstrip("\\/"))) if into else dest
        if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(src):
            raise ValueError(f"{target} is already there; nothing is replaced this way. Choose another name, or "
                             "delete that one first with delete_files.")
        # Two moves landing on one name: the second would replace the first (shutil.move copies over a file).
        if any(os.path.normcase(m["to"]) == os.path.normcase(target) for m in moves):
            raise ValueError(f"Two of the moves land on {target}, so one would replace the other; nothing was "
                             "moved. To move them into a folder, end `to` with \\.")
        moves.append({"from": src, "to": target, "folder": dest if into and not os.path.isdir(dest) else (
            "" if os.path.isdir(os.path.dirname(target)) else os.path.dirname(target))})
    if not moves:
        raise ValueError("Give at least one move.")
    return {"op": "move", "moves": moves, "copy": copy, "folder": os.path.dirname(moves[0]["from"]),
            "said": {lang: words.move_said(moves, copy, lang) for lang in ("zh", "en")}}


def _delete(args: dict, base: str, grants: Grants) -> dict:
    paths = [_place(p, base, grants, True) for p in args.get("paths") or [] if str(p).strip()]
    missing = [p for p in paths if not os.path.exists(p)]
    if not paths or missing:
        raise ValueError(f"There is no {missing[0]}." if missing else "Give the paths to delete.")
    what = ({lang: words.quote(os.path.basename(paths[0].rstrip("\\/")), lang) for lang in ("zh", "en")}
            if len(paths) == 1 else {"zh": f" {len(paths)} 项", "en": f"{len(paths)} items"})
    return {"op": "delete", "paths": paths, "folder": os.path.dirname(paths[0]),
            "said": {lang: words.file_doing("delete", {"paths": paths}, lang, done=True) for lang in ("zh", "en")},
            # The question says where they go; the gate's own lines below it say what is in them.
            "card": {"zh": {"title": f"将{what['zh']}移到回收站", "lines": []},
                     "en": {"title": f"Move {what['en']} to the Recycle Bin", "lines": []}}}


def prepare(op: str, args: dict, base: str, grants: Grants) -> dict:
    """What a file tool will do, with absolute paths from the working folder `base`, checked before the gate;
    ValueError says what the model can fix."""
    if op in ("read", "list", "search", "open"):
        return _look(op, args, base, grants)
    if op in ("write", "edit"):
        return _write(op, args, base, grants)
    if op == "move":
        return _move(args, base, grants)
    if op == "delete":
        return _delete(args, base, grants)
    raise ValueError(f"No file tool {op}.")


def _open(path: str, home) -> str:
    if os.environ.get("SHELL_OPEN_DRY"):
        # The measuring script (tools/computer_tasks.py) checks what would open without a window.
        return f"Opened {path} (not shown: SHELL_OPEN_DRY is set)."
    if _WEB.match(path):
        # A page for them to see: in the app's own browser; their default browser only when the app window is
        # not open.
        from ..browsed import _ask
        if _ask(home, "POST", "/api/browser/op", 20, json={"op": "show", "url": path}).get("status") == "ok":
            return f"Opened {path} in the app's browser, in front of them."
        os.startfile(path)
        return f"Opened {path} in their default browser: the app's own browser is not open."
    os.startfile(path)
    return f"Opened {path} with its default program."


def _write_file(job: dict) -> str:
    os.makedirs(os.path.dirname(job["path"]), exist_ok=True)
    try:
        with open(job["path"], "wb") as f:
            f.write(job["bytes"])
    except PermissionError as e:
        # Word, Excel and PowerPoint hold the file they have open.
        raise OSError(e.errno, "the file is open in another program or is read-only; ask them to close it "
                               "there, then write it again", job["path"]) from e
    done = f"{'Changed' if job['before'] is not None else 'Made'} {job['path']} ({files.size(len(job['bytes']))})"
    if job.get("document"):
        return (f"{done}: {job['document']}. The file is finished and saved; no program has to be opened to "
                "make it. open with show true shows it to them if they want to see it.")
    return done + "."


def perform(job: dict, grants: Grants, home) -> str:
    """Does a judged file tool's work; what came of it, for the model. OSError says what failed."""
    op = job["op"]
    if op == "read":
        return files.read(job["path"], job["offset"], job["limit"])
    if op == "list":
        return files.listing(job["path"], grants.places, job["pattern"], job["recursive"], job["sort"])
    if op == "search":
        return files.search(job["path"], job["text"], grants.places, job["pattern"])
    if op == "open":
        return _open(job["path"], home)
    if op == "write":
        return _write_file(job)
    if op == "move":
        files.move(job["moves"], job["copy"])
        verb = "Copied" if job["copy"] else "Moved"
        return "\n".join(f"{verb} {m['from']} -> {m['to']}" for m in job["moves"])
    if op == "delete":
        if not files.recycle(job["paths"]):
            raise OSError(0, "Windows did not move them to the Recycle Bin", job["paths"][0])
        return "Moved to the Recycle Bin: " + ", ".join(job["paths"])
    raise ValueError(op)
