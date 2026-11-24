"""Douyin and TikTok: every form their links take is one video's address with its player, the person's words for
them name them, a video page gives its own facts, a feed's cards are kept as videos, and their walls are told
apart. The pages are trimmed copies of what a signed-out visitor's headless browser drew (samples/shortvideo)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mibo import crossing, platforms, players, signedread
from mibo import installed_browser as web
from mibo.library import Library
from mibo.pagefacts import facts_from
from mibo.web import gate, signin, sites
from mibo.web.read import READER

SAMPLES = Path(__file__).parent / "samples" / "shortvideo"
DY, TT = "7680171480428890495", "7681450201478892807"
DY_VIDEO, DY_PLAYER = f"https://www.douyin.com/video/{DY}", f"https://open.douyin.com/player/video?vid={DY}&autoplay=0"
TT_VIDEO, TT_PLAYER = f"https://www.tiktok.com/@homosapienstv/video/{TT}", f"https://www.tiktok.com/player/v1/{TT}"

try:
    import playwright  # noqa: F401
    DRIVER = True
except ImportError:
    DRIVER = False
needs_browser = pytest.mark.skipif(not DRIVER or web.find_browser() is None,
                                   reason="needs Playwright and an installed Chromium-family browser")


@pytest.mark.parametrize(("link", "one", "player"), [
    (DY_VIDEO, DY_VIDEO, DY_PLAYER),
    (f"https://www.douyin.com/video/{DY}?previous_page=app_code_link", DY_VIDEO, DY_PLAYER),
    (f"https://www.douyin.com/?modal_id={DY}", DY_VIDEO, DY_PLAYER),
    (f"https://www.douyin.com/jingxuan?modal_id={DY}", DY_VIDEO, DY_PLAYER),
    (f"https://www.douyin.com/user/MS4wLjABAAAA?from_tab_name=main&modal_id={DY}", DY_VIDEO, DY_PLAYER),
    (f"https://www.douyin.com/note/{DY}", f"https://www.douyin.com/note/{DY}", ""),
    (f"https://www.iesdouyin.com/share/video/{DY}/?region=CN&mid=1", DY_VIDEO, DY_PLAYER),
    (f"https://www.iesdouyin.com/share/note/{DY}/", f"https://www.douyin.com/note/{DY}", ""),
    (f"https://m.douyin.com/share/video/{DY}", DY_VIDEO, DY_PLAYER),
    (TT_VIDEO, TT_VIDEO, TT_PLAYER),
    (f"{TT_VIDEO}?is_from_webapp=1&sender_device=pc", TT_VIDEO, TT_PLAYER),
    (f"https://m.tiktok.com/@homosapienstv/video/{TT}", TT_VIDEO, TT_PLAYER),
    (f"https://www.tiktok.com/@a.b_c/photo/{TT}", f"https://www.tiktok.com/@a.b_c/photo/{TT}", ""),
    (f"https://m.tiktok.com/v/{TT}.html", f"https://www.tiktok.com/@/video/{TT}", TT_PLAYER),
    (f"https://www.tiktok.com/embed/v2/{TT}", f"https://www.tiktok.com/@/video/{TT}", TT_PLAYER),
])
def test_every_form_of_a_link_is_one_address_with_its_player(link, one, player):
    key = "douyin.com" if "douyin" in link else "tiktok.com"
    assert players.canonical(link) == one and players.player_for(link) == player
    assert platforms.of_url(link) == sites.key_of(link) == key
    assert players.allowed(player) == player


@pytest.mark.parametrize("link", ["https://v.douyin.com/iRNBho6u/", "https://vm.tiktok.com/ZMh3abcde/",
                                  "https://vt.tiktok.com/ZSabcdefg/", "https://www.tiktok.com/t/ZTabcdefg/"])
def test_a_short_link_is_the_platform_and_read_where_it_redirects(link):
    # Its id is the redirect's, never guessed: no address of its own and no player until a read follows it.
    assert players.canonical(link) == players.player_for(link) == ""
    assert platforms.of_url(link) == sites.key_of(link) in ("douyin.com", "tiktok.com")


@pytest.mark.parametrize("link", [f"https://douyin.com.evil.example/video/{DY}", f"https://www.notdouyin.com/video/{DY}",
                                  f"https://notiktok.com/@a/video/{TT}", f"https://tiktok.com.evil.example/@a/video/{TT}",
                                  f"https://www.douyin.example/video/{DY}"])
def test_a_look_alike_host_is_neither(link):
    assert players.canonical(link) == players.player_for(link) == platforms.of_url(link) == ""
    assert not crossing.named(sites.key_of(link) or "x.example", "在抖音上点个赞 tiktok", site=True)


@pytest.mark.parametrize(("site", "said"), [
    ("douyin.com", "去抖音找点好玩的"), ("douyin.com", "open douyin"), ("douyin.com", "Douyin 上那个视频点个赞"),
    ("douyin.com", "抖音网页版登录一下"), ("www.iesdouyin.com", "抖音"), ("tiktok.com", "TikTok 上关注她"),
    ("tiktok.com", "tiktok"), ("tiktok.com", "用国际版抖音搜一下"), ("www.tiktok.com", "TIKTOK")])
def test_the_persons_words_name_the_platform(site, said):
    assert crossing.named(site, said, site=True)


def test_the_other_platform_is_not_named():
    assert not crossing.named("tiktok.com", "去抖音找点好玩的", site=True)
    assert not crossing.named("douyin.com", "TikTok 上关注她", site=True)


def _sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def test_a_douyin_video_page_gives_its_caption_author_cover_and_player():
    page = _sample("douyin-video.json")
    facts = facts_from(page["data"], page["url"])
    # The document's title without "- 抖音"; the author from its breadcrumb; the cover from its Lark preview meta.
    assert facts["title"] == "韩国🇰🇷便利店🏪沉浸式体验 #便利店 #冰杯 #韩国美食 #便利店美食 #马克定食"
    assert (facts["author"], facts["site"], facts["kind"], facts["embed"]) == ("Jonice111", "抖音", "video", DY_PLAYER)
    assert facts["picture"].startswith("https://p3-pc-sign.douyinpic.com/image-cut-tos-priv/77e7dc43b9e6419fefea339fba619ee4")
    # Opened as a modal over 精选, the same video and player.
    over = facts_from(page["data"], f"https://www.douyin.com/jingxuan?modal_id={DY}")
    assert (over["embed"], over["author"]) == (DY_PLAYER, "Jonice111")


def test_a_tiktok_video_page_gives_its_caption_not_its_byline():
    page = _sample("tiktok-video.json")
    facts = facts_from(page["data"], page["url"])
    # og:title is "homosapiens on TikTok": who posted it; the caption is the description.
    assert facts["title"].startswith("¿Por qué las gallinas comen piedras a veces?")
    assert (facts["author"], facts["site"], facts["kind"], facts["embed"]) == ("homosapiens", "TikTok", "video", TT_PLAYER)


def _read(name: str) -> tuple[dict, dict]:
    """reader.js's answer and signin's look at a saved page, in the headless browser with every request refused."""
    from playwright.async_api import async_playwright

    async def go() -> tuple[dict, dict]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=str(web.find_browser()), headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                await page.route("**/*", lambda route: route.abort())
                await page.set_content((SAMPLES / name).read_text(encoding="utf-8"))
                return await page.evaluate(READER, {}), await page.evaluate(signin.CHECK_JS, {})
            finally:
                await browser.close()
    return asyncio.run(go())


@needs_browser
def test_a_douyin_feed_is_kept_as_videos_at_their_own_addresses(tmp_path, monkeypatch):
    from mibo.sources import catalog
    covers = []

    async def cover(http, address, referer):
        covers.append(address)
        return b"\xff\xd8 cover"
    monkeypatch.setattr(catalog, "_cover", cover)
    data, _ = _read("douyin-jingxuan.html")
    assert data["kind"] == "list" and not data["wall"]["kind"]
    runtime = tmp_path / "runtime"
    assert signedread.keep_finds(runtime, "douyin.com", data["rows"]) == 5
    kept = {item.url: item for item in Library(runtime).items()}
    first = kept[DY_VIDEO]
    assert first.title == "韩国🇰🇷便利店🏪沉浸式体验 #便利店 #冰杯 #韩国美食 #便利店美食 #马克定食"
    assert (first.author, first.kind, first.embed, first.site) == ("Jonice111", "video", DY_PLAYER, "抖音")
    # The card linked as a modal over 精选 is kept at its video's address.
    assert kept["https://www.douyin.com/video/7688942545711222025"].embed.endswith("vid=7688942545711222025&autoplay=0")
    assert all(item.picture for item in kept.values()) and len(covers) == 5
    assert all(c.startswith("https://p3-pc-sign.douyinpic.com/") for c in covers)


@needs_browser
def test_a_tiktok_feed_keeps_each_caption_without_the_sound_line(tmp_path, monkeypatch):
    from mibo.sources import catalog

    async def cover(http, address, referer):
        return b""
    monkeypatch.setattr(catalog, "_cover", cover)
    data, _ = _read("tiktok-explore.html")
    rows = [*data["rows"], {"title": "JENNIE", "link": "https://www.tiktok.com/@jennierubyjane"}]
    runtime = tmp_path / "runtime"
    # The profile row is no video of TikTok's: left.
    assert signedread.keep_finds(runtime, "tiktok.com", rows) == 6
    kept = {item.url: item for item in Library(runtime).items()}
    first = kept[TT_VIDEO]
    assert first.title == "¿Por qué las gallinas comen piedras a veces? 🤔 #SabiasQue #homosapienstv #aprendeentiktok #cienciaentiktok"
    assert (first.author, first.kind, first.embed, first.site) == ("homosapiens", "video", TT_PLAYER, "TikTok")
    # A video with no caption goes by who posted it.
    assert kept["https://www.tiktok.com/@jeff_funnyguy_/video/7709593292475813141"].title == "Jeff"
    assert not any("created by" in item.title for item in kept.values())


@needs_browser
def test_douyins_sign_in_box_is_no_check_and_its_check_is_one():
    data, check = _read("douyin-search-signin.html")
    # Its 验证码 is the code it texts to the phone number: a sign-in, the person's.
    assert data["wall"]["kind"] == "sign_in_overlay" and check["kind"] != "verification" and check["form"]
    data, check = _read("douyin-check.html")
    assert data["wall"]["kind"] == "verification" == check["kind"]


@needs_browser
def test_tiktoks_login_box_is_a_sign_in_layer():
    data, check = _read("tiktok-login-box.html")
    assert data["wall"]["kind"] == "sign_in_overlay" == check["kind"]


def test_their_icon_buttons_read_as_likes_by_count_and_test_id():
    # Douyin's like: only a count for a name, its test id says digg; TikTok's follow: a plus with feed-follow.
    assert gate.classify("click", "1.2万", "generic", {"classes": "wn9Oh5bX video-player-digg"})[0] == "like"
    assert gate.classify("click", "11.8K", "button", {"classes": "css-x like-icon"})[0] == "like"
    assert gate.classify("click", "", "button", {"classes": "css-co7ut0 feed-follow", "iconOnly": True})[0] == "like"
    assert gate.classify("click", "1.2万", "generic", {"classes": "wn9Oh5bX"})[0] == ""
