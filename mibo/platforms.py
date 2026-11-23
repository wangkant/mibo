"""The mainstream platforms the app knows: video, short video, live, social, communities and the large reading and
listening platforms (not mail, shopping, banks or search engines).

A platform is named by its registrable host, the key web/seeds.json and web/signin_sites.json use for it
("bilibili.com"; Tencent Video is "qq.com", which WeRead, QQ Music and WeChat share, and seeds.json's card for it
is WeChat's). `reach` is "open" when the app reads its lists without signing in (a catalogue source carries it, or
seeds.json gives it a walkable hot list) and "signin" when its lists answer only a signed-in person. The person's
chosen platforms (feed_platforms, panels/feed.py) are a preference: the sources' prior, the first run's samples
and the walks' order. A "signin" platform's own feed is read only by its switch in Settings > Connections.

The catalogue's sources from before `Source.platform` get theirs from PREFIXES, by key.
"""
from __future__ import annotations

from typing import NamedTuple

from . import situation


class Platform(NamedTuple):
    key: str
    zh: str
    en: str
    # "video" (video, short video, live) or "social" (social, communities, reading, listening).
    kind: str
    # The language of most of it and the country it is of; "" for the whole world's.
    lang: str
    region: str
    reach: str
    # The Traditional Chinese name, where it is written otherwise.
    hant: str = ""

    def name(self, lang: str) -> str:
        """The brand as written for a reader of `lang`: in Chinese for Chinese, in Latin script otherwise."""
        if lang in ("zh-TW", "zh-Hant", "zh-HK"):
            return self.hant or self.zh
        return self.zh if str(lang).startswith("zh") else self.en


OPEN, SIGNIN = "open", "signin"

