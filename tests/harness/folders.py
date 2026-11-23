"""A person's profile under tmp: Desktop, Documents, Downloads, Pictures, Music and Videos with the files a real
one holds (CJK names, a large binary, a git folder) and the keys a command must never show (.env, id_rsa, a
.pem). USERPROFILE and HOME point at it, and the app's own stand-in switch (MIBO_USER_DIRS) at its known
folders."""
from __future__ import annotations

import os
from pathlib import Path

from mibo.shell import grants

FOLDERS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
# Where a key lies, relative to the profile: each is one a command or a listing must hide.
KEYS = (".env", "Documents/project/.env", ".ssh/id_rsa", "Documents/certs/server.pem")
BIG = 1_500_000


class Profile:
    """`Profile(root, monkeypatch)` lays the profile out at `root` and points the environment at it."""

    def __init__(self, root: Path, monkeypatch) -> None:
        self.root = root
        for name in FOLDERS:
            (root / name).mkdir(parents=True, exist_ok=True)
        files = {
            "Desktop/待办.txt": "周五前交季度报告\n",
            "Desktop/屏幕截图 2026-11-19 200845.png": b"\x89PNG\r\n\x1a\n" + b"\x01" * 400,
            "Documents/简历.docx": b"PK\x03\x04" + b"\x00" * 200,
            "Documents/project/README.md": "# project\n",
            "Documents/project/.git/HEAD": "ref: refs/heads/main\n",
            "Downloads/发票.pdf": b"%PDF-1.4\n%\xe5\x8f\x91\xe7\xa5\xa8\n",
            "Downloads/setup.bin": b"\x00\x01" * (BIG // 2),
            "Pictures/猫.jpg": b"\xff\xd8\xff" + b"\x00" * 300,
            "Music/歌.mp3": b"ID3" + b"\x00" * 100,
            "Videos/clip.mp4": b"\x00\x00\x00\x18ftypmp42",
            **dict.fromkeys(KEYS, "API_KEY=sk-not-a-real-key\n"),
        }
        for name, body in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body) if isinstance(body, bytes) else path.write_text(body, encoding="utf-8")
        for name in ("USERPROFILE", "HOME"):
            monkeypatch.setenv(name, str(root))
        monkeypatch.setenv(grants.DIRS_ENV, os.pathsep.join(str(root / name.title()) for name in grants.DIRS))
