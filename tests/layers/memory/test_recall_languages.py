"""Recall of past chats for a person in any of the ten chat languages: a search in the words they used finds their
line whatever language it is in, and the search tool the reply model is given shows its examples in several
languages, so a small model does not translate the query into one (a translated query finds nothing)."""
from __future__ import annotations

import re

from harness.model import call, say
from harness.turn import run_turn
from mibo import chatlangs, pastchats

# A line in each chat language, and words of it a search would use.
SAID = {
    "en": ("I finished reading Project Hail Mary last month.", "Project Hail Mary"),
    "zh": ("我上个月读完了《三体》，太震撼了。", "三体"),
    "zh-TW": ("我上個月在台南吃到一家很棒的牛肉湯。", "牛肉湯 台南"),
    "ja": ("大阪の病院で看護師として働いています。", "看護師 病院"),
    "ko": ("새로 산 자전거 색깔은 파란색이에요.", "자전거 색깔"),
    "es": ("Mi hermana se casa en Granada el próximo verano.", "hermana Granada"),
    "fr": ("Ma grand-mère m'a appris à faire des crêpes bretonnes.", "crêpes bretonnes"),
    "de": ("Ich habe endlich meinen Führerschein bestanden.", "Führerschein"),
    "pt-BR": ("Comprei uma bicicleta vermelha no sábado.", "bicicleta vermelha"),
    "ru": ("Я купила новую машину, красную Ладу.", "машину Ладу"),
}


def test_a_search_in_their_own_words_finds_a_past_line_in_each_of_the_ten_languages(app):
    for code, (line, _query) in SAID.items():
        assert run_turn(app, line, say("ok")).status == 200, code
    chat = app.post("/api/chats").json()["id"]
    done = run_turn(app, "Do you remember what I told you?", [call(pastchats.NAME, query=q) for _l, q in SAID.values()],
                    say("Yes."), conversation=chat)
    found = {code: done.result_of(searched["id"]) for code, searched in zip(SAID, done.calls())}
    assert {code: line for code, (line, _q) in SAID.items() if line not in found[code]} == {}


def test_the_search_tool_shows_its_examples_in_several_languages(app):
    done = run_turn(app, "hi", say("hi"))
    tool = next(t["function"] for t in done.asked()[0]["tools"] if t["function"]["name"] == pastchats.NAME)
    words = [tool["description"], *(p["description"] for p in tool["parameters"]["properties"].values())]
    examples = [e for w in words for e in re.findall(r'"([^"]+)"', w)]
    shown = {chatlangs.detect(e, "") for e in examples}
    assert len(shown - {""}) >= 3, examples
