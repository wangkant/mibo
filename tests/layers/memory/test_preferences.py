"""What the person likes and how they want to be treated, as the store keeps it (person.py) and the fold revises
it (consolidate.py): a preference seen once waits unseen until it comes up again in another chat, the fold rewrites
a kept one in place and folds another into it, never changes or ends one the person wrote, and each preference
group of Settings › 记忆 (偏好: likes, form and manner; 不喜欢) keeps at most PREFERENCES_MAX, the fold's least used
going first. A replaced manner line leaves what every reply reads too."""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness.model import say, text

from mibo import consolidate, memstate, person, profile

NOW = 1_764_000_000.0
HOUR = 3600.0


def _store(folder: Path) -> person.Person:
    store = person.Person(folder / person.FILE)
    store.load()
    return store


def _active(store: person.Person) -> list[str]:
    return [f["text"] for f in store.facts()]


def test_a_preference_seen_once_waits_unseen_until_another_chat_says_it_again(tmp_path):
    store = _store(tmp_path)
    store.put_fact("like", "", "睡前看做饭视频", NOW, conv="c1", once=True)
    # The same chat an hour later is still the one sighting.
    store.put_fact("like", "", "睡前看做饭视频解压", NOW + HOUR, conv="c1", once=True)
    assert _active(store) == [] and [f["text"] for f in store.hints()] == ["睡前看做饭视频解压"]
    row, _ = store.put_fact("like", "", "睡前看做饭视频解压", NOW + 2 * HOUR, conv="c2", once=True)
    assert _active(store) == ["睡前看做饭视频解压"] and store.hints() == []
    # Kept since it was first seen.
    assert row["born"] == NOW


def test_a_preference_said_outright_is_kept_at_once_and_a_hint_not_seen_again_lapses(tmp_path):
    store = _store(tmp_path)
    store.put_fact("like", "", "后摇，写代码时听", NOW, conv="c1")
    store.put_fact("like", "", "看了一集繁花", NOW, conv="c1", once=True)
    assert _active(store) == ["后摇，写代码时听"]
    assert store.tidy(NOW + person.SEEN_DAYS * 86400) and store.hints() == []


def test_words_a_kept_preference_already_says_add_nothing_beside_it(tmp_path):
    store = _store(tmp_path)
    store.put_fact("like", "", "羽毛球，每周末打两个小时", NOW, conv="c1")
    store.put_fact("like", "", "每周末打两个小时羽毛球", NOW + HOUR, conv="c2")
    assert _active(store) == ["羽毛球，每周末打两个小时"]


def test_a_fold_never_ends_a_preference_the_person_wrote(tmp_path):
    store = _store(tmp_path)
    store.put_fact("like", "food", "辣的川菜，越辣越好", NOW, src="page")
    store.put_fact("like", "food", "清淡的粥", NOW + HOUR, conv="c1")
    assert _active(store) == ["辣的川菜，越辣越好", "清淡的粥"]


# Eighteen things a fold kept, each in other words, taken in turn as a like and a form.
FOLDED = ("羽毛球", "攀岩", "纪录片", "美式", "播客", "解谜游戏", "川菜", "跑步", "科幻小说", "胶片", "多肉", "博物馆",
          "赛车", "乌龙茶", "骑行", "日剧", "吉他", "围棋")


def test_each_preference_group_keeps_its_bound_and_the_folds_least_used_give_way(tmp_path):
    store = _store(tmp_path)
    own = [store.put_fact("manner", "", words, NOW, src="page")[0] for words in ("叫我小林", "先给结论", "晚上别发消息")]
    folded = [store.put_fact("like" if n % 2 else "form", "", words, NOW + n * HOUR, conv="c1")[0]
              for n, words in enumerate(FOLDED)]
    dislikes = [store.put_fact("dislike", "", f"讨厌{words}", NOW, conv="c1")[0]
                for words in ("香菜", "广告", "饭圈", "鬼片", "堵车")]
    # Likes, forms and manners are one group: 21 of them, so the oldest the fold kept gives way.
    assert len([f for f in store.facts() if f["kind"] in ("like", "form", "manner")]) == person.PREFERENCES_MAX
    assert folded[0]["status"] == "past" and folded[0]["why"] == "crowded"
    assert all(f["status"] == "active" for f in own + folded[1:] + dislikes)


