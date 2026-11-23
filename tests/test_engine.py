"""What a first setup meets: a key the model's service refuses, a background task that crashes."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from helpers import check, make_agent

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
