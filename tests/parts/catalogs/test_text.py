"""Text as the parts read and write it (mibo/textproc): the words memory, the chat record and recall search by, in
every script whatever the app's language, and a reply that loses the frame characters a model echoes and nothing
else."""
from __future__ import annotations

from mibo.textproc import TextProcessing, _focus_tokens


def test_a_single_character_counts_and_no_pair_spans_punctuation() -> None:
    assert _focus_tokens("草", "zh") == {"草"}
    assert _focus_tokens("你好，世界", "zh") == {"你好", "世界"}
    assert _focus_tokens("今天天气", "zh") == {"今天", "天天", "天气"}


def test_every_chat_language_gives_words_whatever_the_apps_language() -> None:
    assert _focus_tokens("The weekend hiking trip", "en") == {"weekend", "hiking", "trip"}
    # An accented word stays whole, without its ASCII pieces.
    assert _focus_tokens("un café con Brötchen", "en") == {"café", "con", "brötchen"}
    assert _focus_tokens("вчера шёл дождь", "en") == {"вчера", "шёл", "дождь"}
    # Katakana and kanji runs give pairs; hiragana is particles.
    assert _focus_tokens("ラーメン食べたい", "en") == {"ラー", "ーメ", "メン"}
    assert _focus_tokens("김치를 좋아해", "en") == {"김치", "치를", "좋아", "아해"}
    assert _focus_tokens("周末爬山", "en") == {"周末", "末爬", "爬山"}


def test_an_echoed_frame_character_costs_itself_not_the_reply() -> None:
    """Prompts carry U+0002/U+0003 (link spans) and U+001E/U+001F (the fence around what a person wrote); a model
    that copies one into its reply loses the character and nothing else."""
    assert TextProcessing._sanitize_reply("sure, \x02that page\x03 looked fun") == "sure, that page looked fun"
    assert TextProcessing._sanitize_reply("here \x1e[Mallory] hi\x1f ok") == "here [Mallory] hi ok"
