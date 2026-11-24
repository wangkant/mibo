"""The platforms the person chose (推荐偏好) as a preference, not a filter: a lift in the sources' prior shared
among a platform's lists that the person reads, a place in the first run's samples for each chosen platform that
has a find. A chosen platform read only signed in has its own feed read once the person agreed and is signed in to
it, never a feed they turned off or a wall stopped, and only the feeds a choice turned on go with that choice; a
video from that feed plays on its card."""
from __future__ import annotations

from itertools import pairwise

import pytest
from harness.clock import Clock
from harness.finds import Shelf

from mibo import signedread
from mibo.library import Library
from mibo.panels import browser, feed
from mibo.sources import weights
from mibo.sources.base import Source
from mibo.web import signin, sites

NOW = 1_800_000_000


def source(key: str, platform: str = "", lang: str = "zh") -> Source:
    return Source(key, (key, key), ("", ""), "video", None, lang=lang, platform=platform)


def test_a_chosen_platform_lifts_its_sources_prior_shared_among_its_lists():
    listed = [source("bili-a", "bilibili.com"), source("bili-b", "bilibili.com"), source("douyu-hot", "douyu.com"),
              source("news")]
    prior = {row["source"].key: row["prior"] for row in weights.weigh(listed, {}, "zh", None)}
    assert prior == dict.fromkeys(prior, 1.0)
    chosen = {row["source"].key: row["prior"]
              for row in weights.weigh(listed, {}, "zh", None, platforms={"bilibili.com", "douyu.com"})}
    assert chosen == {"bili-a": 1 + weights.PLATFORM / 2, "bili-b": 1 + weights.PLATFORM / 2,
                      "douyu-hot": 1 + weights.PLATFORM, "news": 1.0}


def test_a_chosen_platform_is_shared_only_among_the_lists_in_languages_the_person_reads():
    listed = [source("apple-zh", "apple.com"), source("apple-de", "apple.com", "de"), source("apple-fr", "apple.com", "fr")]
    prior = {row["source"].key: row["prior"] for row in weights.weigh(listed, {}, "zh", None, platforms={"apple.com"})}
    assert prior == {"apple-zh": 1 + weights.PLATFORM, "apple-de": weights.OTHER_LANG, "apple-fr": weights.OTHER_LANG}


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    return Shelf(tmp_path / "runtime", Clock(monkeypatch, NOW), monkeypatch)


def test_the_first_run_keeps_a_place_for_each_chosen_platform_with_a_find(shelf):
    for n in range(4):
        for site in ("kitchen", "pitch", "gadget", "harbour", "garden", "studio", "market", "orchard"):
            shelf.add(f"A story from the {site} number {n}", site=f"{site}.example", hours_ago=0.5,
                      text="A summary long enough to say what the story is about, and then some more of it.")
    # Older than all of the above, and a live room says little more than its title: a video platform's need not.
    live = shelf.add("今晚的围棋直播", site="www.douyu.com", kind="video", text="直播", hours_ago=30)
    show = shelf.add("A drama, episode one", site="v.qq.com", kind="video", hours_ago=30,
                     text="A summary long enough to say what the story is about, and then some more of it.")
    # A WeRead book is on qq.com too, but not Tencent Video: no platform of the catalogue's own, none by its address.
    book = shelf.add("A novel on the rise", site="weread.qq.com", kind="video", text="", hours_ago=30,
                     source="weread-rising")
    for chosen in (["douyu.com", "qq.com", "tiktok.com"], []):
        shown = feed.first_round(shelf.library, [], shelf.clock.now, ["food"], chosen)
        sites_ = [row["site"] for row in shown]
        assert len(shown) == feed.FIRST_MAX and max(sites_.count(site) for site in sites_) <= feed.FIRST_PER_SOURCE
        assert all(a != b for a, b in pairwise(sites_)), sites_
        assert book.id not in {row["id"] for row in shown}
        if chosen:
            assert {live.id, show.id} <= {row["id"] for row in shown}, sites_


def signed(runtime, *urls: str) -> None:
    for url in urls:
        signin.became(runtime / "desktop", url, "signin")


def reading(runtime) -> set[str]:
    return set(signedread.feeds_on(runtime))


def test_without_the_agreement_no_choice_reads_a_feed(tmp_path):
    runtime = tmp_path / "runtime"
    signed(runtime, "https://www.douyin.com/", "https://x.com/")
    browser.switch_feed(runtime, "x.com", True, "https://x.com/")
    feed.keep_platforms(runtime, ["douyin.com", "bilibili.com", "x.com", "weibo.com"])
    assert feed.load_platforms(runtime) == ["douyin.com", "bilibili.com", "x.com", "weibo.com"]
    signed(runtime, "https://weibo.com/")
    assert reading(runtime) == {"x.com"}
    feed.keep_platforms(runtime, ["bilibili.com"])
    assert reading(runtime) == {"x.com"}


