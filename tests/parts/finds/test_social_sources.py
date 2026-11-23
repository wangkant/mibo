"""The social, reading and listening platforms' sources: each reads a recorded, trimmed answer of its
list page or API into finds with a real title, the thing's own page and a cover, and leaves out what a
plain visitor should not be shown (adult titles, posts with no words, films not yet in cinemas)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from mibo.sources import base, catalog, social

SAMPLES = Path(__file__).resolve().parent / "samples" / "social"

# key: (sample, finds read, first link, first title, the first cover starts with)
EXPECTED = {
    "github-trending": ("github-trending.html", 3, "https://github.com/elementalsouls/Claude-BugHunter",
                        "elementalsouls/Claude-BugHunter", ""),
    "douban-nowplaying": ("douban-nowplaying.html", 3, "https://movie.douban.com/subject/36915988/", "饥饿游戏：收获日出",
                          "https://img3.doubanio.com/"),
    "douban-new-films": ("douban-chart.html", 2, "https://movie.douban.com/subject/36847425/", "可能的爱",
                         "https://img3.doubanio.com/view/photo/m_ratio_poster/"),
    "douban-groups": ("douban-groups.html", 3, "https://www.douban.com/group/topic/506267390/",
                      "巴东东瀼（四声rang)口镇:长江沿岸一个种满柑橘，五颜六色，山明水秀的乡镇", "https://img9.doubanio.com/"),
    "csdn-hot": ("csdn-hot.json", 3, "https://blog.csdn.net/2402_87731470/article/details/171112653",
                 "【Linux网络】HTTP 请求到底长什么样？从 URL、请求响应报文到 Web 服务器完整实战", "https://i-blog.csdnimg.cn/"),
    "lemmy-hot": ("lemmy-hot.json", 3, "https://lemmy.world/post/54765362", "Alternative Facts",
                  "https://lemmy.world/pictrs/"),
    "tumblr-trending": ("tumblr-trending.html", 2,
                        "https://www.tumblr.com/furryprovocateur/833858511274442752/how-it-feels-to-get-mad-at-dumb-shit-on-here-now",
                        "how it feels to get mad at dumb shit on here now", "https://64.media.tumblr.com/"),
    "goodreads-new": ("goodreads-new.html", 3, "https://www.goodreads.com/book/show/251612960-peculiar-stars",
                      "Peculiar Stars", "https://m.media-amazon.com/"),
    "weread-rising": ("weread-rising.json", 3, "https://weread.qq.com/web/bookDetail/dc032330813abc48dg0134a9",
                      "我在电诈园区当卧底", "https://cdn.weread.qq.com/"),
    "webtoon-popular": ("webtoon-popular.html", 2, "https://www.webtoons.com/en/fantasy/osora/list?title_no=6202",
                        "Osora", "https://webtoon-phinf.pstatic.net/"),
    "naver-webtoon": ("naver-webtoon.json", 2, "https://comic.naver.com/webtoon/list?titleId=821597", "괴력 난신",
                      "https://image-comic.pstatic.net/"),
    "mal-airing": ("mal-airing.html", 2, "https://myanimelist.net/anime/61469/Steel_Ball_Run__JoJo_no_Kimyou_na_Bouken",
                   "Steel Ball Run: JoJo no Kimyou na Bouken", "https://cdn.myanimelist.net/images/anime/"),
    "qqmusic-hot": ("qqmusic-hot.json", 3, "https://y.qq.com/n/ryqq/albumDetail/003CuoS534m1aY", "慌啥子嘛 (赵本山版)",
                    "https://y.gtimg.cn/music/photo_new/"),
    "apple-podcasts-us": ("apple-podcasts.json", 3, "https://podcasts.apple.com/us/podcast/the-daily/id1200361736",
                          "The Daily", "https://is1-ssl.mzstatic.com/"),
    "apple-music-cn": ("apple-music.json", 3, "https://music.apple.com/cn/album/%E6%88%91%E4%B8%8D%E9%9A%BE%E8%BF%87/255920420?i=255921025",
                       "我不难过", "https://is1-ssl.mzstatic.com/"),
}


def _read(key: str, sample: str | None = None) -> list[base.Find]:
    body = (SAMPLES / (sample or EXPECTED[key][0])).read_bytes()
    source = next(s for s in social.SOURCES if s.key == key)

    async def run() -> list[base.Find]:
        async with base.client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as http:
            return await source.fetch(http)
    return asyncio.run(run())


def test_every_source_here_is_in_the_catalogue_once_with_its_names_group_and_language() -> None:
    keys = [s.key for s in social.SOURCES]
    assert len(keys) == len(set(keys))
    assert set(EXPECTED) <= set(keys) and set(keys) <= set(catalog.all_sources([]))
    assert all(s.group in base.GROUPS and s.lang and s.name[1] and s.about[1] for s in social.SOURCES)


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_a_recorded_answer_is_read_into_finds_with_title_link_and_cover(key: str) -> None:
    _, count, link, title, cover = EXPECTED[key]
    found = _read(key)
    assert len(found) == count <= base.PER_SOURCE
    first = found[0]
    assert (first.item.url, first.item.title) == (link, title)
    assert first.picture.startswith(cover)
    assert all(f.item.url.startswith("https://") and f.item.title for f in found)


def test_a_repository_carries_its_line_language_and_stars_of_the_day() -> None:
    first = _read("github-trending")[1].item
    assert first.description == "An agentic skills framework & software development methodology that works. ｜ Shell ｜ 838 stars today"


def test_only_the_films_in_cinemas_are_read_the_most_wanted_first() -> None:
    films = _read("douban-nowplaying")
    assert "即将上映" not in "".join(f.item.description for f in films)
    assert all(f.item.url != "https://movie.douban.com/subject/3001114/" for f in films)
    assert [f.item.title for f in films] == ["饥饿游戏：收获日出", "珠穆朗玛：云中彼岸", "试探"]
    assert films[0].item.description.startswith("豆瓣 6.3 ｜ 美国 ｜ 159分钟")


def test_a_group_topic_keeps_its_group_and_likes_and_loses_its_tracking_query() -> None:
    topic = _read("douban-groups")[0].item
    assert (topic.description, topic.kind) == ("村庄爱好者小组 ｜ 86 人喜欢", "post")
    assert "?" not in topic.url


def test_a_tumblr_post_with_no_words_is_left_out() -> None:
    assert [f.item.author for f in _read("tumblr-trending")] == ["furryprovocateur", "feefal"]


def test_a_comic_for_adults_is_left_out_of_both_webtoon_lists() -> None:
    assert [f.item.title for f in _read("webtoon-popular")] == ["Osora", "Superfish"]
    # Of the four recorded Naver titles the third is adult and the fourth is on a break.
    assert len(_read("naver-webtoon")) == 2


def test_a_weread_book_is_linked_by_the_hash_its_deep_link_carries() -> None:
    book = _read("weread-rising")[1].item
    assert book.url == "https://weread.qq.com/web/bookDetail/249328c0813abc48cg014adb"
    assert book.author == "李娟"


def test_an_anime_cover_is_asked_for_at_its_own_size_and_its_score_is_kept() -> None:
    first = _read("mal-airing")[0]
    assert first.picture == "https://cdn.myanimelist.net/images/anime/1065/158884.jpg"
    assert first.item.description.endswith("score 9.03")


def test_an_apple_chart_is_each_storefronts_in_its_language_with_artwork_at_card_size() -> None:
    by_key = {s.key: s for s in social.SOURCES}
    assert (by_key["apple-podcasts-tw"].lang, by_key["apple-podcasts-tw"].region) == ("zh-Hant", "TW")
    assert (by_key["apple-music-br"].lang, by_key["apple-music-br"].region) == ("pt", "BR")
    assert all(s.platform == "apple.com" for key, s in by_key.items() if key.startswith("apple-"))
    show = _read("apple-podcasts-us")[0]
    assert show.picture.endswith("/600x600bb.jpg")
    assert show.item.description == "The New York Times ｜ News"
    song = _read("apple-music-cn")[0].item
    assert song.published == "2003-01-10"


def test_a_lemmy_post_is_linked_on_the_instance_that_was_asked_and_a_marked_one_is_left_out() -> None:
    body = (SAMPLES / "lemmy-hot.json").read_text(encoding="utf-8")
    marked = body.replace('"nsfw": false', '"nsfw": true', 1)
    source = next(s for s in social.SOURCES if s.key == "lemmy-hot")

    async def run() -> list[base.Find]:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=marked.encode()))
        async with base.client(transport=transport) as http:
            return await source.fetch(http)
    assert len(asyncio.run(run())) == 2
