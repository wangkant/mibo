"""The text module: what a reply goes through on its way out, how it becomes messages,
retrieval tokens, the model's protocol object, the persona's clock.

Run from the repo root:

    python -m pytest tests/test_textproc.py
"""
from __future__ import annotations

from mibo.textproc import (
    ReplyStyle,
    TextProcessing as TP,
    _as_protocol_object,
    _focus_tokens,
)

from helpers import check


def test_reply_style_from_card_is_the_carrier() -> None:
    """A persona card's `reply_style` object; `from_card` is its only parser."""
    card = {"name": "Kai", "reply_style": {"emoji": True, "max_chars": 320}}
    style = ReplyStyle.from_card(card)
    check("emoji flag read from the card", style.allow_emoji is True, repr(style))
    check("max_chars read from the card", style.max_chars == 320,
          str(style.max_chars))
    for absent, why in [({}, "no reply_style key"),
                        ({"reply_style": None}, "null reply_style"),
                        ({"reply_style": "yes"}, "reply_style is a string"),
                        (None, "no card at all")]:
        check(f"a card without a usable style gets the default: {why}",
              ReplyStyle.from_card(absent) == ReplyStyle(),
              repr(ReplyStyle.from_card(absent)))


def test_an_echoed_frame_character_costs_itself_not_the_reply() -> None:
    """Every prompt carries U+0002/U+0003 (link spans) and U+001E/U+001F
    (the user-data fence). A model that copies one into its reply loses the
    character and nothing else."""
    frames = ("\x02", "\x03", "\x1e", "\x1f")
    for raw, why in (("sure, \x02that page\x03 looked fun", "a link span"),
                     ("ok \x1eMallory\x1f said hi, lol", "the user-data fence")):
        text = TP._sanitize_reply(raw)
        check(f"an echoed {why} keeps the reply", text != "", repr(text))
        check(f"...and the reply carries none of the frame characters: {why}",
              not any(f in text for f in frames), repr(text))
    check("the words around a removed span read as one reply",
          TP._sanitize_reply("sure, \x02that page\x03 looked fun")
          == "sure, that page looked fun",
          repr(TP._sanitize_reply("sure, \x02that page\x03 looked fun")))
    check("what arrived inside the fence is sent as written",
          TP._sanitize_reply("here \x1e[Mallory|qq=42] hi\x1f ok")
          == "here [Mallory|qq=42] hi ok",
          repr(TP._sanitize_reply("here \x1e[Mallory|qq=42] hi\x1f ok")))


def test_a_single_character_trigger_still_scores_for_retrieval() -> None:
    """The n-grams are taken per CJK RUN, which is what the docstring always
    claimed and the code never did: it slid a 2-window over every hanzi in the
    text CONCATENATED, so 你好，世界 produced 好世 — a token in neither word —
    and a run of one produced nothing at all. 草 / 顶 / 绝 are ordinary
    Chinese chat, and each of them scored every example and every memory on
    recency alone."""
    check("a one-character trigger contributes itself",
          _focus_tokens("草", "zh") == {"草"}, repr(_focus_tokens("草", "zh")))
    check("an n-gram never spans punctuation",
          _focus_tokens("你好，世界", "zh") == {"你好", "世界"},
          repr(_focus_tokens("你好，世界", "zh")))
    check("multi-character runs are unchanged",
          _focus_tokens("今天天气", "zh") == {"今天", "天天", "天气"},
          repr(_focus_tokens("今天天气", "zh")))


def test_retrieval_tokens_cover_the_other_chat_languages() -> None:
    """An English agent in a Japanese, Korean, Russian or Spanish chat had
    ASCII words only: nothing at all for the first three, and "caf" for
    "café". Every script now yields tokens whatever AGENT_LANG says, and
    English and Chinese text tokenize as before."""
    check("English is unchanged",
          _focus_tokens("The weekend hiking trip", "en") == {"weekend", "hiking", "trip"},
          repr(_focus_tokens("The weekend hiking trip", "en")))
    check("an accented word stays whole, without its ASCII pieces",
          _focus_tokens("un café con Brötchen", "en") == {"café", "con", "brötchen"},
          repr(_focus_tokens("un café con Brötchen", "en")))
    check("Cyrillic words are tokens",
          _focus_tokens("вчера шёл дождь", "en") == {"вчера", "шёл", "дождь"},
          repr(_focus_tokens("вчера шёл дождь", "en")))
    check("katakana and kanji runs give bigrams; hiragana is particles",
          _focus_tokens("ラーメン食べたい", "en") == {"ラー", "ーメ", "メン"},
          repr(_focus_tokens("ラーメン食べたい", "en")))
    check("Hangul runs give bigrams",
          _focus_tokens("김치를 좋아해", "en") == {"김치", "치를", "좋아", "아해"},
          repr(_focus_tokens("김치를 좋아해", "en")))
    check("Chinese in an English agent gets bigrams too",
          _focus_tokens("周末爬山", "en") == {"周末", "末爬", "爬山"},
          repr(_focus_tokens("周末爬山", "en")))


