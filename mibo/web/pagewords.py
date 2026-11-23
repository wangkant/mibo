"""The words of a page as a look prints them and the model reads them: one way to space, fold, clip and quote
text, the patterns that make a field secret, the field types set by value, and the ids of frames from another site.
Shared by the page modules (pageops and the ones beside it) and by the window reader that prints in the same
grammar (desk/uia.py)."""
from __future__ import annotations

import json
import re
import time
from typing import Any

# The roles of controls the model acts on.
CONTROLS = {"button", "link", "textbox", "searchbox", "combobox", "listbox", "option", "checkbox", "radio", "switch",
            "slider", "spinbutton", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "treeitem"}
# Input types set by value, as Playwright fills them (injectedScript.ts fill), and the form each takes.
SET_BY_VALUE = {"date": "YYYY-MM-DD", "time": "HH:MM, 24-hour", "datetime-local": "YYYY-MM-DDTHH:MM",
                "month": "YYYY-MM", "week": "YYYY-Www", "color": "#rrggbb", "range": "a number"}
CONTEXT_LOSS = re.compile(r"Execution context was destroyed|Cannot find context|Cannot find default execution "
                          r"context|Inspected target navigated|Target closed|No frame")
CDP_TIMEOUT_MS = 15_000
SURROGATE = re.compile("[\ud800-\udfff]")
# A field's own words that make it secret, whatever its type says: card and one-time-code words as Chromium's
# autofill heuristics name them (card #, ccnum, csc, a 6-digit code, 2FA, PIN), and their Chinese.
SECRET_LABEL = re.compile(r"password|passcode|passwd|\b(?:card|cc|acct)[\s._-]?(?:number|num|no\b|#)|cvv|cvc|cvn|csc|"
                          r"security\s*code|one[-\s]?time|\botp\b|\botc\b|totp|\b2fa\b|two[-\s]?factor|\bpin\b|"
                          r"verification\s*code|sms\s*code|\benter\s+(?:the\s+)?code\b|\d[-\s]?digit\s+code|"
                          r"密码|口令|验证码|校验码|动态码|卡号|银行卡|信用卡|安全码|支付密码",
                          re.I)
SECRET_AUTOCOMPLETE = re.compile(r"^(?:cc-.*|one-time-code|current-password|new-password)$", re.I)
SECRET_SELECTOR = ("input[type=password],input[autocomplete^=cc-],input[autocomplete=one-time-code],"
                   "input[autocomplete=current-password],input[autocomplete=new-password],textarea[autocomplete^=cc-],"
                   "textarea[autocomplete=one-time-code]")
# The ids in a frame from another site: the frame's number in the page times this, plus the id in its own process.
FRAME_IDS = 10_000_000


def norm(s: Any) -> str:
    if isinstance(s, bool):
        s = "true" if s else "false"
    return re.sub(r"[ \t\n\r\f﻿]+", " ", "" if s is None else str(s)).strip()


def fold(s: str) -> str:
    return re.sub(r"[\s﻿]+", " ", s).lower()


def clip(s: str, n: int) -> str:
    return f"{s[:n]}…" if len(s) > n else s


def quote(s: str) -> str:
    return SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", json.dumps(s, ensure_ascii=False))


def well_formed(s: str) -> str:
    return SURROGATE.sub("�", s)


def is_context_loss(e: BaseException) -> bool:
    return bool(CONTEXT_LOSS.search(str(e)))


def now() -> float:
    return time.monotonic() * 1000
