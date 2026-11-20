"""The chat log (chatlog.py): each chat's lines on disk for MEMORY_LOG_DAYS,
searchable, cited by notes, and reached by every forget.

Run from the repo root:

    python -m pytest tests/test_memory_log.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from mibo import chatlog

from helpers import check

ROOM = "telegram:g"
OTHER = "telegram:h"
DAY = 86400.0


def row(seq: int, text: str, uid: str = "7", name: str = "Ann", t: float = 0.0) -> dict:
    return {"seq": seq, "t": t or time.time(), "user_id": uid, "name": name, "text": text}


def log_of(tmp: Path, **kw) -> chatlog.ChatLog:
    return chatlog.ChatLog(tmp / "log", **kw)


# ---- the store ---------------------------------------------------------------

def test_lines_are_appended_once_and_a_grown_line_is_read_at_its_newest(tmp: Path) -> None:
    log = log_of(tmp)
    check("two new lines taken", log.take(ROOM, [row(1, "hi"), row(2, "tea?")]) == 2)
    check("nothing new: nothing taken", log.take(ROOM, [row(1, "hi"), row(2, "tea?")]) == 0)
    check("the newest grew: taken again", log.take(ROOM, [row(2, "tea? green")]) == 1)
    check("read keeps the grown text once",
          [r["text"] for r in log.read(ROOM)] == ["hi", "tea? green"], repr(log.read(ROOM)))
    again = log_of(tmp)
    check("a new process knows where it stopped", again.take(ROOM, [row(2, "tea? green")]) == 0
          and again.last_seq(ROOM) == 2)


def test_a_chat_key_never_names_a_path(tmp: Path) -> None:
    log = log_of(tmp)
    for key in ("../../evil", "a/b\\c", "C:\\x", "\x00", "telegram:../../.."):
        log.take(key, [row(1, "x")])
    files = list((tmp / "log").iterdir())
    check("every file sits in the log folder, named by a hash",
          all(f.parent == tmp / "log" and len(f.stem) == 32 for f in files
              if f.suffix == ".jsonl"), repr(files))
    check("nothing outside it", not (tmp / "evil").exists() and not (tmp.parent / "evil").exists())


def test_a_write_cut_short_is_skipped_and_the_next_one_lands_whole(tmp: Path) -> None:
    log = log_of(tmp)
    log.take(ROOM, [row(1, "hi")])
    with open(log.path(ROOM), "ab") as fh:
        fh.write(b'{"seq": 2, "t": 1, "te')
    fresh = log_of(tmp)
    check("the fragment is skipped", [r["seq"] for r in fresh.read(ROOM)] == [1])
    fresh.take(ROOM, [row(2, "again")])
    check("the next line is read whole", [r["text"] for r in fresh.read(ROOM)] == ["hi", "again"])


def test_old_lines_and_lines_past_the_cap_are_pruned(tmp: Path) -> None:
    now = time.time()
    log = log_of(tmp, days=30, max_lines=3)
    log._append(ROOM, [row(1, "old", t=now - 31 * DAY)] + [
        row(i, f"line {i}", t=now - 60 + i) for i in range(2, 7)])
    log._append(OTHER, [row(1, "very old", t=now - 40 * DAY)])
    check("pruned: the old line and two past the cap", log.prune(now) == 3 + 1)
    check("the newest three stay", [r["seq"] for r in log.read(ROOM)] == [4, 5, 6])
    check("a chat with nothing left loses its file", not log.path(OTHER).exists())
    check("a line older than the days is not taken at all",
          log.take(OTHER, [row(2, "stale", t=now - 31 * DAY)]) == 1
          and not log.read(OTHER))


def test_search_by_words_by_speaker_and_by_time(tmp: Path) -> None:
    now = time.time()
    log = log_of(tmp)
    log.take(ROOM, [row(1, "I adopted a cat named Miso", "7", "Ann", now - 5 * DAY),
                    row(2, "nice weather today", "9", "Bo", now - 4 * DAY),
                    row(3, "Miso knocked over my plant", "7", "Ann", now - DAY),
                    row(4, "我下周去杭州出差", "9", "Bo", now - 3600)])
    check("words, best first",
          [r["seq"] for r in log.search(ROOM, "Miso the cat")][:1] == [1])
    check("Chinese words", [r["seq"] for r in log.search(ROOM, "杭州")] == [4])
    check("by speaker", [r["seq"] for r in log.search(ROOM, speakers=["9"])] == [4, 2])
    check("by time", [r["seq"] for r in log.search(ROOM, since=now - 2 * DAY)] == [4, 3])
    check("lines asked to skip stay out",
          [r["seq"] for r in log.search(ROOM, "Miso", skip=[1])] == [3])
    check("words that make no token find nothing", log.search(ROOM, "a") == [])
    check("bounded", len(log.search(ROOM, limit=999)) <= chatlog.SEARCH_MAX)


def test_a_forgotten_newest_line_is_not_logged_again(tmp: Path) -> None:
    log = log_of(tmp)
    log.take(ROOM, [row(1, "hi"), row(2, "my secret")])
    check("one line forgotten", log.forget(ROOM, lambda r: "secret" in r["text"]) == 1)
    check("gone from reads", [r["text"] for r in log.read(ROOM)] == ["hi"])
    check("not in the file", "secret" not in log.path(ROOM).read_text(encoding="utf-8"))
    again = log_of(tmp)
    check("a new process does not log it again from the window",
          again.take(ROOM, [row(1, "hi"), row(2, "my secret")]) == 0
          and [r["text"] for r in again.read(ROOM)] == ["hi"])


def test_refs_are_read_defensively() -> None:
    check("ints only, positive, unique, bounded",
          chatlog.refs_of({"refs": [3, "4", -1, True, 3, 5, 6, 7, 8, 9, 10]}) == [3, 5, 6, 7, 8, 9])
    check("absent or malformed is none", chatlog.refs_of({}) == [] == chatlog.refs_of(
        {"refs": "1,2"}) == chatlog.refs_of(None))


# ---- the agent's log ---------------------------------------------------------

def test_a_backup_never_holds_the_log(tmp: Path) -> None:
    from mibo.panels import desk
    home = tmp / "home"
    (home / "runtime" / "log").mkdir(parents=True)
    (home / "runtime" / "log" / "x.jsonl").write_text(json.dumps(row(1, "hi")), encoding="utf-8")
    (home / "runtime" / "memory.json").write_text("{}", encoding="utf-8")
    members = [name for _p, name in desk.members(home)]
    check("memory is in the backup, the log is not",
          "runtime/memory.json" in members and not any("log/" in m for m in members),
          repr(members))
