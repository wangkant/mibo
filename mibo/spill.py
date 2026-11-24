"""A tool result too long for its share of the model's window, kept whole in a file the model reads back in parts
(dsh's spill-policy and spill-local; Claude Code keeps a large tool output the same way).

The files are in <home>/runtime/spill: read_file reads them (shell/grants.py opens the folder to reads), and
nothing of the model's writes there, the home being the app's own. What is saved is the result as the model was
given it, so reading it back shows nothing a longer window would not have shown. A file older than KEPT_S is
removed when the next one is saved.
"""
from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

KEPT_S = 7 * 86400


def folder(home) -> Path:
    return Path(home) / "runtime" / "spill"


def save(home, text: str, name: str = "result") -> str:
    """`text` in a new file of the home's spill folder, named after the tool it came from; the file's path."""
    place = folder(home)
    place.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in place.iterdir():
        if now - old.stat().st_mtime > KEPT_S:
            old.unlink(missing_ok=True)
    path = place / f"{secrets.token_hex(6)}-{re.sub(r'[^A-Za-z0-9_-]', '_', name)[:40]}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)
