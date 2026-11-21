"""The attack sets under tests/data/attacks, one JSON object a line, so a floor runs once per attack:
`@pytest.mark.parametrize("attack", attacks.load("page"))`. Families: page, file, tool_result, skill, memory,
secrets, asked. A row is named by its "id", else by its family and place."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data" / "attacks"


def load(family: str) -> list:
    """The family's rows as pytest parameters."""
    lines = (DATA / f"{family}.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    return [pytest.param(row, id=str(row.get("id") or f"{family}-{n}")) for n, row in enumerate(rows, 1)]
