"""The platforms the app knows (mibo/platforms.py): one key per platform shared with the walks' seeds and the
sign-in hints, every source of the catalogue on a known platform, a platform read without signing in only where a
source or a walkable hot list reads it, and a reader's own platforms offered first."""
from __future__ import annotations

import json
from pathlib import Path

from mibo import platforms, situation
from mibo.sources import catalog

WEB = Path(platforms.__file__).with_name("web")
SEEDS = json.loads((WEB / "seeds.json").read_text(encoding="utf-8"))["hosts"]
HINTS = json.loads((WEB / "signin_sites.json").read_text(encoding="utf-8"))["sites"]


def test_a_platform_is_named_by_its_registrable_host_as_the_seeds_and_the_sign_in_hints_name_it():
    for key, platform in platforms.PLATFORMS.items():
        assert platform.key == key and situation.site_of(f"https://www.{key}/") == key, key
        assert platform.kind in ("video", "social") and platform.reach in (platforms.OPEN, platforms.SIGNIN), key
    hinted = {row["site"] for row in HINTS if not row.get("mail")}
    assert {"douyin.com", "xiaohongshu.com", "bilibili.com", "tiktok.com", "x.com"} <= hinted & set(platforms.PLATFORMS)
    assert {"douyin.com", "kuaishou.com", "weibo.com", "instagram.com"} <= SEEDS.keys() & set(platforms.PLATFORMS)


def test_every_source_is_on_a_known_platform_and_an_open_platform_is_read_without_signing_in():
    sources = catalog.all_sources([])
    carried = {source.platform for source in sources.values() if source.platform}
    assert [key for key in carried if not platforms.known(key)] == []
    assert sources["bili-hot"].platform == "bilibili.com" and sources["youtube-science"].platform == "youtube.com"
    assert sources["tieba-hot"].platform == "baidu.com" and sources["bbc-world"].platform == ""
    walked = {key for key, seed in SEEDS.items() if seed.get("walk", True) and seed.get("hot")}
    assert [p.key for p in platforms.PLATFORMS.values() if p.reach == platforms.OPEN
            and p.key not in carried | walked] == []


def test_a_reader_is_offered_their_regions_and_languages_platforms_first_and_none_they_cannot_read():
    zh = [p.key for p in platforms.offered(["zh", "en"], "CN")]
    assert zh.index("douyin.com") < zh.index("youtube.com") and zh.index("bilibili.com") < zh.index("reddit.com")
    assert "nicovideo.jp" not in zh and "rtve.es" not in zh
    ja = [p.key for p in platforms.offered(["ja"], "JP")]
    assert ja[0] == "nicovideo.jp" and "reddit.com" not in ja and "youtube.com" in ja
    assert platforms.PLATFORMS["bilibili.com"].name("zh-TW") == "嗶哩嗶哩"
    assert platforms.PLATFORMS["bilibili.com"].name("de") == "Bilibili"
    assert platforms.of_url("https://v.qq.com/x/cover/abc.html") == "qq.com" and platforms.of_url("https://evil.example/") == ""
