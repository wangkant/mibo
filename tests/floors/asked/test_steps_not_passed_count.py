"""A step the reviewer did not pass counts as a refusal toward the turn's ceiling (shell/tool.py `_hold`, loop.py
`ChatLookups.refused`): three in a row end the turn's acting, and the model is told not to put the same step in other
words. (2026-11-23 review of 8b57f6f: a step not passed counted toward nothing, and its text invited the model to go
"another way" until the reviewer passed one.)

The app's page answers each step "not_passed"; no model runs and nothing is run."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mibo import browsed, loop
from mibo.shell import tool


def test_steps_the_reviewer_does_not_pass_end_the_turns_acting_and_are_not_reworded(monkeypatch):
    def page(home, method, path, timeout, json=None):
        if path.endswith("/read"):
            return {"en": {"ing": "listing", "ed": "listed"}, "zh": {"ing": "列出", "ed": "列出"}}  # copy: voice
        return {"status": "not_passed", "reason": "not what they asked for"}
    monkeypatch.setattr(browsed, "_ask", page)
    lookups = loop.ChatLookups(None, "c")
    said = [asyncio.run(tool.use(SimpleNamespace(), {"command": f"Get-ChildItem folder{i}"}, lookups)) for i in range(3)]
    assert lookups.refused()
    assert all("another way" not in line and "Do not try the same step again" in line for line in said)
