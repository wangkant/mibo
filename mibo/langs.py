"""The languages mibo knows: their codes, their names, and which of the
prompts' two languages each reads (`content`). The interface's own words are in
i18n.py's catalogs.
"""
from __future__ import annotations

import contextlib
import os
import sys
import unicodedata

from .chatlangs import CODES

#: Each language in its own words, for a menu.
NAMES = {"en": "English", "zh": "简体中文", "zh-TW": "繁體中文", "ja": "日本語",
         "ko": "한국어", "es": "Español", "fr": "Français", "de": "Deutsch",
         "pt-BR": "Português (Brasil)", "ru": "Русский"}

#: What the character is called until someone names it.
DEFAULT_NAMES = {"en": "Nova", "zh": "小夏", "zh-TW": "小夏", "ja": "ノヴァ",
                 "ko": "노바", "es": "Nova", "fr": "Nova", "de": "Nova",
                 "pt-BR": "Nova", "ru": "Нова"}

_ALIASES = {"cn": "zh", "chinese": "zh", "中文": "zh", "english": "en",
            "japanese": "ja", "korean": "ko", "spanish": "es", "french": "fr",
            "german": "de", "portuguese": "pt-BR", "pt": "pt-BR", "russian": "ru"}
_LOWER = {code.lower(): code for code in CODES}
_TRADITIONAL = {"tw", "hk", "mo", "hant"}


def normalize(value: object) -> str:
    """The code for a spelling of a language (zh-CN, zh_TW, pt, Japanese), or ''."""
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw in _ALIASES:
        return _ALIASES[raw]
    primary, *rest = raw.split("-")
    if primary == "zh" and _TRADITIONAL & set(rest):
        return "zh-TW"
    return _LOWER.get(raw) or _ALIASES.get(primary) or _LOWER.get(primary, "")


def content(lang: str) -> str:
    """The language of the prompts and bundled data `lang` reads; a code outside
    the ten keeps its own name, since it names files someone put there."""
    if lang in ("zh", "zh-TW"):
        return "zh"
    return "en" if lang in CODES else lang


def utf8_console() -> None:
    """Every language's output must not crash a pipe on a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def interactive() -> bool:
    """A person at a terminal. On Windows NUL is a character device too, so
    `isatty` alone says yes to a script that gave no input."""
    stdin = sys.stdin
    if stdin is None or not stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt
    try:
        handle = msvcrt.get_osfhandle(stdin.fileno())
    except (AttributeError, OSError, ValueError):
        return True  # no real handle to ask: a stand-in that says it is one
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_uint32())))


def width(text: str) -> int:
    """Columns `text` takes in a terminal: CJK characters take two."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
