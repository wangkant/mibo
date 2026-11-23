"""The fold (consolidate.py) in the person's own language: what they said about themselves is kept in their words
whichever of the ten chat languages they write in, the language is the one most of their letters are in (a kaomoji,
a word or a title in another script, or a pasted error message does not change it), a language outside the ten is
taken for none of them, the request teaches no other language, a harmless rewording of their line is kept and a
fact with a word they never said is not, and an answer that comes back in another language is asked for once more
in theirs, within the day's calls, without losing a true fact. A conversation goes through the page; the fold runs
on the app's own trigger once enough lines of theirs are in."""
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


def _examples_of(request: dict, lines: list[str]) -> set[str]:
    """The chat languages whose examples the fold's request carries beside the person's lines."""
    beside = _beside(request, lines)
    return {code for code, ex in consolidate.EXAMPLES.items() if ex[1] in beside or ex[4] in beside}


# Two lines in each chat language.
TEN = {
    "en": ["I just moved to Leeds for a new job.", "My cat is called Biscuit and she is so lazy."],
    "zh": ["我刚搬到成都，换了新工作。", "我家猫叫年糕，特别懒。"],
    "zh-TW": ["我剛搬到台中，換了新工作。", "我家的貓叫年糕，這隻貓真的很懶。"],
    "ja": ["新しい仕事で福岡に引っ越したばかり。", "うちの猫はモチって名前で、すごく怠け者。"],
    "ko": ["새 직장 때문에 대구로 이사했어요.", "우리 고양이 이름은 떡이고 엄청 게을러요."],
    "es": ["Hoy me mudé a Valencia por un trabajo nuevo, estoy muy contenta.",
           "Mi gata se llama Mora y es muy perezosa, pero la quiero mucho."],
    "fr": ["Je suis à Lille depuis hier pour un nouveau travail.", "Ma chatte s'appelle Pépite et elle est très paresseuse."],
    "de": ["Ich bin wegen eines neuen Jobs nach Leipzig gezogen.", "Meine Katze heißt Keks und ist echt faul."],
    "pt-BR": ["Eu me mudei pra Curitiba por causa de um trabalho novo.", "Minha gata se chama Paçoca e é muito preguiçosa."],
    "ru": ["Я переехала в Казань ради новой работы.", "Мою кошку зовут Пышка, она очень ленивая."],
}


@pytest.mark.parametrize("code", list(TEN))
def test_the_folds_examples_are_in_the_language_each_person_writes_and_in_no_other(app, turn, monkeypatch, code):
    _talk(app, turn, monkeypatch, TEN[code], _fold([]))
    assert _examples_of(app.model.asked("fold")[0], TEN[code]) == {code}


# Lines whose language one sign or word in another script, a pasted message or a close neighbour could mislead,
# and the examples their fold must carry.
MIXED = {
    "a kaomoji from an English speaker": (["I just moved to Leeds for a new job.", r"Work is fine I guess ¯\_(ツ)_/¯",
                                           "My cat is called Biscuit and she is so lazy."], "en"),
    "a kaomoji from a Chinese speaker": (["我刚搬到成都，换了新工作。", r"工作还行吧 ¯\_(ツ)_/¯", "我家猫叫年糕，特别懒。"], "zh"),
    "one Chinese word in English": (["We had 饺子 for dinner, my mom made them.", "I just moved to Leeds for a new job."], "en"),
    "an anime title in English": (["I love the anime 鬼滅の刃, I watched it twice.",
                                   "My cat is called Biscuit and she is so lazy."], "en"),
    "an English error pasted by a Chinese speaker": (
        ["帮我看看这个报错是怎么回事", "TypeError: Cannot read properties of undefined (reading 'map') at App.render (App.js:12:5)",
         "我刚学React两个月"], "zh"),
    "Japanese mostly in kanji": (["東京都内の総合病院で看護師として勤務中。", "来月大阪本社へ転勤予定です。"], "ja"),
    "Portuguese beside Spanish": (["Hoje eu trabalho de casa, mas amanhã vou ao escritório.",
                                   "Minha irmã mora em Lisboa com o marido."], "pt-BR"),
    "Traditional beside Simplified": (["我剛搬到台中，換了新工作。", "週末都在練習鋼琴，老師說我進步很多。"], "zh-TW"),
}


@pytest.mark.parametrize("case", list(MIXED))
def test_the_language_is_the_one_most_of_their_letters_are_in(app, turn, monkeypatch, case):
    lines, code = MIXED[case]
    _talk(app, turn, monkeypatch, lines, _fold([]))
    assert _examples_of(app.model.asked("fold")[0], lines) == {code}


