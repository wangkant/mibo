"""The pictures the character sent and what the person attached to a message: checked, stored by content hash in
the chats' own folders, served only while a message shows them, and removed once none does."""
from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from .pagechat import TITLE_MAX, stored_names
from .setup_wizard import own_avatar_kind

# A picture the character sent, stored by its content hash; nothing else is served.
PICTURE_NAME = re.compile(r"[0-9a-f]{40}\.(png|jpg|gif|webp)")
# A file the person attached, its text stored by its content hash.
FILE_NAME = re.compile(r"[0-9a-f]{40}\.txt")
PICTURE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
MAX_PICTURE = 8 * 1024 * 1024
# What the person attaches to a message (chat.js): at most ATTACH_MAX things. A picture
# (png, jpg, webp, gif) of at most ATTACH_PICTURE bytes, the page having made a larger one
# smaller; a text file of at most ATTACH_FILE bytes, read here, of the kinds below, whose text
# goes to the character cut to ATTACH_TEXT characters.
ATTACH_MAX = 4
ATTACH_PICTURE = 1_000_000
ATTACH_FILE = 512 * 1024
ATTACH_TEXT = 10_000
ATTACH_TEXT_KINDS = frozenset(["txt", "text", "md", "markdown", "rst", "csv", "tsv", "json", "jsonl", "yaml", "yml",
                               "toml", "ini", "cfg", "conf", "log", "xml", "html", "htm", "css", "scss", "js", "mjs",
                               "cjs", "ts", "tsx", "jsx", "vue", "py", "ipynb", "java", "kt", "kts", "scala", "go",
                               "rs", "c", "h", "cc", "cpp", "hpp", "cs", "m", "mm", "swift", "rb", "php", "pl", "lua",
                               "r", "sql", "sh", "bash", "zsh", "ps1", "bat", "cmd", "tex", "bib", "srt", "vtt",
                               "diff", "patch"])
# Bytes a message's attachments add to its request: pictures go as base64.
ATTACH_ROOM = ATTACH_MAX * ATTACH_PICTURE * 4 // 3 + 4096


def picture_kind(data: bytes) -> str:
    """The file extension of an image the page can show, or "": a character's own picture's kinds and GIF."""
    return "gif" if data[:6] in (b"GIF87a", b"GIF89a") else own_avatar_kind(data)


def file_text(data: bytes) -> str | None:
    """A text file's words: UTF-8 (or UTF-16 with its mark, or GB18030 as Windows in
    Chinese saves); None for what is not text."""
    encodings = ("utf-16",) if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return None if "\x00" in text else text
    return None


def _hashed(data: bytes, kind: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()[:40]}.{kind}"


def _label(value) -> str:
    return " ".join(str(value or "").split())[:TITLE_MAX]


def _read_one(item) -> tuple[dict, bytes]:
    """One attached thing checked: its record for the message and what is stored for it."""
    # A page from the app's browser, by its address: the character reads it itself.
    if isinstance(item, dict) and item.get("kind") == "page":
        url = str(item.get("url") or "").strip()
        if urlsplit(url).scheme not in ("http", "https") or len(url) > 2000:
            raise ValueError("generic")
        return {"kind": "page", "url": url, "title": _label(item.get("title"))}, b""
    try:
        data = base64.b64decode(str(item.get("data") or ""), validate=True)
    except (AttributeError, binascii.Error, ValueError):
        raise ValueError("generic") from None
    if item.get("kind") == "picture":
        kind = picture_kind(data)
        if not kind:
            raise ValueError("picture_type")
        if len(data) > ATTACH_PICTURE:
            raise ValueError("picture_too_large")
        return {"kind": "picture", "name": _hashed(data, kind), "size": len(data)}, data
    label = _label(item.get("name"))
    if Path(label).suffix.lower()[1:] not in ATTACH_TEXT_KINDS:
        raise ValueError("file_type")
    if len(data) > ATTACH_FILE:
        raise ValueError("file_too_large")
    words = file_text(data)
    if words is None:
        raise ValueError("file_unreadable")
    stored = words.encode("utf-8")
    return ({"kind": "file", "name": _hashed(stored, "txt"), "file": label, "size": len(data),
             "clipped": len(words) > ATTACH_TEXT}, stored)


def read_attachments(raw) -> list[tuple[dict, bytes]]:
    """The pictures and files sent with a message, checked: each one's record
    for the message and what is stored for it. A file is kept as its text."""
    if not isinstance(raw, list) or len(raw) > ATTACH_MAX:
        raise ValueError("attach_too_many")
    return [_read_one(item) for item in raw]


