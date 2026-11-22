"""The fold (consolidate.py) in the person's own language: what they said about themselves is kept in their words
whichever of the ten chat languages they write in, the request teaches no other language, a harmless rewording of
their line is kept, and an answer that comes back in another language is asked for once more in theirs rather
than lost. A conversation goes through the page; the fold runs on the app's own trigger once enough lines of
theirs are in."""
from __future__ import annotations

import json
import re
import time

import pytest

from harness.model import say, text
from mibo import consolidate

CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
KANA = re.compile(r"[ぁ-ヿ]")


def _talk(app, turn, monkeypatch, lines: list[str], *answers: dict) -> list[dict]:
    """Each line said in the main chat and answered; the fold, due once all are in, answers with `answers` in
    turn. The facts the page's memory view shows after it."""
    monkeypatch.setattr(consolidate, "PERSON_FOLD_LINES", len(lines))
    app.model.script(*answers, purpose="fold")
    for n, line in enumerate(lines):
        assert turn(line, say(f"ok {n}")).status == 200
    kept = app.home / "runtime" / "person.json"
    for _ in range(500):
        # The fold has written its answer once person.json says when it last ran.
        if not app.model.left("fold") and kept.exists() and json.loads(kept.read_text(encoding="utf-8"))["fold"].get("at"):
            break
        time.sleep(0.02)
    assert not app.model.left("fold"), "the fold did not ask for every scripted answer"
    return app.get("/api/person").json()["facts"]


def _fold(facts: list[dict], plans: list | None = None, summary: str = "", topics: list | None = None) -> dict:
    return text(json.dumps({"facts": facts, "plans": plans or [], "summary": summary, "topics": topics or []},
                           ensure_ascii=False))


def _beside(request: dict, lines: list[str]) -> str:
    """A fold request's words without the person's own lines: its instructions and examples."""
    words = request["body"]["messages"][0]["content"]
    for line in lines:
        words = words.replace(line, "")
    return words


EN = ["I live in Boston with my partner Sam, and the winters are rough.",
      "I play badminton for two hours every weekend, it's my thing.",
      "Next Friday I'm flying to Denver for my sister's wedding."]
JA = ["大阪に住んでて、看護師をしてるよ。", "毎週末バドミントンを2時間やってる。", "今日は夜勤明けでちょっと眠い。"]
ES = ["Hoy tengo el día libre, pero mañana vuelvo al hospital.",
      "Trabajo de enfermera en Sevilla y también hago turnos de noche.",
      "Juego al bádminton dos horas cada fin de semana, me gusta muy mucho."]


def test_an_english_speaker_has_their_facts_kept_in_english_and_a_rewording_of_their_line_too(app, turn, monkeypatch):
    facts = _talk(app, turn, monkeypatch, EN, _fold([
        {"op": "add", "kind": "life", "slot": "home.city", "text": "Lives in Boston with partner Sam",
         "quote": "I live in Boston with my partner Sam", "from": ["L1"]},
        # Their words in other forms ("plays" for "play", "weekends" for "weekend").
        {"op": "add", "kind": "like", "slot": "badminton", "text": "Plays badminton on weekends",
         "quote": "I play badminton for two hours every weekend", "from": ["L3"]}],
        plans=[{"op": "add", "text": "Flying to Denver for sister's wedding", "when": "Next Friday",
                "quote": "I'm flying to Denver for my sister's wedding", "from": ["L5"]}]))
    assert sorted(f["text"] for f in facts) == ["Lives in Boston with partner Sam", "Plays badminton on weekends"]
    assert [p["text"] for p in app.get("/api/person").json()["plans"]] == ["Flying to Denver for sister's wedding"]
    # Nothing in the request teaches another language.
    assert not CJK.search(app.model.asked("fold")[0]["body"]["messages"][0]["content"])


def test_a_japanese_speaker_has_their_facts_kept_in_japanese_from_japanese_examples(app, turn, monkeypatch):
    facts = _talk(app, turn, monkeypatch, JA, _fold([
        {"op": "add", "kind": "life", "slot": "job", "text": "大阪に住んでいて、看護師をしている",
         "quote": "大阪に住んでて、看護師をしてる", "from": ["L1"]},
        {"op": "add", "kind": "like", "slot": "badminton", "text": "バドミントン、毎週末2時間やる",
         "quote": "毎週末バドミントンを2時間やってる", "from": ["L3"]}]))
    assert {f["text"] for f in facts} == {"大阪に住んでいて、看護師をしている", "バドミントン、毎週末2時間やる"}
    # The examples beside their lines are Japanese.
    assert KANA.search(_beside(app.model.asked("fold")[0], JA))