# The most used first within each language and region.
PLATFORMS = {p.key: p for p in (
    Platform("youtube.com", "YouTube", "YouTube", "video", "", "", OPEN),
    Platform("tiktok.com", "TikTok", "TikTok", "video", "", "", SIGNIN),
    Platform("instagram.com", "Instagram", "Instagram", "social", "", "", SIGNIN),
    Platform("facebook.com", "Facebook", "Facebook", "social", "", "", SIGNIN),
    Platform("x.com", "X", "X", "social", "", "", SIGNIN),
    Platform("reddit.com", "Reddit", "Reddit", "social", "en", "", SIGNIN),
    Platform("pinterest.com", "Pinterest", "Pinterest", "social", "", "", SIGNIN),
    Platform("linkedin.com", "领英", "LinkedIn", "social", "", "", SIGNIN, "領英"),
    Platform("snapchat.com", "Snapchat", "Snapchat", "video", "", "", SIGNIN),
    Platform("threads.com", "Threads", "Threads", "social", "", "", SIGNIN),
    Platform("spotify.com", "Spotify", "Spotify", "social", "", "", SIGNIN),
    Platform("quora.com", "Quora", "Quora", "social", "en", "", SIGNIN),
    Platform("twitch.tv", "Twitch", "Twitch", "video", "", "", OPEN),
    Platform("wikipedia.org", "维基百科", "Wikipedia", "social", "", "", OPEN, "維基百科"),
    Platform("github.com", "GitHub", "GitHub", "social", "", "", OPEN),
    Platform("stackoverflow.com", "Stack Overflow", "Stack Overflow", "social", "en", "", OPEN),
    Platform("medium.com", "Medium", "Medium", "social", "en", "", OPEN),
    Platform("tumblr.com", "Tumblr", "Tumblr", "social", "en", "", OPEN),
    Platform("steampowered.com", "Steam", "Steam", "social", "", "", OPEN),
    Platform("ted.com", "TED", "TED", "video", "en", "", OPEN),
    Platform("ycombinator.com", "Hacker News", "Hacker News", "social", "en", "", OPEN),
    Platform("producthunt.com", "Product Hunt", "Product Hunt", "social", "en", "", OPEN),
    Platform("huggingface.co", "Hugging Face", "Hugging Face", "social", "en", "", OPEN),
    Platform("dev.to", "DEV", "DEV", "social", "en", "", OPEN),
    Platform("bsky.app", "Bluesky", "Bluesky", "social", "en", "", OPEN),
    Platform("mastodon.social", "Mastodon", "Mastodon", "social", "en", "", OPEN),
    Platform("itch.io", "itch.io", "itch.io", "social", "en", "", OPEN),
    Platform("anilist.co", "AniList", "AniList", "social", "en", "", OPEN),
    Platform("apple.com", "Apple 音乐与播客", "Apple Music & Podcasts", "social", "", "", OPEN, "Apple 音樂與播客"),
    Platform("webtoons.com", "WEBTOON", "WEBTOON", "social", "", "", OPEN),
    Platform("goodreads.com", "Goodreads", "Goodreads", "social", "en", "", OPEN),
    Platform("myanimelist.net", "MyAnimeList", "MyAnimeList", "social", "en", "", OPEN),
    Platform("lemmy.world", "Lemmy", "Lemmy", "social", "en", "", OPEN),
    Platform("odysee.com", "Odysee", "Odysee", "video", "en", "", OPEN),
    Platform("sepiasearch.org", "PeerTube", "PeerTube", "video", "", "", OPEN),
    # Chinese, mainland.
    Platform("douyin.com", "抖音", "Douyin", "video", "zh", "CN", SIGNIN),
    Platform("bilibili.com", "哔哩哔哩", "Bilibili", "video", "zh", "CN", OPEN, "嗶哩嗶哩"),
    Platform("kuaishou.com", "快手", "Kuaishou", "video", "zh", "CN", SIGNIN),
    Platform("weibo.com", "微博", "Weibo", "social", "zh", "CN", SIGNIN),
    Platform("xiaohongshu.com", "小红书", "Xiaohongshu", "social", "zh", "CN", SIGNIN, "小紅書"),
    Platform("qq.com", "腾讯视频", "Tencent Video", "video", "zh", "CN", OPEN, "騰訊視頻"),
    Platform("iqiyi.com", "爱奇艺", "iQIYI", "video", "zh", "CN", OPEN, "愛奇藝"),
    Platform("youku.com", "优酷", "Youku", "video", "zh", "CN", OPEN, "優酷"),
    Platform("zhihu.com", "知乎", "Zhihu", "social", "zh", "CN", OPEN),
    Platform("toutiao.com", "今日头条", "Toutiao", "social", "zh", "CN", OPEN, "今日頭條"),
    Platform("baidu.com", "百度贴吧", "Baidu Tieba", "social", "zh", "CN", OPEN, "百度貼吧"),
    Platform("163.com", "网易云音乐", "NetEase Cloud Music", "social", "zh", "CN", OPEN, "網易雲音樂"),
    Platform("mgtv.com", "芒果 TV", "Mango TV", "video", "zh", "CN", OPEN),
    Platform("cctv.com", "央视网", "CCTV", "video", "zh", "CN", OPEN, "央視網"),
    Platform("douban.com", "豆瓣", "Douban", "social", "zh", "CN", OPEN),
    Platform("douyu.com", "斗鱼", "Douyu", "video", "zh", "CN", OPEN, "鬥魚"),
    Platform("acfun.cn", "AcFun", "AcFun", "video", "zh", "CN", OPEN),
    Platform("okjike.com", "即刻", "Jike", "social", "zh", "CN", SIGNIN),
    Platform("pearvideo.com", "梨视频", "Pear Video", "video", "zh", "CN", OPEN, "梨視頻"),
    Platform("juejin.cn", "稀土掘金", "Juejin", "social", "zh", "CN", OPEN),
    Platform("csdn.net", "CSDN", "CSDN", "social", "zh", "CN", OPEN),
    Platform("v2ex.com", "V2EX", "V2EX", "social", "zh", "CN", OPEN),
    Platform("jjwxc.net", "晋江文学城", "Jinjiang Literature City", "social", "zh", "CN", OPEN, "晉江文學城"),
    Platform("bgm.tv", "Bangumi 番组计划", "Bangumi", "social", "zh", "CN", OPEN, "Bangumi 番組計劃"),
    # Chinese, Taiwan.
    Platform("ptt.cc", "PTT", "PTT", "social", "zh-Hant", "TW", OPEN),
    Platform("gamer.com.tw", "巴哈姆特", "Bahamut", "social", "zh-Hant", "TW", OPEN),
    # Japanese.
    Platform("nicovideo.jp", "Niconico", "Niconico", "video", "ja", "JP", OPEN),
    Platform("hatena.ne.jp", "Hatena", "Hatena", "social", "ja", "JP", OPEN),
    Platform("qiita.com", "Qiita", "Qiita", "social", "ja", "JP", OPEN),
    Platform("zenn.dev", "Zenn", "Zenn", "social", "ja", "JP", OPEN),
    # Korean: CHZZK is Naver's, on chzzk.naver.com.
    Platform("naver.com", "CHZZK", "CHZZK", "video", "ko", "KR", OPEN),
    Platform("sooplive.co.kr", "SOOP", "SOOP", "video", "ko", "KR", OPEN),
    # Russian, French, German, Spanish.
    Platform("rutube.ru", "Rutube", "Rutube", "video", "ru", "RU", OPEN),
    Platform("habr.com", "Habr", "Habr", "social", "ru", "RU", OPEN),
    Platform("france.tv", "France.tv", "France.tv", "video", "fr", "FR", OPEN),
    Platform("ardmediathek.de", "ARD Mediathek", "ARD Mediathek", "video", "de", "DE", OPEN),
    Platform("rtve.es", "RTVE Play", "RTVE Play", "video", "es", "ES", OPEN),
    Platform("meneame.net", "Menéame", "Menéame", "social", "es", "ES", OPEN),
)}

