"""The library's pictures over the page's API."""
from __future__ import annotations

import warnings

import pytest

from persona_agent import life, players, welcome
from persona_agent.library import Item, Library

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

NOW = 1_800_000_000
TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}
PLAYER = "https://www.youtube-nocookie.com/embed/abc"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(life, "clock", lambda: NOW)


def fill(runtime) -> list[Item]:
    library = Library(runtime)
    told = library.add(Item(url="https://www.youtube.com/watch?v=abc", site="YouTube", kind="video",
                            title="Slow train north", why="You said you miss long rides.", fits=True,
                            embed=PLAYER, seen_at=NOW - 120, text="A night on the line."))
    plain = library.add(Item(url="https://example.test/post", site="Example", kind="article",
                             title="On kettles", fits=True, seen_at=NOW - 60))
    other = library.add(Item(url="https://example.test/other", title="Not for the owner", seen_at=NOW - 30))
    return [told, plain, other]


# ---------------------------------------------------------------- page ----

@pytest.fixture
def workspace(tmp_path):
    value = welcome.Workspace(tmp_path)
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    with TestClient(welcome.create_app(workspace.home, TOKEN, workspace=workspace),
                    base_url="http://127.0.0.1") as value:
        yield value


def test_the_cover_comes_from_the_library_only(client, workspace):
    told, plain, _ = fill(workspace.home / "runtime")
    library = Library(workspace.home / "runtime")
    told.picture = library.save_picture(told.id, b"\xff\xd8\xff" + b"x" * 50)
    library.add(told)
    cover = client.get(f"/api/library/picture/{told.id}", headers=HEADERS)
    assert cover.status_code == 200 and cover.headers["content-type"] == "image/jpeg"
    assert cover.content.startswith(b"\xff\xd8\xff")
    for name in (plain.id, "0" * 16, "..%2F..%2F.env"):
        assert client.get(f"/api/library/picture/{name}", headers=HEADERS).status_code == 404


def test_the_page_may_frame_the_listed_players_only(client):
    policy = client.get("/", headers=HEADERS).headers["content-security-policy"]
    frames = next(part for part in policy.split(";") if part.strip().startswith("frame-src")).split()[1:]
    assert frames == [f"https://{source}" for source in players.frame_sources()]
    assert "https://www.youtube.com/embed/" in frames and "https://www.youtube.com" not in frames
    assert "img-src 'self' data: blob:" in policy and "frame-ancestors 'none'" in policy


def test_a_reply_item_keeps_a_clean_card_and_loses_a_foreign_player(workspace):
    card = {"kind": "video", "title": "T", "url": "https://example.test/v", "embed": "https://evil.test/p"}
    entry = workspace._entry({"type": "text", "text": "look", "card": card})
    assert entry["card"]["embed"] == "" and entry["card"]["url"] == card["url"]
    assert "card" not in workspace._entry({"type": "text", "text": "plain"})
    assert "card" not in workspace._entry({"type": "text", "text": "x", "card": {"url": "file:///c:/x"}})