def test_a_spanish_speaker_has_their_facts_kept_in_spanish(app, turn, monkeypatch):
    facts = _talk(app, turn, monkeypatch, ES, _fold([
        {"op": "add", "kind": "life", "slot": "job", "text": "Trabaja de enfermera en Sevilla",
         "quote": "Trabajo de enfermera en Sevilla", "from": ["L3"]},
        {"op": "add", "kind": "like", "slot": "badminton", "text": "Bádminton, dos horas cada fin de semana",
         "quote": "Juego al bádminton dos horas cada fin de semana", "from": ["L5"]}]))
    assert sorted(f["text"] for f in facts) == ["Bádminton, dos horas cada fin de semana",
                                                  "Trabaja de enfermera en Sevilla"]
    assert not CJK.search(app.model.asked("fold")[0]["body"]["messages"][0]["content"])


# Two lines in each chat language, and the scripts its examples may and must be written in.
SCRIPTS = {"han": "[一-鿿]", "kana": "[ぁ-ヿ]", "hangul": "[가-힣]", "cyrillic": "[Ѐ-ӿ]"}
TEN = {
    "en": (["I just moved to Leeds for a new job.", "My cat is called Biscuit and she is so lazy."], (), ()),
    "zh": (["我刚搬到成都，换了新工作。", "我家猫叫年糕，特别懒。"], ("han",), ("han",)),
    "zh-TW": (["我剛搬到台中，換了新工作。", "我家的貓叫年糕，這隻貓真的很懶。"], ("han",), ("han",)),
    "ja": (["新しい仕事で福岡に引っ越したばかり。", "うちの猫はモチって名前で、すごく怠け者。"], ("kana",), ("kana", "han")),
    "ko": (["새 직장 때문에 대구로 이사했어요.", "우리 고양이 이름은 떡이고 엄청 게을러요."], ("hangul",), ("hangul",)),
    "es": (["Hoy me mudé a Valencia por un trabajo nuevo, estoy muy contenta.",
            "Mi gata se llama Mora y es muy perezosa, pero la quiero mucho."], (), ()),
    "fr": (["Je suis à Lille depuis hier pour un nouveau travail.", "Ma chatte s'appelle Pépite et elle est très paresseuse."], (), ()),
    "de": (["Ich bin wegen eines neuen Jobs nach Leipzig gezogen.", "Meine Katze heißt Keks und ist echt faul."], (), ()),
    "pt-BR": (["Eu me mudei pra Curitiba por causa de um trabalho novo.", "Minha gata se chama Paçoca e é muito preguiçosa."], (), ()),
    "ru": (["Я переехала в Казань ради новой работы.", "Мою кошку зовут Пышка, она очень ленивая."], ("cyrillic",), ("cyrillic",)),
}


@pytest.mark.parametrize("code", list(TEN))
def test_the_folds_examples_are_in_the_language_each_person_writes(app, turn, monkeypatch, code):
    lines, must, may = TEN[code]
    _talk(app, turn, monkeypatch, lines, _fold([]))
    beside = _beside(app.model.asked("fold")[0], lines)
    for script, letters in SCRIPTS.items():
        if script in must:
            assert re.search(letters, beside), f"{code}: the examples are in {script}"
        elif script not in may:
            assert not re.search(letters, beside), f"{code}: no example in {script}"


ZH_FOR_EN = [{"op": "add", "kind": "life", "slot": "home.city", "text": "和伴侣Sam住在波士顿",
              "quote": "I live in Boston with my partner Sam", "from": ["L1"]}]
EN_AGAIN = [{"op": "add", "kind": "life", "slot": "home.city", "text": "Lives in Boston with partner Sam",
             "quote": "I live in Boston with my partner Sam", "from": ["L1"]}]


def test_an_answer_in_another_language_is_asked_for_again_once_in_theirs_and_kept(app, turn, monkeypatch):
    facts = _talk(app, turn, monkeypatch, EN, _fold(ZH_FOR_EN, summary="他们聊了波士顿的冬天。"),
                  _fold(EN_AGAIN, summary="They talked about winters in Boston. Sam is with them."))
    assert [f["text"] for f in facts] == ["Lives in Boston with partner Sam"]
    kept = json.loads((app.home / "runtime" / "person.json").read_text(encoding="utf-8"))
    assert kept["talk"]["summary"] == "They talked about winters in Boston. Sam is with them."
    again = app.model.asked("fold")[1]["body"]["messages"]
    # The same conversation, its first answer in it, then the ask.
    assert [m["role"] for m in again] == ["user", "assistant", "user"] and "波士顿" in again[1]["content"]


def test_an_answer_still_in_another_language_after_one_more_ask_keeps_nothing_and_asks_no_more(app, turn, monkeypatch):
    facts = _talk(app, turn, monkeypatch, EN, _fold(ZH_FOR_EN), _fold(ZH_FOR_EN))
    assert facts == [] and len(app.model.asked("fold")) == 2
