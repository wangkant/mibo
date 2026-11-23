"""The durable memory files: ids, strict loading and the daily copy. No model
call and no Agent import."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shutil
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from .storage import atomic_write_text
from .textproc import _focus_tokens

logger = logging.getLogger("agent")

BAK_SUFFIX = ".bak"


class MemoryFileDamaged(RuntimeError):
    """A durable memory file does not load; the start stops and names the
    daily copy rather than starting empty."""

    def __init__(self, path: Path):
        path = Path(path)
        bak = path.with_name(path.name + BAK_SUFFIX)
        if bak.is_file():
            day = datetime.fromtimestamp(bak.stat().st_mtime).strftime("%Y-%m-%d")
            message = (f"The memory file {path} is damaged and was left untouched. "
                       f"A copy from {day} is at {bak}; move it in place of the damaged "
                       "file to start from it, or move the damaged file aside to start "
                       "with an empty memory.")
        else:
            message = (f"The memory file {path} is damaged and was left untouched, and "
                       "no earlier copy of it exists. Move the damaged file aside, for "
                       "example by renaming it, to start with an empty memory.")
        super().__init__(message)
        self.path = path
        self.backup = bak if bak.is_file() else None


def new_id(prefix: str, taken: Iterable[str] = ()) -> str:
    """prefix + 10 random hex characters, never one already in `taken`."""
    taken = set(taken)
    while True:
        candidate = prefix + secrets.token_hex(5)
        if candidate not in taken:
            return candidate


def token_hashes(text: str) -> list[str]:
    """What a tombstone keeps of a forgotten text: hashes of its focus tokens."""
    return sorted({hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16]
                   for tok in _focus_tokens(str(text or ""), "zh")})


def _read_strict(path: Path, shape: Callable[[object], bool]):
    """JSON from a durable file; None when it is absent, MemoryFileDamaged
    when it is not JSON or not the expected shape."""
    path = Path(path)
    try:
        blob = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryFileDamaged(path) from exc
    if not shape(data):
        raise MemoryFileDamaged(path)
    return data


def save_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def refresh_backup(path: Path) -> None:
    """After a final forget: the daily copy becomes the file as it is now,
    so it no longer holds what was forgotten."""
    path = Path(path)
    bak = path.with_name(path.name + BAK_SUFFIX)
    if not bak.exists():
        return
    if path.is_file():
        tmp = bak.with_name(bak.name + ".tmp")
        shutil.copy2(path, tmp)
        tmp.replace(bak)
    else:
        bak.unlink()