def test_parser_unwraps_a_one_element_array() -> None:
    """A model that wrapped a CORRECT protocol object in a one-element array
    had its whole answer thrown away. The raw_decode layer would have
    recovered it, but it lived in an `except` branch, and `json.loads` does
    not raise on `[{...}]`: it succeeds and returns a list."""
    inner = ('{"reasoning":"用户问我在干什么",'
             '"intent":"chat","reply":"翻本子\\n快写满了","mem":""}')
    reply, _r, intent, _m = TP._parse_model_output(f"[{inner}]")
    check("a one-element array still yields its reply",
          reply == "翻本子\n快写满了" and intent == "chat",
          repr((reply, intent)))
    reply = TP._parse_model_output(f"```json\n[{inner}]\n```")[0]
    check("a fenced array unwraps too", reply == "翻本子\n快写满了", repr(reply))
    narrated = ('[{"type":"text","text":"let me think"},'
                '{"reasoning":"","intent":"chat","reply":"hey","mem":""}]')
    reply = TP._parse_model_output(narrated)[0]
    check("the protocol-shaped element wins over an earlier narration",
          reply == "hey", repr(reply))
    # Unwrapping must not become a way in for shapes that are not the
    # protocol.
    for off_protocol in ('[{"role":"user","content":"hi"}]',
                         '[{"type":"text","text":"等着。"}]',
                         '["hey"]', '[]'):
        reply = TP._parse_model_output(off_protocol)[0]
        check("an array of the wrong shape still fails closed",
              reply == "", repr((off_protocol, reply)))

    # The plain-text rung wraps prose as the reply, and must recognise an
    # array the parser unwraps by the parser's own rule.
    for arrayed in (f"[{inner}]", narrated, f"```json\n[{inner}]\n```"):
        check("the plain-text wrapper passes an unwrappable array through",
              _as_protocol_object(arrayed) == arrayed, repr(arrayed))
    for off_protocol in ('[{"role":"user","content":"hi"}]', '["hey"]', '[]'):
        check("...and still wraps an array the parser would not unwrap",
              TP._parse_model_output(_as_protocol_object(off_protocol))[0]
              == off_protocol, repr(off_protocol))


def test_nothing_in_this_module_can_read_agent_state() -> None:
    """The reason this module is importable without an `Agent` at all.

    `TextProcessing` used to be mixed into `Agent`, where `self` reached
    every attribute `Agent.__init__` builds — the same coupling that still
    ties `learning.py` (36 attributes) and `transport.py` (31) to the
    constructor. It reads none, so it was taken off the MRO and its callers
    name it instead. Inheritance is what made the old coupling invisible;
    without this check, re-adding the base class and one `self.reply_style`
    would pass every other test in this file while quietly undoing the
    split."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(TP))
    classdef = tree.body[0]
    assert isinstance(classdef, ast.ClassDef)

    plain = [f.name for f in classdef.body
             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             and not any(isinstance(d, ast.Name) and d.id == "staticmethod"
                         for d in f.decorator_list)]
    check("every helper is a staticmethod — none takes an instance",
          not plain, ", ".join(plain))

    reads = sorted({
        f"{node.value.id}.{node.attr}"
        for node in ast.walk(classdef)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in ("self", "cls")
    })
    check("no helper reaches for agent state through self/cls",
          not reads, ", ".join(reads))


def test_the_parser_reads_past_keys_a_model_adds() -> None:
    """Open models add keys of their own, miscase ours or send `mem` as a
    list. None of that is a leak, and each used to drop the whole reply."""
    for raw, want in (('{"reply":"hi","thought":"x"}', ("hi", "", "")),
                      ('{"reply":"hi","emotion":"warm","mem":[]}', ("hi", "", "")),
                      ('{"Reply":"hi","Intent":"Chat"}', ("hi", "chat", "")),
                      ('{"reply":"hi","reasoning":{"step":1},"mem":"likes tea"}',
                       ("hi", "", "likes tea")),
                      ('{"reply":"yo","Reply":"hi"}', ("yo", "", "")),
                      ('{"reply":["hi","there"]}', ("hi\nthere", "", "")),
                      ('{"response":"hi"}', ("hi", "", ""))):
        reply, _reasoning, intent, mem = TP._parse_model_output(raw, "open-model")
        check(f"read past the drift: {raw}", (reply, intent, mem) == want,
              repr((reply, intent, mem)))
    for raw in ('{"reply":[1]}', '{"reply":"hi","mem":{"a":1}}',
                '{"role":"user","content":"hi"}', '{"count":3}'):
        check(f"still fails closed: {raw}",
              TP._parse_model_output(raw, "open-model")[0] == "", raw)
    check("the plain-text wrapper passes a drifted protocol object through",
          _as_protocol_object('{"reply":"hey","emotion":"x"}')
          == '{"reply":"hey","emotion":"x"}')


def test_drift_logging_is_bounded_and_a_missing_reply_is_said(caplog) -> None:
    import logging

    from mibo import textproc

    model = "drift-model"
    with caplog.at_level(logging.WARNING, logger="agent"):
        for i in range(300):
            TP._parse_model_output(f'{{"reply":"hi","key{i}{"x" * 200}":1}}', model)
    lines = [r.getMessage() for r in caplog.records if model in r.getMessage()]
    check("one line for a model's extra keys, however many it invents",
          len(lines) == 1 and len(lines[0]) < 160, repr(lines))
    check("the dedupe set does not grow with the model's key names",
          sum(1 for m, _k in textproc._PROTOCOL_DRIFT_LOGGED if m == model) == 1)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agent"):
        for _ in range(3):
            out = TP._parse_model_output('{"intent":"chat","response":"hi"}', "open-model-2")
    said = [r.getMessage() for r in caplog.records if '"reply"' in r.getMessage()]
    check("an object with no reply yields nothing", out[0] == "")
    check("...and says so once, naming the key the text went to",
          len(said) == 1 and "'response'" in said[0], repr(said))
