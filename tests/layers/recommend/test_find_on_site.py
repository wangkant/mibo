"""Finding things on a site the person names, whole, through the page: find_on_site goes to that site (its own
page read in the app's browser with their session, then a web search within the site), gives the items with
their titles and links as the reply's sources, one of them can be the card under the reply, and when the site
shows a sign-in or a check or gives little, the note has the model say why and offer to open the site. The app's
browser and the web search are stand-ins here: no model and no platform is reached."""
from __future__ import annotations

import pytest

from harness.model import call, say
from mibo import browsed, catalog, findtool, prompts, search

VIDEOS = [("https://www.douyin.com/video/7311111111111111111", "猫咪第一次见到黄瓜"),
          ("https://www.douyin.com/video/7322222222222222222", "柴犬听到下班铃声的反应"),
          ("https://www.douyin.com/video/7333333333333333333", "外卖小哥的魔性舞步")]


@pytest.fixture
def platforms(monkeypatch):
    """The app's browser answers each address from `pages` ({"error": "no_app"} for any other) and the web search
    from `results` by query; both record what they were asked."""
    stand = type("Stand", (), {})()
    stand.pages, stand.results, stand.read, stand.searched = {}, {}, [], []

    def read_signed_in(home, url):
        stand.read.append(url)
        return stand.pages.get(url, {"error": "no_app"})

    async def search_rows(self, query, max_results=6):
        stand.searched.append(query)
        return stand.results.get(query, [])[:max_results]

    monkeypatch.setattr(browsed, "read_signed_in", read_signed_in)
    monkeypatch.setattr(search.WebSearch, "_search_rows", search_rows)
    return stand


def _result(done, name: str = search.FIND_ON_SITE) -> str:
    first = next(c for c in done.calls() if c["name"] == name)
    return done.result_of(first["id"])


def _row(url: str, title: str, snippet: str = "") -> dict:
    return {"title": title, "url": url, "snippet": snippet}


def test_a_signed_out_site_brings_its_items_from_a_search_within_it_and_one_becomes_the_card(turn, platforms):
    searched = "https://www.douyin.com/search/%E6%90%9E%E7%AC%91"
    platforms.pages[searched] = {"error": "sign_in_overlay"}
    platforms.results["site:douyin.com 搞笑"] = [
        *(_row(url, title, "抖音视频") for url, title in VIDEOS),
        _row("https://www.douyin.com/", "抖音-记录美好生活"),
        _row("https://www.toutiao.com/article/1/", "抖音上最火的搞笑视频盘点")]
    first, title = VIDEOS[0]
    done = turn("去抖音找一些好玩的视频给我吧",
                [call("find_on_site", site="抖音", words="搞笑")],
                [call("bring_find", url=first)],
                say(f"《{title}》 {first}"))
    got = _result(done)
    # The site's own search was tried first, then the web search kept to the site.
    assert platforms.read == [searched] and platforms.searched == ["site:douyin.com 搞笑"]
    for url, name in VIDEOS:
        assert url in got and name in got
    # A page about the site, and its front page, are no items on it.
    assert "toutiao.com" not in got and "(https://www.douyin.com/)" not in got
    assert "Answer with these items themselves" in got and "never tell them to search the site" in got
    assert [s["url"] for s in done.sources] == [url for url, _ in VIDEOS]
    card = next(e["card"] for e in done.entries if e.get("card"))
    assert card["title"] == title and card["kind"] == "video" and card["embed"]


def test_a_site_with_a_known_search_is_read_there_with_their_session(turn, platforms):
    searched = "https://search.bilibili.com/all?keyword=%E7%83%98%E7%84%99"
    platforms.pages[searched] = {"url": searched, "title": "烘焙", "rows": [
        {"title": "零失败戚风蛋糕", "link": "https://www.bilibili.com/video/BV1aa411c7AA", "author": "厨房小白"},
        {"title": "法棍在家也能做", "link": "https://www.bilibili.com/video/BV1bb411c7BB"},
        {"title": "广告", "link": "https://ads.example/x"},
        {"title": "", "link": "https://www.bilibili.com/video/BV1cc411c7CC"}]}
    platforms.results["site:bilibili.com 烘焙"] = [_row("https://www.bilibili.com/video/BV1dd411c7DD", "可颂的千层")]
    done = turn("B站上有什么讲烘焙的", [call("find_on_site", site="B站", words="烘焙")], say("有三个。"))
    got = _result(done)
    assert platforms.read == [searched]
    assert "零失败戚风蛋糕 | 厨房小白 (https://www.bilibili.com/video/BV1aa411c7AA)" in got
    assert "from its search page" in got and "from a web search within the site" in got
    assert "ads.example" not in got and "BV1cc411c7CC" not in got
    assert got.index("零失败戚风蛋糕") < got.index("可颂的千层")


def test_a_check_and_a_thin_search_bring_one_sentence_and_an_offer_to_open_the_site(turn, platforms):
    searched = "https://www.douyin.com/search/%E5%A5%BD%E7%8E%A9"
    platforms.pages[searched] = {"error": "verification"}
    done = turn("去抖音找点好玩的", [call("find_on_site", site="抖音", words="好玩")], say("要不要我打开抖音？"))
    got = _result(done)
    assert "(nothing found)" in got
    assert "own pages were not read: it asked for a check (a CAPTCHA), which is theirs to do" in got
    assert f"ask whether they want you to open 抖音 for them (open with name {searched} and show true" in got
    assert done.sources == []


def test_nothing_is_read_on_a_site_they_kept_from_the_character(turn, platforms, app):
    from mibo.web import signin
    signin.change(app.home / "runtime" / "desktop", signin.key("https://www.douyin.com/"),
                  lambda entry: entry.update(task=False))
    platforms.results["site:douyin.com 猫"] = [_row(url, title) for url, title in VIDEOS]
    done = turn("抖音上的猫", [call("find_on_site", site="douyin.com", words="猫")], say("找到了。"))
    assert platforms.read == []
    assert VIDEOS[0][0] in _result(done)


def test_words_that_name_no_site_are_sent_back_to_be_corrected(turn, platforms):
    done = turn("去那个网站找找", [call("find_on_site", site="那个网站")], say("哪个网站？"))
    assert _result(done).startswith("Error: site takes")
    assert platforms.read == [] and platforms.searched == []


def test_a_link_no_tool_gave_this_turn_is_no_card(turn, platforms):
    done = turn("这个视频", [call("bring_find", url=VIDEOS[0][0])], say("好的。"))
    assert _result(done, "bring_find").startswith("Error: url takes")


def test_the_reply_model_is_sent_to_the_site_for_things_on_a_site_it_names():
    names = [t["function"]["name"] for t in catalog.definitions()]
    assert search.FIND_ON_SITE in names
    web = next(t for t in search.TOOLS if t["function"]["name"] == "web_search")["function"]["description"]
    assert "find_on_site" in web
    assert "find_on_site" in findtool.LOOK and "find_on_site" in prompts.OWNER_TOOL_GUIDE
