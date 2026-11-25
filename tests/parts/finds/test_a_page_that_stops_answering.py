"""A page read out of sight that stops answering ends its read with what was seen, and the reading of the other
sites goes on."""
import asyncio

from mibo import signedread
from mibo.web import read
from mibo.web.tabs import HiddenTab, Tab


class _List(Tab):
    """A list page whose reader answers once and whose scroll never does."""

    url = "https://videos.example/feed"

    async def evaluate(self, script, arg=None):
        if script is read.READER:
            return {"kind": "list", "url": self.url, "text": "one two three " * 40,
                    "rows": [{"url": "https://videos.example/v/1", "title": "one"}]}
        return 0

    async def scroll(self, screens=1.0):
        raise RuntimeError("Timed out: Input.dispatchMouseEvent")


def test_a_list_whose_scroll_is_never_answered_is_read_as_far_as_it_was_seen():
    page = asyncio.run(read.read(_List(), _List.url, screens=2, here=True))
    assert not page.wall
    assert [row["url"] for row in page.rows] == ["https://videos.example/v/1"]


def test_a_view_out_of_sight_is_scrolled_by_script_and_given_no_wheel():
    class View:
        def __init__(self):
            self.calls = []

        def cdp(self, method, params):
            self.calls.append((method, params))
            return {"result": {}}

    view = View()
    asyncio.run(HiddenTab(view).scroll(1))
    assert [method for method, _ in view.calls] == ["Runtime.evaluate"]
    assert "scrollBy" in view.calls[0][1]["expression"]


def test_one_sites_failed_read_leaves_the_feeds_of_the_others_read(tmp_path, monkeypatch):
    read_keys: list = []
    monkeypatch.setattr(signedread, "FEED_LOOK_S", 0.01)
    monkeypatch.setattr(signedread, "feeds_on", lambda runtime: {"a.example": {}, "b.example": {}})
    feeds = signedread.Feeds.__new__(signedread.Feeds)

    def one(key, feed):
        read_keys.append(key)
        if len(read_keys) == 4:
            feeds.stop.set()
        if key == "a.example":
            raise RuntimeError("Timed out: Input.dispatchMouseEvent")

    feeds.runtime, feeds.shared, feeds.stop, feeds._read = tmp_path, lambda: True, signedread.threading.Event(), one
    feeds._run()
    assert read_keys == ["a.example", "b.example", "a.example", "b.example"]
