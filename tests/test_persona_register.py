"""The 1:1 register: a character who does what is asked, in its own voice.

The sections of `dm_style_guide` checked here are unconditional text, which
is why they are checked over the WHOLE knob space rather than over the
default style: the failure is not a persona choosing badly, it is a later
edit moving a section inside a variant table, or a new variant in a table
between them dropping what follows."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

from persona_agent.agent import Agent
from persona_agent.prompts import (
    OWNER_TOOL_GUIDE,
    STYLE_KNOBS,
    PersonaStyle,
    dm_honest_disclosure,
    dm_output_protocol,
    dm_style_guide,
)

from helpers import check, isolated_agent


def make_agent(tmp: Path) -> Agent:
    """The persona is a stub: what these suites own is the text the engine
    writes around it."""
    return isolated_agent(tmp, persona_name="B")


def _every_style() -> list[PersonaStyle]:
    """Every combination of the knobs, built from `STYLE_KNOBS` so a knob or
    a value added later is covered on the commit that adds it."""
    knobs = sorted(STYLE_KNOBS)
    return [PersonaStyle(**dict(zip(knobs, values)))
            for values in itertools.product(*(STYLE_KNOBS[k] for k in knobs))]


def _assembled_dm_prompt(style: PersonaStyle) -> str:
    """Every block of the 1:1 system prompt a `PersonaStyle` can change, in
    served order."""
    return "\n\n".join((dm_style_guide(style), OWNER_TOOL_GUIDE, dm_output_protocol()))


async def _served_dm_prompts(tmp: Path) -> dict[str, str]:
    """The whole system prompt `_chat_dm` sends: the engine-authored rest of
    it (who they are) is where a banned phrase would slip back in unnoticed."""
    agent = make_agent(tmp)
    captured: list = []

    async def fake_call(system, messages, **kwargs):
        captured.append(system)
        return json.dumps({"reply": "mhm"})


    agent._call_llm = fake_call
    served = {}
    try:
        await agent._chat_dm([{"role": "user", "content": "hey"}], pkey="private:browser:c1")
        served["person"] = captured[-1]
    finally:
        await agent.aclose()
    return served


#: The phrases the register bans, in both languages a reply is written in: a
#: zh build reads the same guide, and an English-only ban would leave it
#: closing every turn like a support ticket.
BANNED_ASSISTANT_PHRASES = (
    "Is there anything else",
    "I'm here to help",
    "Let me know if",
    "有什么我可以帮你的",
    "还有什么需要我帮忙的",
    "有需要随时告诉我",
)

#: The header of the one section allowed to contain those strings.
DOES_HEADER = "[WHAT THEY ASK FOR, YOU DO]"


def _section(guide: str, header: str) -> str:
    """One `[HEADER]` section of the style guide, header line included: from
    its header to the next line opening a bracket at column 0, or `""`."""
    lines = guide.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(header)]
    if not starts:
        return ""
    start = starts[0]
    end = next((i for i, line in enumerate(lines[start + 1:], start + 1)
                if line.startswith("[")), len(lines))
    return "\n".join(lines[start:end])


def test_the_companionship_register_survives_every_knob_combination() -> None:
    """Each anchor is a distinct rule, pinned by a phrase short enough to
    survive rewording and specific enough that deleting the rule deletes it.
    The crisis safety exception is re-checked too."""
    styles = _every_style()
    check("the knob space really is the full cross product",
          len(styles) == 216 and len(set(map(repr, styles))) == len(styles),
          f"{len(styles)} styles")

    anchors = (
        # [WHAT THEY ASK FOR, YOU DO]
        (DOES_HEADER, "the section header"),
        ("Capable, in your own voice", "what is asked is done, in its own voice"),
        ("never a reason to do less", "personality is the tone, never less help"),
        ("Length and form follow what was asked", "length by need"),
        ("Read what they actually said", "what was said is answered"),
        ("is their answer: act on it", "a short line after its own question is an answer"),
        ("Never read a mood into them", "no mood read into them"),
        ("Don't summarize their message back at them", "no read-back"),
        ("make it with schedule_create in that same reply", "a reminder is made, never only promised"),
        # [SMALL TALK]: the two floors under every character
        ("Don't end every turn with a question", "not every turn a question"),
        ("is a whole reply", "'mhm' is a whole reply"),
        ("Never win at their expense", "a tease is never a verdict on them"),
        ("Say the thing", "understood on one read"),
        # [WHEN IT IS ABOUT THE TWO OF YOU]
        ("receive it, do not deflect", "affection is received"),
        ("Do not overcorrect into devotion", "and not performed back"),
        # [PICTURES AND FILES]
        ("read it out, describe it and answer from it", "a picture asked about is read and described"),
        # [DON'T FAKE KNOWING]
        ("is only what <your_day> in the turn context holds", "its day is only what its record holds"),
        # [CONTINUITY]
        ("[CONTINUITY", "the continuity header"),
        ("briefly, once", "raise an open thread briefly and once"),
        ("Never announce that you remembered", "don't narrate the recall"),
    )
    missing: dict[str, list[str]] = {}
    unsafe: list[str] = []
    for style in styles:
        assembled = _assembled_dm_prompt(style)
        for anchor, label in anchors:
            if anchor not in assembled:
                missing.setdefault(label, []).append(repr(style))
        if not ("SAFETY EXCEPTION" in assembled and "crisis line" in assembled):
            unsafe.append(repr(style))

    for _anchor, label in anchors:
        hits = missing.get(label, [])
        check(f"every one of the {len(styles)} styles carries: {label}",
              not hits, f"{len(hits)} styles missing it, e.g. {hits[:1]}")
    check("...and none of them lost the crisis safety exception",
          not unsafe, f"{len(unsafe)} styles, e.g. {unsafe[:1]}")

    guide = dm_style_guide(PersonaStyle())
    talk = _section(guide, "[SMALL TALK")
    check("the floors sit under the teasing licence they bound",
          talk.index("Light teasing only") < talk.index("Never win at")
          and "Say the thing" in talk, talk)
    check("continuity follows DON'T FAKE KNOWING",
          guide.index("[CONTINUITY") > guide.index("[DON'T FAKE KNOWING"))


async def test_no_assistant_ism_survives_the_assembled_dm_prompt(
        tmp: Path) -> None:
    """The banned phrases appear nowhere in the 1:1 prompt except in the one
    section that forbids them. A flat "nowhere" is unsatisfiable, because the
    ban is written by quoting them; so: each occurs exactly once, inside
    `[WHAT THEY ASK FOR, YOU DO]`, on a line that forbids it, and the prompt
    with that section removed contains none of them in any casing — which is
    what catches an example reply or a protocol line teaching one."""
    styles = _every_style()
    headerless: list[str] = []
    not_once: dict[str, list[str]] = {}
    not_a_ban: dict[str, list[str]] = {}
    leaked: dict[str, list[str]] = {}

    def audit(label: str, assembled: str) -> None:
        section = _section(assembled, DOES_HEADER)
        if not section:
            headerless.append(label)
            return
        outside = assembled.replace(section, "\n")
        for phrase in BANNED_ASSISTANT_PHRASES:
            if assembled.count(phrase) != 1 or phrase not in section:
                not_once.setdefault(phrase, []).append(
                    f"{label}: {assembled.count(phrase)} occurrences")
            carrier = [line for line in section.splitlines() if phrase in line]
            if not any("never" in line or "Don't" in line for line in carrier):
                not_a_ban.setdefault(phrase, []).append(repr(carrier))
            hits = [line for line in outside.splitlines()
                    if phrase.lower() in line.lower()]
            if hits:
                leaked.setdefault(phrase, []).append(f"{label}: {hits[0]!r}")

    for style in styles:
        audit(repr(style), _assembled_dm_prompt(style))
    for who, served in (await _served_dm_prompts(tmp)).items():
        audit(f"served to the {who}", served)

    check(f"every prompt renders a {DOES_HEADER} section",
          not headerless, f"{len(headerless)} without one, e.g. {headerless[:1]}")
    for phrase in BANNED_ASSISTANT_PHRASES:
        check(f"{phrase!r} is written exactly once, inside the section that "
              f"bans it", phrase not in not_once,
              repr(not_once.get(phrase, [])[:1]))
        check(f"...on a line that FORBIDS it rather than demonstrating it — "
              f"{phrase!r}", phrase not in not_a_ban,
              repr(not_a_ban.get(phrase, [])[:1]))
        check(f"...and nowhere else in the 1:1 prompt, in any casing — "
              f"{phrase!r}", phrase not in leaked,
              repr(leaked.get(phrase, [])[:1]))


async def test_a_tool_shaped_request_is_answered_by_the_character(
        tmp: Path) -> None:
    """Asked for code, a lookup or a fact, the character does it properly, in
    its own voice: personality is never a reason to do less."""
    protocol = dm_output_protocol()
    check("the protocol has no intent to classify and no PASS",
          '"intent"' not in protocol and "never the literal" in protocol, protocol)
    check("...and its reasoning asks whether the turn needs a lookup",
          "whether it needs a tool or a lookup this turn" in protocol)

    served_by_who = await _served_dm_prompts(tmp)
    for who, served in served_by_who.items():
        check(f"the {who} gets the thing asked for done properly",
              "answer it or do it, fully and correctly" in served, who)
        check(f"...with no refusal of work and no second rule block for the {who}",
              "work to order" not in served and "<private_overrides>" not in served
              and "<rules>" not in served and "<intent_rules>" not in served, who)


async def test_the_dm_guide_tells_the_character_to_receive_affection(
        tmp: Path) -> None:
    """Four turns of "I like you" / "do you like me" / "I'm gay" came back as
    four deflections ending in "we only talk online, don't take it too
    seriously". No rule asked for that, and that was the cause: with nothing
    in the prompt about being cared for, the model fell back on the
    deflection its training rewards.

    The second half is the important one. "Never tell them you are just a
    program" is one edit from "never say you are an AI", and that answer is
    still owed to anyone who sincerely asks. The style rule forbids offering
    it UNASKED, and points at the honesty block instead of restating it."""
    guide = dm_style_guide(PersonaStyle())
    check("1:1 guide: affection is received rather than deflected",
          "receive it, do not deflect" in guide)
    check("1:1 guide: the dodge it was measured making is named",
          "别太当真" in guide and "哦 知道了" in guide)
    check("1:1 guide: a direct question about feelings gets an answer",
          "**answer it**" in guide)
    check("1:1 guide: and it does not swing into devotion",
          "Do not overcorrect into devotion" in guide)
    honesty = dm_honest_disclosure("some-model")
    check("the honest answer is still owed to anyone who sincerely asks",
          "sincerely asks whether you are an AI, answer honestly" in honesty)
    check("...and the model the person set is named when they ask",
          "it is some-model" in honesty and "Leave out" not in honesty, honesty)
    check("the style rule defers to the honesty block instead of replacing it",
          "sincere question about whether you are an AI, which the honesty "
          "block below covers" in guide)

    for who, served in (await _served_dm_prompts(tmp)).items():
        check(f"the {who}'s honesty block really is below the guide",
              served.index("<honesty>")
              > served.index("receive it, do not deflect"), who)
        check(f"...and is the one place the {who}'s prompt says it",
              served.lower().count("answer honestly") == 1, who)


def test_the_guide_lets_the_chat_choose_the_reply_language() -> None:
    """The guide is English and the bundled data English or Chinese, so a
    chat in any other language is answered in it only because [LANGUAGE] says
    so. Unconditional text, so it is checked over every knob combination."""
    for style in _every_style():
        guide = dm_style_guide(style)
        check("the guide follows the other person's language",
              "language they write to you in" in _section(guide, "[LANGUAGE]"), repr(style))
        check("...after what it does, which stays first",
              guide.index(DOES_HEADER) < guide.index("[LANGUAGE]") < guide.index("[FORMAT"),
              repr(style))


def test_a_cards_emoji_opt_in_and_length_reach_the_prompt(tmp: Path) -> None:
    """A card sets `reply_style`; the prompt said emoji were banned
    whatever the card said. The default card must give the default text, or
    the provider's prompt cache starts over."""
    import dataclasses

    agent = make_agent(tmp)
    default_dm = agent._build_dm_prompt([{"role": "user", "content": "hi"}]).system
    check("the default card keeps the guide byte for byte", dm_style_guide(agent.persona_style) in default_dm)
    check("no emoji at the default card", "- No emoji, no kaomoji" in default_dm)

    agent.reply_style = dataclasses.replace(agent.reply_style, allow_emoji=True)
    dm = agent._build_dm_prompt([{"role": "user", "content": "hi"}]).system
    check("emoji as the character uses them",
          "- Emoji only as this character uses them" in dm and "- No emoji" not in dm)
    check("no length line at the default length", "stay under" not in dm)

    agent.reply_style = dataclasses.replace(agent.reply_style, max_chars=120)
    dm = agent._build_dm_prompt([{"role": "user", "content": "hi"}]).system
    check("a shorter limit is stated for small talk only, never for code or a real answer",
          "In small talk stay under 120 characters; code, lists and the answer "
          "to a real question are not counted" in dm)
