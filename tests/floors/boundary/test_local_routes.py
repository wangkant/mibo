"""The page's server is for this computer alone: every API route needs the capability token, from the page's
own origin, addressed to a loopback name and through no proxy; nothing outside /api/ can change anything;
answers are never cached and the page is never framed; bodies are bounded."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient
import pytest

from mibo import players, welcome

TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}
# What another page, another device or a proxy in front could send along with a stolen token.
FOREIGN = {"another-site": {"Origin": "https://other.example"},
           "another-port": {"Origin": "http://127.0.0.1:1"},
           "another-name": {"Host": "other.example"},
           "a-name-ending-elsewhere": {"Host": "127.0.0.1.other.example"},
           "x-forwarded-host": {"X-Forwarded-Host": "localhost"},
           "x-forwarded-for": {"X-Forwarded-For": "127.0.0.1"},
           "forwarded": {"Forwarded": "for=127.0.0.1"}}


@pytest.fixture
def app(tmp_path):
    workspace = welcome.Workspace(tmp_path)
    yield welcome.create_app(workspace.home, TOKEN, workspace=workspace)
    workspace.close()


@pytest.fixture
def client(app):
    # No lifespan: the boundary stands before any route, and no character is needed to meet it.
    return TestClient(app, base_url="http://127.0.0.1")


def _api_calls(app) -> list[tuple[str, str]]:
    """(method, path) for every API route the app serves, its path parameters filled in."""
    return [(method, re.sub(r"\{[^}]+\}", "x", route.path))
            for route in app.routes if getattr(route, "path", "").startswith("/api/")
            for method in sorted(route.methods - {"HEAD"})]


def test_the_page_loads_without_the_token_and_every_api_route_refuses_without_it(app, client):
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/.env").status_code == 404
    calls = _api_calls(app)
    assert len(calls) > 100
    let_through = [f"{method} {path}" for method, path in calls
                   if client.request(method, path, json={}).status_code != 403
                   or client.request(method, path, json={}, headers={welcome.TOKEN_HEADER: "guess"}).status_code
                   != 403]
    assert let_through == []


@pytest.mark.parametrize("extra", FOREIGN.values(), ids=FOREIGN.keys())
def test_every_api_route_refuses_a_foreign_origin_host_or_proxy_even_with_the_token(app, client, extra):
    let_through = [f"{method} {path}" for method, path in _api_calls(app)
                   if client.request(method, path, json={}, headers={**HEADERS, **extra}).status_code != 403]
    assert let_through == []
    if "Host" in extra:
        # A page loaded under another name could read the answers it is sent.
        assert client.get("/", headers=extra).status_code == 403


def test_nothing_outside_the_api_can_change_anything(app):
    # Routes outside /api/ carry no token (the page, its assets, and the two sign-in callbacks a browser is
    # sent back to), so they may only read.
    writable = [f"{route.path} {sorted(route.methods)}" for route in app.routes
                if not getattr(route, "path", "/api/").startswith("/api/")
                and set(getattr(route, "methods", ())) - {"GET", "HEAD"}]
    assert writable == []


def test_answers_are_never_cached_and_the_page_is_never_framed(client):
    answer = client.get("/api/state", headers=HEADERS)
    assert answer.status_code == 200 and answer.json()["configured"] is False
    assert answer.headers["cache-control"] == "no-store"
    for path in ("/", "/api/state"):
        policy = client.get(path, headers=HEADERS).headers["content-security-policy"]
        assert "frame-ancestors 'none'" in policy and "default-src 'self'" in policy


def test_the_page_may_frame_the_listed_players_only(client):
    policy = client.get("/", headers=HEADERS).headers["content-security-policy"]
    frames = next(part for part in policy.split(";") if part.strip().startswith("frame-src")).split()[1:]
    assert frames == [f"https://{source}" for source in players.frame_sources()]
    # A platform's own site is not its player: the bare host would let any of its pages in.
    assert "https://www.youtube.com/embed/" in frames and "https://www.youtube.com" not in frames
    assert "img-src 'self' data: blob:" in policy


def test_large_and_malformed_bodies_are_refused(client):
    assert client.post("/api/config", headers=HEADERS, content="x" * (welcome.MAX_BODY + 1)).status_code == 413
    assert client.post("/api/config", headers=HEADERS, content="[]").status_code == 400
    assert client.post("/api/config", headers=HEADERS, content="{").status_code == 400