# The platform of each catalogue source from before `Source.platform`, by the start of its key.
PREFIXES = {
    "bili-": "bilibili.com", "bilibili-": "bilibili.com", "acfun-": "acfun.cn", "youtube-": "youtube.com",
    "zhihu-": "zhihu.com", "tieba-": "baidu.com", "douban-": "douban.com", "v2ex-": "v2ex.com",
    "toutiao-": "toutiao.com", "netease-": "163.com", "juejin-": "juejin.cn", "jjwxc-": "jjwxc.net",
    "bangumi-": "bgm.tv", "hn-": "ycombinator.com", "so-": "stackoverflow.com", "ph-": "producthunt.com",
    "hf-": "huggingface.co", "devto-": "dev.to", "mastodon-": "mastodon.social", "bluesky-": "bsky.app",
    "medium-": "medium.com", "steam-": "steampowered.com", "itch-": "itch.io", "anilist-": "anilist.co",
    "wiki-": "wikipedia.org", "hatena-": "hatena.ne.jp", "qiita-": "qiita.com", "zenn": "zenn.dev",
    "gnn-": "gamer.com.tw", "habr": "habr.com", "meneame": "meneame.net",
}


def known(key: str) -> bool:
    return key in PLATFORMS


def of_source(key: str) -> str:
    """The platform a catalogue source's key names by PREFIXES, or ""."""
    return next((platform for prefix, platform in PREFIXES.items() if key.startswith(prefix)), "")


def of_url(url: str) -> str:
    """The platform an address is on, or ""."""
    key = situation.site_of(url)
    return key if key in PLATFORMS else ""


def offered(langs: list[str], region: str = "") -> list[Platform]:
    """The platforms for a reader of `langs` (their own language first) in `region`: those of their region,
    then of their own language, then the whole world's and those of the other languages they read, each the
    most used first; none of a language they do not read nor of their region."""
    reads = [situation.primary(code) for code in langs]

    def tier(p: Platform) -> int:
        return 0 if region and p.region == region else 1 if p.lang and situation.primary(p.lang) == reads[0] else 2

    shown = [p for p in PLATFORMS.values()
             if not p.lang or situation.primary(p.lang) in reads or (region and p.region == region)]
    return sorted(shown, key=tier)