def test_with_the_agreement_a_chosen_platform_is_read_once_signed_in_now_or_later(tmp_path):
    runtime = tmp_path / "runtime"
    signed(runtime, "https://www.douyin.com/")
    feed.keep_platforms(runtime, ["douyin.com", "weibo.com"])
    assert not feed.agreed(runtime) and reading(runtime) == set()
    feed.agree(runtime)
    feed.keep_platforms(runtime, ["douyin.com", "weibo.com"])
    assert feed.agreed(runtime) and reading(runtime) == {"douyin.com"}
    assert signedread.feeds_on(runtime)["douyin.com"]["url"] == "https://www.douyin.com/jingxuan"
    signed(runtime, "https://www.weibo.com/home")
    assert reading(runtime) == {"douyin.com", "weibo.com"}


def test_a_feed_the_person_turned_off_or_a_wall_stopped_stays_off_after_a_choice(tmp_path):
    runtime = tmp_path / "runtime"
    feed.agree(runtime)
    signed(runtime, "https://www.douyin.com/", "https://www.xiaohongshu.com/")
    browser.switch_feed(runtime, "douyin.com", False, "https://www.douyin.com/")
    sites._change(runtime, "xiaohongshu.com", lambda card: card.update(feed={"on": False, "stopped": "verification"}))
    feed.keep_platforms(runtime, ["douyin.com", "xiaohongshu.com"])
    assert reading(runtime) == set()
    # A sign-in seen again does not turn it on either.
    signin.signed_out(runtime / "desktop", "douyin.com")
    signed(runtime, "https://www.douyin.com/")
    assert reading(runtime) == set()


def test_letting_a_platform_go_turns_off_only_the_feed_its_choice_turned_on(tmp_path):
    runtime = tmp_path / "runtime"
    feed.agree(runtime)
    signed(runtime, "https://www.douyin.com/", "https://x.com/", "https://www.kuaishou.com/")
    browser.switch_feed(runtime, "x.com", True, "https://x.com/")
    feed.keep_platforms(runtime, ["douyin.com", "x.com", "kuaishou.com"])
    assert reading(runtime) == {"douyin.com", "x.com", "kuaishou.com"}
    # The person's own switch takes a feed a choice turned on over.
    browser.switch_feed(runtime, "kuaishou.com", True, "https://www.kuaishou.com/")
    feed.keep_platforms(runtime, [])
    assert reading(runtime) == {"x.com", "kuaishou.com"}
    # Let go, it is nobody's choice: a new choice reads it again.
    feed.keep_platforms(runtime, ["douyin.com"])
    assert reading(runtime) == {"douyin.com", "x.com", "kuaishou.com"}


def test_an_open_platform_or_one_the_registry_does_not_know_never_touches_a_feed(tmp_path):
    runtime = tmp_path / "runtime"
    feed.agree(runtime)
    signed(runtime, "https://www.bilibili.com/", "https://www.youtube.com/", "https://gone.example/")
    feed.keep_platforms(runtime, ["bilibili.com", "youtube.com", "gone.example"])
    signed(runtime, "https://news.example/")
    assert reading(runtime) == set() and sites.load(runtime) == {}


def test_a_saved_platform_the_registry_no_longer_knows_is_left_out(tmp_path):
    runtime = tmp_path / "runtime"
    feed.keep_platforms(runtime, ["bilibili.com", "gone.example"])
    assert feed.load_platforms(runtime) == ["bilibili.com"]
    assert [row["key"] for row in feed.offered_platforms(runtime, "zh") if row["key"] == "gone.example"] == []


def test_an_unknown_platform_is_refused_and_one_chosen_twice_is_kept_once():
    assert feed.clean_platforms(["douyin.com", "bilibili.com", "douyin.com"]) == ["douyin.com", "bilibili.com"]
    for wrong in (["evil.example"], ["douyin.com", 3], "douyin.com", None):
        with pytest.raises(ValueError, match="feed_platforms"):
            feed.clean_platforms(wrong)


def test_a_video_from_a_signed_in_feed_plays_on_its_card(tmp_path):
    runtime = tmp_path / "runtime"
    rows = [{"title": "A dance", "link": "https://www.douyin.com/video/7300000000000000001"},
            {"title": "A note", "link": "https://www.douyin.com/note/7300000000000000002"},
            {"title": "Elsewhere", "link": "https://www.example.com/video/1"}]
    assert signedread.keep_finds(runtime, "douyin.com", rows) == 2
    video, note = (Library(runtime).get(item.id) for item in sorted(Library(runtime).items(), key=lambda i: i.title))
    assert (video.kind, video.embed) == ("video", "https://open.douyin.com/player/video?vid=7300000000000000001&autoplay=0")
    assert (note.kind, note.embed) == ("post", "")
