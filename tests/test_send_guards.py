"""The search gate in all ten chat languages, a reply sent as written, and
the notes for media the character cannot see.

The gate's table has a row per language in `chatlangs.CODES`, and a check
that it does.
"""
from __future__ import annotations

import pytest

from mibo import chatlangs
from mibo.textproc import (
    TextProcessing as TP,
)

from helpers import check


def _covers_every_language(table: dict, what: str) -> None:
    check(f"{what}: a row for every chat language",
          set(table) == set(chatlangs.CODES),
          repr(sorted(set(table) ^ set(chatlangs.CODES))))


# -- the search gate ------------------------------------------------------------

_GATE = {
    "en": (["who won the game last night", "what is black myth wukong",
            "what does rizz mean", "how much is a ps5 now", "who's that singer?",
            "any news on the release", "When does season 2 come out"],
           ["what a day", "how are you", "how are you?", "what's up?", "who cares",
            "how cool is that", "what the hell lol"]),
    "zh": (["周杰伦是谁", "这个梗什么意思", "yyds啥意思", "这电影怎么样", "黑神话是什么",
            "最新的iPhone多少钱", "如何评价这部电影？"],
           ["任何人都可以", "如何是好", "哈哈哈哈", "你怎么了", "今天好累"]),
    "zh-TW": (["周杰倫是誰", "這個梗什麼意思", "最新的iPhone多少錢", "這部電影怎麼樣"],
              ["任何人都可以", "哈哈哈哈", "今天好累"]),
    "ja": (["これ何？", "このミームどういう意味", "いつ発売？", "値段いくら"],
           ["おはよう", "疲れたー", "それな", "任何"]),
    "ko": (["이 밈 무슨 뜻이야", "이거 뭐야", "언제 나와?", "가격 얼마야"],
           ["안녕", "피곤해", "ㅋㅋㅋㅋ"]),
    "es": (["¿qué significa rizz?", "¿quién ganó ayer?", "noticias de la serie"],
           ["hola a todos", "estoy cansado", "jajaja"]),
    "fr": (["qui est ce chanteur", "pourquoi il a fait ça", "le prix de la ps5"],
           ["salut tout le monde", "je suis crevé", "mdr"]),
    "de": (["was ist rizz", "wann kommt staffel 2", "warum ist das so teuer"],
           ["guten morgen", "bin müde", "haha"]),
    "pt-BR": (["o que é rizz", "quem ganhou ontem", "quando sai a temporada 2"],
              ["bom dia gente", "tô cansado", "kkkkk"]),
    "ru": (["что значит рофл", "кто выиграл вчера", "когда выйдет второй сезон"],
           ["доброе утро", "я устал", "ахахах"]),
}


# -- a date, a list ------------------------------------------------------------

def test_a_date_and_a_numbered_list_are_sent_as_written() -> None:
    for text in ("3. Oktober ist Feiertag\nda hab ich frei", "3. Oktober ist Feiertag",
                 "na klar\n24. Dezember bin ich bei meinen Eltern",
                 "1. a\n2. b", "three things\n1. rice\n2. eggs\n3. tea"):
        check(f"{text!r} is unchanged", TP._sanitize_reply(text) == text,
              repr(TP._sanitize_reply(text)))


# -- what the character cannot see ----------------------------------------------

@pytest.mark.parametrize("text", [
    "[image]", "[image] [image]", " [image]\n",
])
def test_a_note_for_unseen_media_is_blind(text: str) -> None:
    check(f"{text!r} is blind", TP._is_blind_content(text))


@pytest.mark.parametrize("text", [
    "[image] what is this", "I sent a photo yesterday",
    "\x02[file: deck.pdf, its text]\nslides\x03", "\x02[image: a cat on a sofa]\x03",
])
def test_a_note_with_words_is_not_blind(text: str) -> None:
    check(f"{text!r} is not blind", not TP._is_blind_content(text))
