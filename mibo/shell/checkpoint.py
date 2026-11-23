"""Each turn's changes to files, kept so the person can take the whole turn back with one press.

As Claude Code's checkpoints and Gemini CLI's /restore do: before a file tool or a command changes a file, the
file as it was is copied to runtime/checkpoints/<turn>/; what was made, moved or moved to the Recycle Bin is listed
beside it (turn.json). Under the reply the fold 本次改动 lists them with their differences, and 撤销这次的改动 puts
each back, newest first, leaving alone a file that was changed again since. Every turn keeps its own, so any
earlier turn can be taken back too. A command's other effects (a program it ran, the network) are not kept.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import time
import zipfile
from pathlib import Path

from . import files, office
from .paths import _matches

# A file larger than this is listed but not copied, so it cannot be put back.
KEEP_MAX = 20 * 1024 * 1024
# Turns whose copies are kept; older ones keep their list only.
TURNS_KEPT = 30
# Places a wildcard is expanded to.
EXPAND_MOST = 2000


def _hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------- the Recycle Bin

def _filetime(ft: int) -> float:
    return (ft - 116444736000000000) / 1e7


def _bin_entries(path: str) -> list[tuple[Path, float]]:
    """The Recycle Bin's records ($I files) of items deleted from `path`, with the time each was deleted. Only the
    person's own folder of the drive's bin can be read, so only theirs are found."""
    found = []
    root = Path(os.path.splitdrive(os.path.abspath(path))[0] + "\\$Recycle.Bin")
    try:
        folders = list(root.iterdir())
    except OSError:
        return found
    for folder in folders:
        try:
            infos = list(folder.glob("$I*"))
        except OSError:
            continue
        for info in infos:
            try:
                data = info.read_bytes()
            except OSError:
                continue
            version, _, when = struct.unpack("<qqq", data[:24])
            if version == 2:
                count = struct.unpack("<i", data[24:28])[0]
                original = data[28:28 + 2 * count].decode("utf-16-le", errors="replace").rstrip("\0")
            else:
                original = data[24:24 + 520].decode("utf-16-le", errors="replace").split("\0")[0]
            if os.path.normcase(original) == os.path.normcase(path):
                found.append((info, _filetime(when)))
    return found


def in_bin(path: str, since: float = 0.0) -> Path | None:
    """The bin's record of `path` deleted at or after `since` (the latest), or None."""
    entries = [e for e in _bin_entries(path) if e[1] >= since - 2]
    return max(entries, key=lambda e: e[1])[0] if entries else None


def unrecycle(path: str, since: float = 0.0) -> bool:
    """Puts `path` back from the Recycle Bin as Explorer's Restore does: its $R item moved back to where it was,
    its $I record removed. False when it is not in the bin or something is at `path` now."""
    info = in_bin(path, since)
    if info is None or os.path.lexists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.replace(info.with_name("$R" + info.name[2:]), path)
    info.unlink()
    return True


# ---------------------------------------------------------------- what a command will change

def _expand(act) -> list[str]:
    """The places an act names now: its wildcards expanded, else its paths."""
    if not act.wild:
        return list(act.paths)
    out = []
    for glob in act.globs:
        out += _matches(glob, EXPAND_MOST) if any(c in glob for c in "*?[") else [glob]
    return out[:EXPAND_MOST]


def targets(read_) -> tuple[list[str], list[tuple[str, str]]]:
    """From a command's reading: (files and folders it may make or change, kept before it runs; (from, to) of what
    it may move). Deletes need none: they go to the Recycle Bin and are listed as it runs."""
    paths, moves = [], []
    for act in read_.acts:
        if act.kind not in ("change", "overwrite", "unknown") or act.unresolved:
            continue
        if act.kind == "unknown" and not act.write:
            continue
        sources = _expand(act)
        if act.dest and act.what in ("copy", "move", "rename", "zip"):
            for src in sources:
                to = act.dest if act.what in ("rename", "zip") or not os.path.isdir(act.dest) else (
                    os.path.join(act.dest, os.path.basename(src.rstrip("\\/"))))
                paths.append(to)
                if act.what in ("move", "rename"):
                    moves.append((src, to))
        elif act.dest and act.what == "unzip":
            for src in sources:
                try:
                    with zipfile.ZipFile(src) as z:
                        top = {name.replace("\\", "/").split("/")[0] for name in z.namelist()}
                except (OSError, zipfile.BadZipFile):
                    top = set()
                paths += [os.path.join(act.dest, name) for name in top if name] or [act.dest]
        else:
            paths += sources
    return list(dict.fromkeys(paths)), moves


# ---------------------------------------------------------------- one turn

