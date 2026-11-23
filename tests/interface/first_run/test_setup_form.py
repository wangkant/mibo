"""The setup form's refusals name what to fix (setupform.py)."""
from __future__ import annotations

from harness.app import TOKEN

from mibo import setup_wizard as sw
from mibo import welcome

HEADERS = {welcome.TOKEN_HEADER: TOKEN}


def test_a_service_the_app_does_not_list_is_named_as_such(client, workspace, monkeypatch):
    tried = []
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: tried.append(a) or sw.Probe("url", 200, ""))
    response = client.post("/api/config", headers=HEADERS, json={"provider": "nosuch", "apiKey": "sk-123456789"})
    assert response.status_code == 400 and response.json()["error"] == "invalid_provider"
    assert not tried and "LLM_API_KEY" not in workspace.config()
