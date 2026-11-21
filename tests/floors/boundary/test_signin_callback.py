"""The two sign-in callbacks sit outside /api/, since a browser sent back by OpenRouter or an MCP server's
consent page carries no token. So each admits only a navigation on this computer to localhost at the page's
own port, with no proxy in front; and OpenRouter's code is bound to its attempt's state, used once."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

from mibo import openrouter_signin as osr
from mibo import setup_wizard as sw
from mibo import welcome
from mibo.panels import signin
from mibo.panels import tools

HEADERS = {welcome.TOKEN_HEADER: "token"}
# Only a label for the page's address: nothing listens on it.
PORT = 18911
CALLBACKS = (signin.CALLBACK_PATH, tools.CALLBACK_PATH)


@pytest.fixture
def page(tmp_path, monkeypatch):
    """The page with an OpenRouter attempt that can finish: the code exchange and the key check stand in,
    and each exchange is counted."""
    exchanged: list[str] = []
    monkeypatch.setattr(signin, "open_browser", lambda url: True)
    monkeypatch.setattr(osr, "exchange", lambda code, verifier: exchanged.append(code) or "sk-or-v1-standin-0123456789")
    monkeypatch.setattr(sw, "probe_key", lambda base, key, model, timeout=30: sw.Probe(base, 200))
    workspace = welcome.Workspace(tmp_path)
    app = welcome.create_app(tmp_path, "token", workspace=workspace)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000))
    yield {"app": app, "client": client, "exchanged": exchanged}
    workspace.close()


def _start(client) -> str:
    """Start an attempt from the page; the state OpenRouter will send back."""
    started = client.post("/api/signin/start", headers=HEADERS, json={
        "provider": "openrouter", "form": {"model": "openrouter/free", "name": "Mira", "character": "mibo"}})
    return parse_qs(urlsplit(started.json()["url"]).query)["state"][0]


def _back(client, query: dict, path: str = signin.CALLBACK_PATH, host: str = f"localhost:{PORT}", **headers):
    return client.get(path, params=query, headers={"host": host, **headers})


def _waiting(client) -> bool:
    return client.get("/api/signin", headers=HEADERS).json()["state"] == "waiting"


@pytest.mark.parametrize("path", CALLBACKS)
@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", "localhost:1", "localhost", f"evil.example:{PORT}",
                                  f"localhost:{PORT}.evil.example"])
def test_the_callback_admits_only_localhost_at_the_page_s_port(page, path, host):
    client = page["client"]
    state = _start(client)
    assert _back(client, {"code": "c", "state": state}, path=path, host=host).status_code == 403
    assert _waiting(client) and page["exchanged"] == []


@pytest.mark.parametrize("path", CALLBACKS)
def test_the_callback_refuses_a_forwarded_request(page, path):
    client = page["client"]
    state = _start(client)
    for header in ("x-forwarded-for", "x-forwarded-host", "forwarded"):
        assert _back(client, {"code": "c", "state": state}, path=path, **{header: "1.2.3.4"}).status_code == 403
    assert _waiting(client) and page["exchanged"] == []


@pytest.mark.parametrize("path", CALLBACKS)
def test_another_device_cannot_end_the_attempt_with_a_borrowed_host(page, path):
    state = _start(page["client"])
    other = TestClient(page["app"], base_url=f"http://127.0.0.1:{PORT}", client=("192.168.1.99", 50000))
    for query in ({}, {"code": "c"}, {"error": "access_denied"}, {"code": "c", "state": state}):
        assert _back(other, query, path=path).status_code == 403, query
    assert _waiting(page["client"]) and page["exchanged"] == []


def test_a_refusal_without_the_state_cannot_end_the_attempt(page):
    client = page["client"]
    state = _start(client)
    # OpenRouter sends no state when access is denied, and any page the person visits can send the same.
    assert _back(client, {}).status_code == 400 and _waiting(client)
    # With the attempt's own state and no code, it is this attempt that was refused.
    assert _back(client, {"state": state}).status_code == 400
    assert client.get("/api/signin", headers=HEADERS).json()["error"] == "signin_denied"


def test_the_state_binds_the_callback_to_its_attempt_once(page):
    client = page["client"]
    state = _start(client)
    for wrong in ({"code": "c", "state": "guess"}, {"code": "c"}, {"code": "c", "state": state[:-1]}):
        assert _back(client, wrong).status_code == 400, wrong
        assert _waiting(client), wrong
    assert page["exchanged"] == []
    assert _back(client, {"code": "c", "state": state}).status_code == 200
    # The same link again finds the attempt finished: no second exchange.
    assert _back(client, {"code": "c", "state": state}).status_code == 400
    assert page["exchanged"] == ["c"]


def test_a_link_replayed_while_its_code_is_being_exchanged_finishes_nothing(page, monkeypatch):
    client = page["client"]
    state = _start(client)
    replayed = []

    def exchange(code, verifier):
        page["exchanged"].append(code)
        # The same link arrives again while the first is still trading its code for a key.
        if len(page["exchanged"]) == 1:
            replayed.append(_back(client, {"code": code, "state": state}).status_code)
        return "sk-or-v1-standin-0123456789"

    monkeypatch.setattr(osr, "exchange", exchange)
    assert _back(client, {"code": "c", "state": state}).status_code == 200
    assert replayed == [400] and page["exchanged"] == ["c"]
