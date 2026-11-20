"""The measurement's own model calls (labelling, judging sentences), with what they cost.

Reads LLM_API_KEY, LLM_BASE_URL and LLM_MODEL from a .env and never prints them.
"""
from __future__ import annotations

from pathlib import Path

import httpx
from dotenv import dotenv_values


def env_values(env: Path) -> dict:
    return {k: str(v or "") for k, v in dotenv_values(env).items()}


class Model:
    def __init__(self, env: Path):
        values = env_values(env)
        self.url = values["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
        self.key = values["LLM_API_KEY"]
        self.model = values.get("LLM_MODEL") or "deepseek/deepseek-v4-flash"
        self.cost = 0.0
        self.calls = 0

    async def ask(self, system: str, user: str, max_tokens: int = 800) -> str:
        body = {"model": self.model, "messages": [{"role": "system", "content": system},
                                                  {"role": "user", "content": user}],
                "max_tokens": max_tokens, "temperature": 0.0, "response_format": {"type": "json_object"},
                "usage": {"include": True}, "reasoning": {"enabled": False}}
        try:
            async with httpx.AsyncClient(timeout=120) as http:
                answer = await http.post(self.url, json=body, headers={"Authorization": f"Bearer {self.key}"})
            answer.raise_for_status()
            data = answer.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"model call failed: {type(exc).__name__}")
            return ""
        self.calls += 1
        self.cost += float((data.get("usage") or {}).get("cost") or 0)
        text = data["choices"][0]["message"].get("content") or ""
        return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