def _own_folder(folder: Path) -> bool:
    """A chat's pictures or files folder exists and is not a link to another place."""
    try:
        return folder.is_dir() and folder.resolve() == folder.parent.resolve() / folder.name
    except OSError:
        return False


class ChatMedia:
    """The chats' pictures and attached files under `desktop`; `messages` gives every message the chats hold,
    which decides what is served and what is kept."""

    def __init__(self, desktop: Path, messages: Callable[[], Iterable[dict]]) -> None:
        self.pictures = desktop / "chat-pictures"
        # The text files the person attached.
        self.files = desktop / "chat-files"
        self._messages = messages

    def _shown(self) -> set:
        return set().union(*map(stored_names, self._messages()))

    def keep_picture(self, encoded) -> str:
        """Store a picture the character sent; its file name, or "" when it is not one."""
        text = str(encoded or "")
        if not text or len(text) > MAX_PICTURE * 4 // 3 + 4:
            return ""
        try:
            data = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return ""
        kind = picture_kind(data)
        return self._store(self.pictures, _hashed(data, kind), data) if kind else ""

    @staticmethod
    def _store(folder: Path, name: str, data: bytes) -> str:
        """Keep `data` as `name` in a chat's own folder; the name, or "" when it cannot be kept there."""
        path = folder / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not _own_folder(folder) or path.is_symlink():
                return ""
            if not path.is_file():
                # Exclusive: never through a link or file that appeared since the check.
                with open(path, "xb") as file:
                    file.write(data)
        except FileExistsError:
            return name if path.is_file() and not path.is_symlink() else ""
        except OSError:
            return ""
        return name

    def picture(self, name: str) -> Path | None:
        """A picture a message in one of the chats shows; None for any other name, link or missing file."""
        return self._served(self.pictures, PICTURE_NAME, name)

    def file(self, name: str) -> Path | None:
        """A text file the person attached to a message in one of the chats, as `picture`."""
        return self._served(self.files, FILE_NAME, name)

    def _served(self, folder: Path, pattern: re.Pattern, name: str) -> Path | None:
        if not pattern.fullmatch(str(name or "")) or not any(name in stored_names(m) for m in self._messages()):
            return None
        path = folder / name
        try:
            # Resolving follows links and junctions: one leading out is refused.
            if not path.is_file() or not _own_folder(folder) or path.resolve() != folder.resolve() / name:
                return None
        except OSError:
            return None
        return path

    def prune(self, names: set | None = None) -> None:
        """Pictures and attached files of `names` that no message shows any more are removed with the messages;
        with no names (a start), every one stored that no chat shows, a 无痕对话's of before the start among them."""
        kept = self._shown()
        for folder, pattern in ((self.pictures, PICTURE_NAME), (self.files, FILE_NAME)):
            if not _own_folder(folder):
                continue
            try:
                stored = list(folder.iterdir()) if names is None else [folder / name for name in names]
            except OSError:
                continue
            for path in stored:
                if pattern.fullmatch(path.name) and path.name not in kept and not path.is_symlink():
                    with contextlib.suppress(OSError):
                        path.unlink()

    def keep(self, taken: list[tuple[dict, bytes]]) -> list[dict]:
        """Store what was attached beside the character's pictures; the records for the message."""
        for record, data in taken:
            if record["kind"] == "page":
                continue
            folder = self.pictures if record["kind"] == "picture" else self.files
            if not self._store(folder, record["name"], data):
                raise ValueError("generic")
        return [record for record, _ in taken]

    def parts(self, records: list[dict]) -> list[dict]:
        """What was attached, as the character reads it (messages._read_message): a picture inline, a
        file by its name and its text cut to ATTACH_TEXT, which it frames as material, not words to obey."""
        return [self._part(record) for record in records]

    def _part(self, record: dict) -> dict:
        if record["kind"] == "picture":
            data = (self.pictures / record["name"]).read_bytes()
            return {"type": "picture", "b64": base64.b64encode(data).decode()}
        if record["kind"] == "page":
            return {"type": "text", "text": f"\n[attached page from their in-app browser: "
                                            f"“{record['title']}” {record['url']}]"}
        words = (self.files / record["name"]).read_text(encoding="utf-8")
        if len(words) > ATTACH_TEXT:
            words = f"{words[:ATTACH_TEXT]}\n[cut here: the last {len(words) - ATTACH_TEXT} characters were not sent]"
        return {"type": "file", "name": record["file"], "text": words}
