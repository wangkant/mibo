"""The text module: the model's protocol object and how the reply parser reads it.

Run from the repo root:

    python -m pytest tests/test_textproc.py
"""
from __future__ import annotations

from mibo.textproc import (
    TextProcessing as TP,
    _as_protocol_object,
)

from helpers import check


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
