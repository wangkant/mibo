"""A card on a reply entry keeps only what the page may show; the cover route and the page's frame
policy are floors in tests/floors/boundary/."""
from __future__ import annotations

import pytest

from mibo import welcome


@pytest.fixture
def workspace(tmp_path):
    value = welcome.Workspace(tmp_path)
    yield value
    value.close()


def test_a_reply_item_keeps_a_clean_card_and_loses_a_foreign_player(workspace):
    card = {"kind": "video", "title": "T", "url": "https://example.test/v", "embed": "https://evil.test/p"}
    entry = workspace._entry({"type": "text", "text": "look", "card": card})
    assert entry["card"]["embed"] == "" and entry["card"]["url"] == card["url"]
    assert "card" not in workspace._entry({"type": "text", "text": "plain"})
    assert "card" not in workspace._entry({"type": "text", "text": "x", "card": {"url": "file:///c:/x"}})