# ---- the fold, through the page ------------------------------------------------------------------------------

def _fold(facts: list[dict]) -> dict:
    return text(json.dumps({"facts": facts, "plans": [], "summary": "", "topics": []}, ensure_ascii=False))


class _Ahead:
    """The time the fold reads, a call gap past the wall clock's: the day's call budget lets a second fold go."""

    @staticmethod
    def time() -> float:
        return time.time() + memstate.MIN_GAP_S


def _talk(app, turn, monkeypatch, lines: list[str], answer: dict) -> list[dict]:
    """Each line said in the main chat and answered; the fold, due once all are in, answers `answer`. The facts
    the page's memory view shows after it."""
    kept = app.home / "runtime" / "person.json"

    def folded_at() -> float:
        return json.loads(kept.read_text(encoding="utf-8"))["fold"].get("at", 0.0) if kept.exists() else 0.0
    before = folded_at()
    monkeypatch.setattr(consolidate, "PERSON_FOLD_LINES", len(lines))
    app.model.script(answer, purpose="fold")
    for n, line in enumerate(lines):
        assert turn(line, say(f"ok {n}")).status == 200
    for _ in range(500):
        if not app.model.left("fold") and folded_at() != before:
            break
        time.sleep(0.02)
    assert not app.model.left("fold"), "the fold did not ask for its scripted answer"
    return app.get("/api/person").json()["facts"]


def test_an_update_sharpens_a_kept_preference_and_folds_another_into_it(app, turn, monkeypatch):
    _talk(app, turn, monkeypatch, ["I like music a lot.", "Britpop is my favourite."], _fold([
        {"op": "add", "kind": "like", "text": "Music", "quote": "I like music", "from": ["L1"]},
        {"op": "add", "kind": "like", "text": "Britpop", "quote": "Britpop is my favourite", "from": ["L3"]}]))
    monkeypatch.setattr(consolidate, "time", _Ahead)
    facts = _talk(app, turn, monkeypatch, ["Mostly 90s Britpop, Blur and Pulp, when I run."], _fold([
        {"op": "update", "id": "F1", "text": "Music: 90s Britpop, Blur and Pulp, when running",
         "quote": "Mostly 90s Britpop, Blur and Pulp, when I run", "from": ["L1"], "merges": ["F2"]}]))
    assert [f["text"] for f in facts] == ["Music: 90s Britpop, Blur and Pulp, when running"]
    assert sorted((r["text"], r["why"]) for r in app.get("/api/person").json()["trash"]) == [
        ("Britpop", "replaced"), ("Music", "replaced")]


def test_the_fold_cannot_change_or_end_what_the_person_wrote(app, turn, monkeypatch):
    assert app.post("/api/person/add", {"text": "我喜欢吃辣的川菜"}).status_code == 200
    facts = _talk(app, turn, monkeypatch, ["最近胃不太舒服，辣的先不吃了。"], _fold([
        {"op": "update", "id": "F1", "text": "川菜，胃不舒服时先不吃辣", "quote": "辣的先不吃了", "from": ["L1"]},
        {"op": "end", "id": "F1", "from": ["L1"]}]))
    assert [f["text"] for f in facts] == ["喜欢吃辣的川菜"]
    # The fold is told which are theirs.
    assert '"own": true' in app.model.asked("fold")[0]["body"]["messages"][0]["content"]


def test_a_replaced_manner_line_no_longer_reaches_the_replies(app, turn, monkeypatch):
    _talk(app, turn, monkeypatch, ["I prefer bullet-point answers."], _fold([
        {"op": "add", "kind": "manner", "text": "Prefers bullet-point answers",
         "quote": "I prefer bullet-point answers", "from": ["L1"]}]))
    assert profile.manner_lines(app.home / "runtime") == ["Prefers bullet-point answers"]
    monkeypatch.setattr(consolidate, "time", _Ahead)
    _talk(app, turn, monkeypatch, ["Plain paragraphs please, no bullet points."], _fold([
        {"op": "update", "id": "F1", "text": "Plain paragraphs, not bullet points",
         "quote": "Plain paragraphs please", "from": ["L1"]}]))
    assert profile.manner_lines(app.home / "runtime") == ["Plain paragraphs, not bullet points"]
