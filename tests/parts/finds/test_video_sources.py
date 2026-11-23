"""The video platforms' sources: each reads a recorded, trimmed answer of its list page or API
into finds with a real title, the video's own page, a cover and the platform it belongs to,
and leaves out what a plain visitor should not be shown (paid, adult, locked, a series page)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from mibo.sources import base, catalog, video

SAMPLES = Path(__file__).resolve().parent / "samples" / "video"

# key: (sample, finds read, first link, first title, the first cover starts with)
EXPECTED = {
    "tencent-video": ("tencent-video.html", 2, "https://v.qq.com/x/cover/mzc00200u6gslvo.html",
                      "斗破苍穹剧场版 双帝之战", "https://tv.puui.qpic.cn/"),
    "iqiyi": ("iqiyi.json", 8, "https://www.iqiyi.com/v_1ewmjgivkm4.html", "两京十五日", "https://pic9.iqiyipic.com/"),
    "youku": ("youku.html", 2, "https://v.youku.com/video?s=aedc393daa324207acea", "谷雨",
              "https://liangcang-material.alicdn.com/"),
    "mgtv": ("mgtv.json", 8, "https://www.mgtv.com/h/919355.html", "天命·成凰", "https://0img.hitv.com/"),
    "cctv-video": ("cctv-video.html", 2, "https://tv.cctv.com/2026/11/22/VIDE5Y3J76m6SvO8vUIK2W2H261122.shtml",
                   "刻在石头上的官方“教科书”", "https://p4.img.cctvpic.com/"),
    "pearvideo": ("pearvideo.html", 2, "https://www.pearvideo.com/video_1808276", "内蒙古一救助站给狼群加餐牛肉",
                  "https://image.pearvideo.com/"),
    "douyu-live": ("douyu-live.html", 2, "https://www.douyu.com/508606", "在微盟上班开心的第一天！",
                   "https://rpic.douyucdn.cn/"),
    "bilibili-live": ("bilibili-live.json", 2, "https://live.bilibili.com/23929781", "我 吃 好 了", "https://i0.hdslb.com/"),
    "niconico-ranking": ("niconico-ranking.html", 2, "https://www.nicovideo.jp/watch/sm47076801",
                         "紲星あかりとお金を破壊する謎のインクリメンタルゲーム【What the Buck?!】",
                         "https://img.cdn.nimg.jp/"),
    "chzzk-live": ("chzzk-live.json", 2, "https://chzzk.naver.com/live/75cbf189b3bb8f9f687d2aca0d0a382b",
                   "[2026 치지직컵] 팀 BNG 서폿 풀리그 2일차", "https://livecloud-thumb.akamaized.net/"),
    "soop-live": ("soop-live.json", 2, "https://play.sooplive.co.kr/khm11903/298811773",
                  "봉준x애디 롤 멸망전 스크림 해보고 정합니다 LOL 진짜로", "https://liveimg.sooplive.com/"),
    "rutube-popular": ("rutube-popular.json", 3, "https://rutube.ru/video/29e43266fe0549ff64655d573ac62096/",
                       "Стив Роджерс - это Локи? Загадки новых кадров Судного Дня!", "https://pic.rtbcdn.ru/"),
    "ted-talks": ("ted-talks.html", 2, "https://www.ted.com/talks/li_hongyi_why_government_is_slow_and_how_to_fix_it",
                  "Why government is slow — and how to fix it", "https://pi.tedcdn.com/"),
    "odysee-trending": ("odysee-trending.json", 2,
                        "https://odysee.com/@KBMyFunnyCats:8/Funny-Cats-Go-Shopping:daf81ca162eee5b1d390812a6f15eda92746d010",
                        "Funny Cats Go Shopping 😂 | Cat Comedy", "https://thumbs.odycdn.com/"),
    "peertube-trending": ("peertube-trending.json", 2,
                          "https://tilvids.com/videos/watch/75458950-1377-42fb-be1c-34a2c5b9f98c",
                          "Proton goes A.I. crazy, Ubuntu goes all SNAP, Vibe-coded Linux compatible kernel - Linux Weekly News",
                          "https://tilvids.com/"),
    "francetv": ("francetv.html", 2, "https://www.france.tv/france-2/disparition-inquietante/9028087-au-nom-du-pere.html",
                 "S1 E8 - Au Nom du Père", "https://medias.france.tv/"),
    "ard-mediathek": ("ard-mediathek.html", 2,
                      "https://www.ardmediathek.de/video/Y3JpZDovL3dkci5kZS9CZWl0cmFnLXNvcGhvcmEtOWE3MzJmMDktMDViYi00ZWU1LWFmMWUtNDc0MmJmODY1NTg3",
                      "Krieg im Weltraum · Wie verwundbar ist Deutschland?", "https://api.ardmediathek.de/"),
    "rtve-play": ("rtve-play.html", 2, "https://www.rtve.es/play/videos/somos-cine/colon-adn-verdadero-origen/16281015/",
                  "Colón ADN. Su verdadero origen", "https://img.rtve.es/"),
}


def _read(key: str) -> list[base.Find]:
    body = (SAMPLES / EXPECTED[key][0]).read_bytes()
    source = next(s for s in video.SOURCES if s.key == key)

    async def run() -> list[base.Find]:
        async with base.client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as http:
            return await source.fetch(http)
    return asyncio.run(run())


def test_every_source_here_is_in_the_catalogue_as_a_video_source_of_a_platform() -> None:
    keys = [s.key for s in video.SOURCES]
    assert len(keys) == len(set(keys)) == len(EXPECTED)
    assert all(s.group == "video" and s.platform and s.lang and s.name[1] and s.about[1] for s in video.SOURCES)
    assert set(keys) <= set(catalog.all_sources([]))


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_a_recorded_answer_is_read_into_finds_with_title_link_cover_and_platform(key: str) -> None:
    _, count, link, title, cover = EXPECTED[key]
    found = _read(key)
    assert len(found) == count <= base.PER_SOURCE
    first = found[0]
    assert first.item.url == link and first.item.title == title and first.item.kind == "video"
    assert first.picture.startswith(cover)
    assert all(f.item.title and f.item.url.startswith("https://") and f.picture for f in found)
    assert next(s for s in video.SOURCES if s.key == key).platform


def test_the_list_pages_say_more_than_a_title_where_they_can() -> None:
    iqiyi, pear, mgtv = _read("iqiyi")[0], _read("pearvideo")[0], _read("mgtv")[0]
    assert "朱瞻基" in iqiyi.item.description
    assert pear.item.author == "视听新时代" and pear.item.length == 18 and "狼" in pear.item.description
    assert mgtv.item.author.startswith("孙晨竣") and "云似" in mgtv.item.description
    ted = _read("ted-talks")[0].item
    assert ted.author == "Li Hongyi" and ted.length == 388 and ted.published == "2026-11-23T15:50:10Z"
    assert ted.description.startswith("TED2026 · government, technology")
    france, rtve = _read("francetv")[0].item, _read("rtve-play")[0].item
    assert france.length == 5526 and france.published.startswith("2026-11-23")
    assert rtve.length == 6370 and rtve.published.startswith("2026-10-09")
    assert _read("cctv-video")[0].item.published == "2026-11-22"


def test_what_a_visitor_should_not_be_shown_is_left_out() -> None:
    # The recorded answers hold a paid video, an adult stream, a locked room, a claim with no channel,
    # an adult video, a series page and a programme page beside the ones kept.
    assert [f.item.title for f in _read("niconico-ranking")] == [
        "紲星あかりとお金を破壊する謎のインクリメンタルゲーム【What the Buck?!】",
        "釣れなくても料理！タコのアヒージョ！【VOICEROIDキッチン】"]
    assert "Adult stream" not in [f.item.title for f in _read("chzzk-live")]
    assert "A locked room" not in [f.item.title for f in _read("soop-live")]
    assert "A claim with no channel" not in [f.item.title for f in _read("odysee-trending")]
    assert "Adult video" not in [f.item.title for f in _read("rutube-popular")]
    assert "A series page" not in [f.item.title for f in _read("rtve-play")]
    assert "A programme page" not in [f.item.title for f in _read("francetv")]
    assert len(_read("ard-mediathek")) == 2


def test_rutube_comes_most_watched_first_and_the_live_rooms_say_they_are_live() -> None:
    hits = [f.item.title for f in _read("rutube-popular")]
    assert hits[0].startswith("Стив Роджерс")
    for key in ("douyu-live", "bilibili-live", "chzzk-live", "soop-live"):
        about = next(s.about[0] for s in video.SOURCES if s.key == key)
        assert about.startswith("live ")


def test_a_player_comes_with_the_find_where_the_platform_has_one() -> None:
    assert _read("ted-talks")[0].item.embed == \
        "https://embed.ted.com/talks/li_hongyi_why_government_is_slow_and_how_to_fix_it"
    assert _read("odysee-trending")[0].item.embed == \
        "https://odysee.com/$/embed/Funny-Cats-Go-Shopping/daf81ca162eee5b1d390812a6f15eda92746d010"
    assert _read("niconico-ranking")[0].item.embed == "https://embed.nicovideo.jp/watch/sm47076801"
    assert _read("rutube-popular")[0].item.embed.startswith("https://rutube.ru/play/embed/")
    assert _read("iqiyi")[0].item.embed == ""