# A language outside the ten: two lines of it, a fact in it and the words of the first line it quotes.
OUTSIDE = {
    "Ukrainian": (["Я працюю медсестрою в Києві.", "Мою кішку звати Пушинка, вона дуже лінива."],
                  "Працюю медсестрою в Києві", "Я працюю медсестрою в Києві"),
    "Serbian": (["Радим као медицинска сестра у Београду.", "Моја мачка се зове Пахуља и јако је лења."],
                "Ради као медицинска сестра у Београду", "Радим као медицинска сестра у Београду"),
    "Bulgarian": (["Работя като медицинска сестра в София.", "Котката ми се казва Пухчо и е много мързелива."],
                  "Работи като медицинска сестра в София", "Работя като медицинска сестра в София"),
    "Romanian": (["Lucrez ca asistentă medicală în București.", "Pisica mea se numește Pufi și îmi place foarte mult de ea."],
                 "Lucrează ca asistentă medicală în București", "Lucrez ca asistentă medicală în București"),
    "Italian": (["Lavoro come infermiera a Milano, faccio anche i turni di notte.",
                 "Il mio gatto si chiama Biscotto ed è molto pigro."],
                "Lavora come infermiera a Milano", "Lavoro come infermiera a Milano"),
    "Vietnamese": (["Tôi làm y tá ở Hà Nội.", "Con mèo của tôi tên là Bánh Quy và nó rất lười."],
                   "Làm y tá ở Hà Nội", "Tôi làm y tá ở Hà Nội"),
}


@pytest.mark.parametrize("language", list(OUTSIDE))
def test_a_language_outside_the_ten_is_taken_for_none_of_them_and_kept_in_their_words(app, turn, monkeypatch, language):
    lines, fact, quote = OUTSIDE[language]
    facts = _talk(app, turn, monkeypatch, lines, _fold([
        {"op": "add", "kind": "life", "slot": "job", "text": fact, "quote": quote, "from": ["L1"]}]))
    # The neutral examples and no other language's; their fact is kept as written, with no second ask.
    assert _examples_of(app.model.asked("fold")[0], lines) == {"en"}
    assert [f["text"] for f in facts] == [fact] and len(app.model.asked("fold")) == 1


# Made-up facts on lines of theirs: a fair rewording and other forms of their words are kept, a fact with a word
# they never said is not.
SAID = ["I work at a bakery on Elm Street, early mornings.",
        "I live in Boston with my partner Sam, and the winters are rough.",
        "I play badminton for two hours every weekend, it's my thing."]
TABLE = [  # text, the words of the line it quotes, kept
    ("Works at a bakery on Elm Street", "I work at a bakery on Elm Street", True),
    ("Lives in Boston with partner Sam", "I live in Boston with my partner Sam", True),
    ("Plays badminton on weekends", "I play badminton for two hours every weekend", True),
    ("Hates bakery", "I work at a bakery on Elm Street", False),
    ("Quit bakery", "I work at a bakery on Elm Street", False),
    ("Loves badminton", "I play badminton for two hours every weekend", False),
    ("Owns a dog named Rex", "I live in Boston with my partner Sam", False),
]


def test_a_rewording_of_their_line_is_kept_and_a_fact_with_a_word_they_never_said_is_not(app, turn, monkeypatch):
    facts = _talk(app, turn, monkeypatch, SAID, _fold([
        {"op": "add", "kind": "other", "slot": f"fact{n}", "text": fact, "quote": quote, "from": ["L1"]}
        for n, (fact, quote, _kept) in enumerate(TABLE)]))
    assert sorted(f["text"] for f in facts) == sorted(fact for fact, _quote, kept in TABLE if kept)


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


# A Chinese speaker's line with English words in it: a fact in those words is theirs, though not in Chinese.
SHOPEE = ["我是做frontend engineer的，在Shopee上班", "今天加班到很晚，好累。"]
IN_ENGLISH = {"op": "add", "kind": "life", "slot": "job", "text": "Frontend engineer at Shopee",
              "quote": SHOPEE[0], "from": ["L1"]}


@pytest.mark.parametrize("again, kept", [
    # Asked again, it comes back in words their line does not hold: the true fact stays.
    ("在Shopee做前端工程师", "Frontend engineer at Shopee"),
    # Asked again, it comes back in words their line holds: that one is kept, and only it.
    ("在Shopee上班，做frontend engineer", "在Shopee上班，做frontend engineer"),
])
def test_a_fact_asked_again_in_their_language_never_loses_the_true_one(app, turn, monkeypatch, again, kept):
    facts = _talk(app, turn, monkeypatch, SHOPEE, _fold([IN_ENGLISH]), _fold([dict(IN_ENGLISH, text=again)]))
    assert [f["text"] for f in facts] == [kept] and len(app.model.asked("fold")) == 2


@pytest.fixture
def one_memory_call_a_day(monkeypatch):
    monkeypatch.setenv("MEMORY_CALLS_PER_DAY", "1")


def test_the_ask_again_is_not_made_past_the_days_memory_calls(one_memory_call_a_day, app, turn, monkeypatch):
    # The fold is the day's one call: what came back in another language is refused, not asked for again.
    facts = _talk(app, turn, monkeypatch, EN, _fold(ZH_FOR_EN))
    assert facts == [] and len(app.model.asked("fold")) == 1