class Turn:
    """The changes of one turn: turn.json holds the list, n.before (and n.after for text) the copies."""

    def __init__(self, root: Path, turn: str):
        self.dir = root / turn
        self.file = self.dir / "turn.json"
        self.state = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {
            "started": time.time(), "items": [], "undone": False}
        # Before a change: path -> (kind, hash, copy) as it was; when the change began.
        self.pending: dict[str, tuple] = {}
        self.began = time.time()

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")

    def _copy(self, path: str, tag: str) -> str:
        """A copy of the file at `path` in the turn's folder, or "" when it is too large to keep."""
        if os.path.getsize(path) > KEEP_MAX:
            return ""
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}.{tag}"
        shutil.copy2(path, self.dir / name)
        return name

    def before(self, paths: list[str]) -> None:
        """Called before a change to `paths`: each as it is now (a file is copied)."""
        self.began = time.time()
        for path in paths:
            if path in self.pending:
                continue
            if os.path.isfile(path) and not os.path.islink(path):
                self.pending[path] = ("file", _hash(path), self._copy(path, "before"))
            else:
                self.pending[path] = ("dir" if os.path.isdir(path) else "none", "", "")

    def after(self, moves: list[tuple[str, str]] = (), recycled: list[str] = ()) -> int:
        """Called after the change: what was made, changed, moved or moved to the bin is listed, in the order undo
        reverses (folders made first, files made or changed last); how many."""
        items = self.state["items"]
        added, merged = len(items), 0
        made = [p for p, (kind, _, _) in self.pending.items() if kind == "none" and os.path.isdir(p)]
        items += [{"op": "created", "path": p, "dir": True} for p in made]
        moved_to = set()
        for src, to in moves:
            # Into a folder the same command made, the item lands inside it by its own name.
            inside = os.path.join(to, os.path.basename(src.rstrip("\\/")))
            to = inside if os.path.isdir(to) and os.path.lexists(inside) else to
            if not os.path.lexists(src) and os.path.lexists(to):
                items.append({"op": "moved", "path": src, "dest": to})
                moved_to.add(os.path.normcase(to))
        for path in recycled:
            items.append({"op": "deleted", "path": path, "at": self.began})
        for path, (kind, digest, copy) in self.pending.items():
            if os.path.normcase(path) in moved_to or path in made:
                continue
            if kind == "none" and os.path.lexists(path):
                item = {"op": "created", "path": path, "dir": False}
            elif kind == "file" and os.path.isfile(path) and _hash(path) != digest:
                item = {"op": "changed", "path": path, "before": copy}
            else:
                continue
            if os.path.isfile(path):
                item["hash"] = _hash(path)
                with open(path, "rb") as f:
                    head = f.read(4096)
                if files.decode(head) is not None or files.document_lines(path) is not None:
                    item["after"] = self._copy(path, "after")
            # A file made or changed earlier in the turn stays one row: its first state, its latest.
            prior = next((i for i in items[:added] if i["path"] == path and i["op"] in ("created", "changed")), None)
            if prior:
                prior.update({k: item[k] for k in ("hash", "after") if k in item})
                merged += 1
            else:
                items.append(item)
        self.pending = {}
        if len(items) > added or merged:
            self.save()
        return len(items) - added + merged

    # ------------------------------------------------------------ shown under the reply

    def _text(self, name: str, path: str) -> list[str] | None:
        """The lines of a kept copy, read as files.read reads (a document's text too); None for a binary file."""
        if not name or not (self.dir / name).exists():
            return None
        copy = str(self.dir / name)
        lines = files.document_lines(copy) if os.path.splitext(path)[1].lower() in office.KINDS else None
        if lines is not None:
            return lines
        decoded = files.decode((self.dir / name).read_bytes())
        return decoded[0].splitlines() if decoded else None

    def view(self) -> dict:
        """{"items": [{"op", "path", "dest", "diff"}], "undone", "kept"} for the fold."""
        shown = []
        for item in self.state["items"]:
            row = {k: item[k] for k in ("op", "path", "dest", "dir") if k in item}
            if item["op"] in ("changed", "created") and not item.get("dir"):
                old = [] if item["op"] == "created" else self._text(item.get("before", ""), item["path"])
                new = self._text(item.get("after", ""), item["path"])
                if old is not None and new is not None:
                    row["diff"] = files.diff(old, new, os.path.basename(item["path"]))
                    row["added"] = sum(line.startswith("+") for line in row["diff"].split("\n"))
                    row["removed"] = sum(line.startswith("-") for line in row["diff"].split("\n"))
            shown.append(row)
        return {"items": shown, "undone": self.state["undone"], "kept": not self.state.get("expired")}

    # ------------------------------------------------------------ taken back

    def undo(self) -> dict:
        """Puts the turn's changes back, newest first: {"done": n, "left": [paths not put back]}. A file changed again
        since this turn is left as it is now; something made is moved to the Recycle Bin, not deleted."""
        done, left = 0, []
        for item in reversed(self.state["items"]):
            path, op = item["path"], item["op"]
            ok = False
            if op == "created":
                # A folder made goes to the bin whole, as undoing a copy in Explorer does; a file only as the turn
                # left it.
                same = os.path.isdir(path) if item.get("dir") else (os.path.isfile(path) and _hash(path) == item.get("hash"))
                ok = same and files.recycle([path])
            elif op == "changed":
                copy = self.dir / item["before"] if item.get("before") else None
                if copy and copy.exists() and os.path.isfile(path) and _hash(path) == item.get("hash"):
                    shutil.copy2(copy, path)
                    ok = True
            elif op == "moved":
                if os.path.lexists(item["dest"]) and not os.path.lexists(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    shutil.move(item["dest"], path)
                    ok = True
            elif op == "deleted":
                ok = unrecycle(path, item["at"])
            done += ok
            if not ok:
                left.append(path)
        self.state["undone"] = True
        self.save()
        return {"done": done, "left": left}


class Checkpoints:
    """runtime/checkpoints: one folder a turn."""

    def __init__(self, home: Path):
        self.root = Path(home) / "runtime" / "checkpoints"

    def turn(self, turn: str) -> Turn:
        return Turn(self.root, os.path.basename(turn))

    def has(self, turn: str) -> bool:
        return (self.root / os.path.basename(turn) / "turn.json").exists()

    def prune(self) -> None:
        """Copies are kept for the newest TURNS_KEPT turns; older turns keep their list, marked so."""
        turns = sorted((p for p in self.root.iterdir() if (p / "turn.json").exists()), key=lambda p: p.stat().st_mtime)
        for folder in turns[:-TURNS_KEPT]:
            state = json.loads((folder / "turn.json").read_text(encoding="utf-8"))
            if state.get("expired"):
                continue
            for copy in folder.iterdir():
                if copy.name != "turn.json":
                    copy.unlink()
            state["expired"] = True
            (folder / "turn.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
