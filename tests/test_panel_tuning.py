"""The tuning panel: the backup model and the models for other uses, saved the way the page saves the rest."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from mibo import setup_wizard as sw
from mibo import welcome
from mibo.panels import tuning

TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}
SECRET = "sk-backup-secret-0123456789"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    value = welcome.Workspace(tmp_path)
    sw.copy_env_template(tmp_path)
    sw.write_env(value.env, {"LLM_API_KEY": "sk-main-key-0123456789", "LLM_BASE_URL": "https://api.deepseek.com",
                             "LLM_MODEL": "deepseek-chat", "PERSONA_NAME": "Mira", "AGENT_LANG": "en"})
    probes = []
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: probes.append(a) or sw.Probe("u", 200, ""))
    value.probes = probes
    restarts = []
    monkeypatch.setattr(value.character, "reload", lambda: restarts.append(True))
    value.restarts = restarts
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    with TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace),
                    base_url="http://127.0.0.1") as value:
        yield value


def post(client, payload, path="/api/tuning"):
    return client.post(path, headers=HEADERS, json=payload)


def test_routes_need_the_page_token(client):
    assert client.get("/api/tuning").status_code == 403
    assert client.post("/api/tuning", json={}).status_code == 403


def test_view_lists_every_field_and_never_a_key(client, workspace):
    sw.write_env(workspace.env, {"LLM_FALLBACK_API_KEY": SECRET})
    response = client.get("/api/tuning", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert SECRET not in response.text and "sk-main-key" not in response.text
    assert body["secrets"]["LLM_FALLBACK_API_KEY"] == sw.mask_secret(SECRET)
    assert set(body["values"]) == set(tuning.BY_KEY) - {"LLM_FALLBACK_API_KEY"}
    assert body["llmBaseUrl"] == "https://api.deepseek.com"


def test_saving_writes_only_what_changed_and_restarts(client, workspace):
    before = workspace.env.read_text(encoding="utf-8")
    body = post(client, {"values": {"LLM_JUDGE_MODEL": "judge-small", "LLM_DM_MODEL": "chat-large",
                                    # The same as what is there: not written.
                                    "LLM_FALLBACK_MODEL": ""}}).json()
    assert body["changed"] and workspace.restarts == [True]
    values = workspace.config()
    assert values["LLM_JUDGE_MODEL"] == "judge-small" and values["LLM_DM_MODEL"] == "chat-large"
    after = workspace.env.read_text(encoding="utf-8")
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert {b.split("=")[0] for _, b in changed} == {"LLM_JUDGE_MODEL", "LLM_DM_MODEL"}
    assert len(before.splitlines()) == len(after.splitlines())
    assert body["values"]["LLM_JUDGE_MODEL"] == "judge-small"


def test_nothing_changed_writes_nothing(client, workspace):
    before = workspace.env.read_bytes()
    body = post(client, {"values": {"LLM_JUDGE_MODEL": ""}}).json()
    assert body["changed"] is False and workspace.restarts == []
    assert workspace.env.read_bytes() == before


@pytest.mark.parametrize("key, value", [
    ("LLM_FALLBACK_MODEL", "two words"), ("LLM_FALLBACK_BASE_URL", "ftp://x"),
    ("LLM_JUDGE_MODEL", "${LLM_API_KEY}"), ("LLM_DM_MODEL", "x" * 257),
])
def test_a_bad_value_is_refused_naming_its_field(client, workspace, key, value):
    before = workspace.env.read_bytes()
    response = post(client, {"values": {key: value}})
    assert response.status_code == 400
    assert response.json()["error"] == f"tuning_invalid:{key}"
    assert workspace.env.read_bytes() == before and workspace.restarts == []


def test_other_refusals(client, workspace):
    assert post(client, {"values": {"SERVER_HOST": "0.0.0.0"}}).json()["error"] == "tuning_unknown"
    assert post(client, {"values": {"LLM_API_KEY": "x"}}).json()["error"] == "tuning_unknown"
    assert post(client, {"values": {"LLM_FALLBACK_BASE_URL": "http://example.com"}}).json()["error"] == "tuning_https"
    assert "SERVER_HOST" not in workspace.env.read_text(encoding="utf-8")


def test_refused_before_a_model(client, workspace):
    sw.write_env(workspace.env, {"LLM_API_KEY": ""})
    assert post(client, {"values": {"LLM_JUDGE_MODEL": "j"}}).json()["error"] == "tuning_not_configured"


def test_backup_model_key_is_kept_with_its_address_and_never_returned(client, workspace, monkeypatch):
    other = "https://openrouter.ai/api/v1"
    response = post(client, {"values": {"LLM_FALLBACK_MODEL": "cheap", "LLM_FALLBACK_BASE_URL": other}})
    assert response.json()["error"] == "tuning_key_needed"
    response = post(client, {"values": {"LLM_FALLBACK_MODEL": "cheap", "LLM_FALLBACK_BASE_URL": other,
                                        "LLM_FALLBACK_API_KEY": SECRET}})
    assert response.status_code == 200 and SECRET not in response.text
    assert workspace.probes[-1] == (other, SECRET, "cheap")
    values = workspace.config()
    assert values["LLM_FALLBACK_API_KEY"] == SECRET and values["LLM_FALLBACK_BASE_URL"] == other
    # A blank key keeps the saved one; a new address drops it.
    post(client, {"values": {"LLM_FALLBACK_MODEL": "cheaper", "LLM_FALLBACK_API_KEY": ""}})
    assert workspace.config()["LLM_FALLBACK_API_KEY"] == SECRET
    assert post(client, {"values": {"LLM_FALLBACK_BASE_URL": "https://api.groq.com/openai/v1"}}).json()["error"] \
        == "tuning_key_needed"
    post(client, {"values": {"LLM_FALLBACK_BASE_URL": ""}})
    assert workspace.config()["LLM_FALLBACK_API_KEY"] == ""
    # On the main service, the main key is used to check it.
    post(client, {"values": {"LLM_FALLBACK_MODEL": "deepseek-other"}})
    assert workspace.probes[-1] == ("https://api.deepseek.com", "sk-main-key-0123456789", "deepseek-other")


@pytest.mark.parametrize("status, code", [(401, "tuning_fallback_rejected"), (429, "tuning_fallback_limited"),
                                          (500, "tuning_fallback_unreachable")])
def test_a_backup_model_that_does_not_answer_is_not_saved(client, workspace, monkeypatch, status, code):
    monkeypatch.setattr(sw, "probe_key", lambda *a, **kw: sw.Probe("u", status, "echo " + SECRET))
    response = post(client, {"values": {"LLM_FALLBACK_MODEL": "cheap"}})
    assert response.json()["error"] == code and SECRET not in response.text
    assert workspace.config()["LLM_FALLBACK_MODEL"] == ""


def test_backup_model_unreachable_when_the_probe_raises(client, workspace, monkeypatch):
    def boom(*a, **kw):
        raise OSError(SECRET)
    monkeypatch.setattr(sw, "probe_key", boom)
    response = post(client, {"values": {"LLM_FALLBACK_MODEL": "cheap"}})
    assert response.json()["error"] == "tuning_fallback_unreachable" and SECRET not in response.text


def test_every_error_code_is_let_through(client):
    for code in ("tuning_key_needed", "tuning_invalid:LLM_FALLBACK_MODEL", "tuning_fallback_rejected"):
        assert code in tuning.ERRORS
