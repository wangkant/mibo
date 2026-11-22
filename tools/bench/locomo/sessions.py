"""A LoCoMo conversation's sessions and their dates, shared by replay.py and score.py."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

#: The app's chat record keeps this many days (MEMORY_LOG_DAYS's default).
RECORD_DAYS = 30


def keys(conv: dict) -> list[str]:
    return sorted((k for k in conv if k.startswith("session_") and not k.endswith("date_time") and conv[k]),
                  key=lambda k: int(k.split("_")[1]))


def when(conv: dict, key: str) -> datetime:
    return datetime.strptime(conv[key + "_date_time"], "%I:%M %p on %d %B, %Y")


def asked_on(conv: dict) -> datetime:
    """When the questions are asked: 10:00 the day after the last session."""
    return (when(conv, keys(conv)[-1]) + timedelta(days=1)).replace(hour=10, minute=0)


def old(qa: dict, conv: dict) -> bool:
    """All of the question's evidence from sessions more than RECORD_DAYS days before it is asked."""
    days = {int(k.split("_")[1]): when(conv, k) for k in keys(conv)}
    found = {int(m.group(1)) for e in qa.get("evidence") or [] for m in [re.match(r"D(\d+):", e)] if m}
    found &= set(days)
    return bool(found) and all(asked_on(conv) - days[s] > timedelta(days=RECORD_DAYS) for s in found)
