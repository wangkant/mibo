"""What a first setup meets: a persona copied from the template, a key the
model's service refuses, a background task that crashes."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from mibo.prompts import render_persona_template

from helpers import check, make_agent


# ---- the persona template ---------------------------------------------------

_TEMPLATE = (
    "You're {bot_name}, a regular here.\n\n"
    "Relationships (optional):\n"
    "- The person you're closest to is {admin_name} ({admin_relationship}). Be looser with them\n"
    "- Everyone else: read the room\n\n"
    "————\n"
    "This is the persona template. Copy it to persona.txt and rewrite it.\n")


def test_the_template_placeholders_are_filled_and_its_note_dropped() -> None:
    out = render_persona_template(_TEMPLATE, bot_name="Luna")
    check("the name is filled in", out.startswith("You're Luna, a regular here."), out)
    check("no admin: the line about one is dropped", "{admin" not in out
          and "closest" not in out and "Everyone else" in out, out)
    check("the note to the reader is cut", "persona.txt" not in out
          and "————" not in out, out)
    out = render_persona_template(_TEMPLATE, bot_name="Luna", admin_name="Kai")
    check("an admin without a relationship loses only the parenthesis",
          "closest to is Kai. Be looser" in out, out)
    out = render_persona_template(_TEMPLATE, bot_name="Luna", admin_name="Kai",
                                  admin_relationship="old friend")
    check("both filled", "closest to is Kai (old friend)." in out, out)
    own = "I'm Mira.\n---\nSecond section, kept."
    check("a document of the user's own is unchanged",
          render_persona_template(own, bot_name="Luna") == own)


def test_a_persona_file_copied_from_the_template_reaches_the_model_filled(
        tmp: Path, monkeypatch) -> None:
    persona = tmp / "persona.txt"
    persona.write_text(_TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("PERSONA_FILE", str(persona))
    agent = make_agent(tmp, persona=None, admin_name="")
    check("the loaded persona has no placeholder and no note",
          "{" not in agent.persona and "persona.txt" not in agent.persona
          and agent.persona.startswith("You're Luna"), agent.persona)


def test_a_users_persona_is_cut_only_at_a_template_note(tmp: Path, monkeypatch) -> None:
    from mibo import setup_wizard as sw

    for own in ("I'm Mira.\n===\nMy notes live in persona.txt, my diary elsewhere.",
                "I'm Mira.\n---\nThe template I started from is long gone.\n\n"
                "persona.txt is mine now."):
        check(f"a section of the user's own is kept: {own!r}",
              render_persona_template(own, bot_name="Luna") == own,
              render_persona_template(own, bot_name="Luna"))
    note = "————\nThis is the persona template. Copy it to persona.txt."
    persona = tmp / "persona.txt"
    persona.write_text(note, encoding="utf-8")
    monkeypatch.setenv("PERSONA_FILE", str(persona))
    agent = make_agent(tmp, persona=None)
    check("a file that is only a note gets the first shipped character",
          "small round robot" in agent.persona and "persona.txt" not in agent.persona, agent.persona)
    out = render_persona_template("Hi.\n- {admin_name}, your {admin_relationship}\nBye.",
                                  bot_name="Luna", admin_name="Kai")
    check("a line that cannot lose its relationship cleanly is dropped",
          out == "Hi.\nBye.", out)
    for lang, text, want in (("en", "Your name is {bot_name}. You are a regular.",
                              "You are a regular."),
                             ("zh", "你叫{bot_name}，是老群友。", "是老群友。")):
        out = render_persona_template(text, bot_name="", lang=lang)
        check(f"no name, no sentence naming nobody ({lang})", out == want, out)
    template = _TEMPLATE.replace("{bot_name}", "Your name is {bot_name}. Hi")
    for admin in ("", "Kai"):
        agent_side = render_persona_template(template, bot_name="Luna", admin_name=admin)
        wizard_side = sw.render_persona(template, name="Luna", lang="en", admin_name=admin)
        check(f"the wizard renders as the agent does (admin={admin!r})",
              wizard_side == agent_side + "\n", repr((wizard_side, agent_side)))


# ---- the connector's own echo and the synthesized mention -------------------

# ---- a model that fails -----------------------------------------------------

# ---- no NapCat HTTP server ---------------------------------------------------

# ---- what the model and the operator read -------------------------------------

def test_a_rejected_key_is_one_operator_line(tmp: Path, caplog) -> None:
    import httpx

    agent = make_agent(tmp, base_url="https://api.openai.com")
    error = httpx.HTTPStatusError(
        "401", request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        response=httpx.Response(401, json={"error": {"message": "Incorrect API key"}}))
    with caplog.at_level(logging.ERROR, logger="agent"):
        agent._report_fatal(error, agent.model)
        agent._report_fatal(error, agent.model)
    lines = [r.getMessage() for r in caplog.records if "model provider" in r.getMessage()]
    check("one line naming the host and the settings to check",
          len(lines) == 1 and "api.openai.com" in lines[0] and "API key" in lines[0]
          and "LLM_API_KEY" in lines[0] and "LLM_BASE_URL" in lines[0], repr(lines))


# ---- background tasks ---------------------------------------------------------

async def test_a_crashed_background_task_is_logged_with_its_name(tmp: Path, caplog) -> None:
    agent = make_agent(tmp)

    async def tag_the_sticker():
        raise ValueError("bad sticker")

    with caplog.at_level(logging.ERROR, logger="agent"):
        task = agent._spawn(tag_the_sticker())
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
    lines = [r.getMessage() for r in caplog.records]
    check("named and explained", any("tag_the_sticker" in m and "bad sticker" in m
                                     for m in lines), repr(lines))
    check("and released", task not in agent._bg_tasks)
