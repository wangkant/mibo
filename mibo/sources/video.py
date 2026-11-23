"""Video platforms beyond YouTube and Bilibili: long-video sites, TV catch-up services, live-stream
directories and open video networks, in Chinese and in six other languages.

Each is read the way its own list page reads itself: a JSON the page loads, the JSON it carries
inline, or its server-rendered rows. Every address answers a plain visitor without a key, a sign-in
or a cookie and is one robots.txt allows (checked 2026-11-23). Douyin, Kuaishou, Xiaohongshu,
Weibo, Haokan, Huya, Vimeo and Dailymotion are not here: they answer only a signed-in person or
their robots.txt turns programs away; their lists come through the person's own browser instead.
A long-video site's items are shows and films; a live directory's are rooms on air now.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
from itertools import zip_longest
from urllib.parse import quote

import httpx

from .base import PER_SOURCE, Find, Source, find, get_json, get_text, plain
from .china import _https

_ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


def _seconds(iso: str) -> int | None:
    """A duration written PT1H32M36.5S, in whole seconds."""
    match = _ISO_DURATION.fullmatch(iso or "")
    if not match:
        return None
    hours, minutes, seconds = (float(g or 0) for g in match.groups())
    return int(hours * 3600 + minutes * 60 + seconds) or None


def _mixed(answers: list) -> list[Find]:
    """Lists fetched side by side, taken in turn so one does not fill the round; a failed one is skipped,
    all failing raises the first error."""
    lists = [a for a in answers if isinstance(a, list)]
    if not lists:
        raise answers[0]
    return [f for row in zip_longest(*lists) for f in row if f is not None][:PER_SOURCE]


def _js(raw: str) -> str:
    """A JS string literal's text as it reads."""
    return json.loads(f'"{raw}"')


# ---------------------------------------------------------------- Chinese long video

_QQ = re.compile(r'cid:"(\w{15})",title:"[^"]*",curl:"",coverPic:"([^"]+)",smallCoverPic:"([^"]*)"'
                 r'.{0,1500}?topicLabel:"([^"]*)".{0,600}?mzTitle:"([^"]+)".{0,200}?subTitle:"([^"]*)"', re.S)


async def _tencent(http: httpx.AsyncClient) -> list[Find]:
    # The shows the home page recommends, as the inline objects its player rail is made from.
    page = await get_text(http, "https://v.qq.com/")
    found, seen = [], set()
    for cid, big, small, label, title, line in _QQ.findall(page):
        if cid not in seen:
            seen.add(cid)
            found.append(find(f"https://v.qq.com/x/cover/{cid}.html", title, site="腾讯视频", kind="video",
                              text=f"{line} {label}", picture=_https(small or big)))
    return found[:PER_SOURCE]


# The channel ids of iQiyi's own list pages: series, film, anime, variety.
_IQIYI_CHANNELS = (2, 1, 4, 6)


async def _iqiyi_channel(http: httpx.AsyncClient, channel: int) -> list[Find]:
    data = await get_json(http, "https://pcw-api.iqiyi.com/search/recommend/list", channel_id=channel,
                          data_type=1, mode=11, page_id=1, ret_num=12)
    if data.get("code") != "A00000":
        raise ValueError(f"iQiyi refused the list: {data.get('code')}")
    return [find(_https(v["playUrl"]), v["name"], site="爱奇艺", kind="video", text=v.get("description", ""),
                 picture=_https(v.get("imageUrl", ""))) for v in data["data"]["list"]]


async def _iqiyi(http: httpx.AsyncClient) -> list[Find]:
    return _mixed(await asyncio.gather(*(_iqiyi_channel(http, c) for c in _IQIYI_CHANNELS), return_exceptions=True))


def _youku_shows(node, out: dict[str, dict]) -> dict[str, dict]:
    """The shows anywhere in the page's data, by id; the promoted items there are not shows."""
    if isinstance(node, dict):
        if node.get("action_type") == "JUMP_TO_SHOW" and node.get("title") and node.get("img"):
            out.setdefault(node["action_value"], node)
        for value in node.values():
            _youku_shows(value, out)
    elif isinstance(node, list):
        for value in node:
            _youku_shows(value, out)
    return out


async def _youku(http: httpx.AsyncClient) -> list[Find]:
    # The home page carries its data as one JS object, with a few bare `undefined`s.
    page = await get_text(http, "https://www.youku.com/")
    start = page.index("{", page.index("window.__INITIAL_DATA__"))
    data, _ = json.JSONDecoder().raw_decode(page[start:page.index("</script>", start)].replace(":undefined", ":null"))
    return [find(f"https://v.youku.com/video?s={show}", v["title"], site="优酷", kind="video", text=v.get("desc", ""),
                 picture=_https(v["img"])) for show, v in list(_youku_shows(data, {}).items())[:PER_SOURCE]]


# The channel ids of Mango TV's library list: series, film, variety, anime.
_MGTV_CHANNELS = (2, 3, 1, 50)


async def _mgtv_channel(http: httpx.AsyncClient, channel: int) -> list[Find]:
    # sort=c2 is the library in the order of how much it is watched.
    data = await get_json(http, "https://pianku.api.mgtv.com/rider/list/pcweb/v3", platform="pcweb",
                          channelId=channel, pn=1, pc=20, kind="a1", edition="a1", area="a1", year="all",
                          chargeInfo="a1", sort="c2", _support=10000000)
    return [find(f"https://www.mgtv.com/h/{v['clipId']}.html", v["title"], site="芒果TV", kind="video",
                 text=v.get("story", ""), author=v.get("subtitle", ""),
                 picture=_https(v.get("imgUrlH") or v.get("img", ""))) for v in data["data"]["hitDocs"]]


async def _mgtv(http: httpx.AsyncClient) -> list[Find]:
    return _mixed(await asyncio.gather(*(_mgtv_channel(http, c) for c in _MGTV_CHANNELS), return_exceptions=True))


_CCTV_LINK = re.compile(r'<a[^>]+href="(https?://tv\.cctv\.com/\d{4}/\d\d/\d\d/VIDE\w+\.shtml)"[^>]*>(.*?)</a>', re.S)
_CCTV_DAY = re.compile(r"/(\d{4})/(\d\d)/(\d\d)/")


async def _cctv(http: httpx.AsyncClient) -> list[Find]:
    # A video's cover and its title sit in two links to the same page.
    page = await get_text(http, "https://tv.cctv.com/")
    rows: dict[str, dict] = {}
    for url, inner in _CCTV_LINK.findall(page):
        row = rows.setdefault(_https(url), {"picture": "", "title": ""})
        cover = re.search(r'<img[^>]+src="([^"]+)"', inner)
        if cover and not row["picture"]:
            row["picture"] = _https(cover.group(1) if cover.group(1).startswith("http") else "https:" + cover.group(1))
        # The 完整版 badge is an <i> in the title's link.
        words = plain(re.sub(r"<i[^>]*>.*?</i>", "", inner))
        if words and not row["title"]:
            row["title"] = words
    return [find(url, row["title"], site="央视网", kind="video", picture=row["picture"],
                 published="-".join(_CCTV_DAY.search(url).groups()))
            for url, row in rows.items() if row["title"] and row["picture"]][:PER_SOURCE]


_PEAR_LINK = re.compile(r'<a href="(video_\d+)" class="popularembd')
_PEAR_TIME = re.compile(r'cm-duration">(?:(\d+):)?(\d+):(\d+)<')


async def _pearvideo(http: httpx.AsyncClient) -> list[Find]:
    # The 排行榜 page's server-rendered rows; any address with a query is off limits to programs there.
    page = await get_text(http, "https://www.pearvideo.com/popular")
    found = []
    for row in page.split('<li class="popularem')[1:]:
        link, cover = _PEAR_LINK.search(row), re.search(r"url\((https://[^)]+)\)", row)
        title = re.search(r'popularem-title">(.*?)</h2>', row, re.S)
        if not (link and cover and title):
            continue
        text, author = re.search(r"popularem-abs[^>]*>(.*?)</p>", row, re.S), re.search(r'class="column">(.*?)</a>', row)
        time = _PEAR_TIME.search(row)
        found.append(find(f"https://www.pearvideo.com/{link.group(1)}", title.group(1), site="梨视频", kind="video",
                          text=text.group(1) if text else "", author=author.group(1) if author else "",
                          picture=cover.group(1),
                          length=int(time.group(1) or 0) * 3600 + int(time.group(2)) * 60 + int(time.group(3))
                          if time else None))
    return found[:PER_SOURCE]


# ---------------------------------------------------------------- Chinese live

_DOUYU = re.compile(r'"nn":"([^"]*)","oaid":\d+,"ol":(\d+),.{0,200}?"rid":(\d+),"rn":"([^"]*)".{0,400}?"rs16":"([^"]+)"',
                    re.S)


async def _douyu(http: httpx.AsyncClient) -> list[Find]:
    # The rooms are inline JSON in the directory page; robots.txt leaves the old JSON API closed.
    page = await get_text(http, "https://www.douyu.com/directory/all")
    rooms: dict[str, tuple] = {}
    for name, heat, room, title, cover in _DOUYU.findall(page):
        rooms.setdefault(room, (_js(title), _js(name), heat, cover))
    return [find(f"https://www.douyu.com/{room}", title, site="斗鱼", kind="video", author=name, text=f"{heat} 热度",
                 picture=cover) for room, (title, name, heat, cover) in list(rooms.items())[:PER_SOURCE]]


async def _bilibili_live(http: httpx.AsyncClient) -> list[Find]:
    data = await get_json(http, "https://api.live.bilibili.com/room/v1/Area/getListByAreaID",
                          areaId=0, sort="online", pageSize=30, page=1)
    # The newer list route answers a visitor with a risk-control code, and this one may follow.
    if data.get("code") != 0:
        raise ValueError(f"Bilibili Live refused the list: {data.get('message')}")
    return [find(f"https://live.bilibili.com/{v['roomid']}", v["title"], site="哔哩哔哩直播", kind="video",
                 author=v.get("uname", ""), picture=v.get("user_cover") or v.get("cover", ""),
                 text=f"{v.get('area_v2_parent_name', '')} {v.get('area_v2_name', '')} · {v.get('online', 0)} 人在看")
            for v in data["data"]][:PER_SOURCE]


# ---------------------------------------------------------------- Japanese, Korean, Russian

async def _niconico(http: httpx.AsyncClient) -> list[Find]:
    # The day's ranking, in the page's own state; the request must look like a browser's or the page leaves it out.
    page = await get_text(http, "https://www.nicovideo.jp/ranking/genre/all", term="24h")
    state = json.loads(html.unescape(re.search(r'name="server-response" content="([^"]+)"', page).group(1)))
    items = state["data"]["response"]["$getTeibanRanking"]["data"]["items"]
    return [find(f"https://www.nicovideo.jp/watch/{v['id']}", v["title"], site="ニコニコ動画", kind="video",
                 text=v.get("shortDescription", ""), author=(v.get("owner") or {}).get("name", ""),
                 published=v.get("registeredAt", ""), picture=v["thumbnail"].get("nHdUrl") or v["thumbnail"]["largeUrl"],
                 length=v.get("duration")) for v in items if not v.get("isPaymentRequired")][:PER_SOURCE]


async def _chzzk(http: httpx.AsyncClient) -> list[Find]:
    data = await get_json(http, "https://api.chzzk.naver.com/service/v1/lives", size=PER_SOURCE * 2, sortType="POPULAR")
    return [find(f"https://chzzk.naver.com/live/{v['channel']['channelId']}", v["liveTitle"], site="CHZZK", kind="video",
                 text=v.get("liveCategoryValue") or "", author=v["channel"]["channelName"], published=v.get("openDate", ""),
                 # The cover's address holds a {type} slot for its width.
                 picture=(v.get("liveImageUrl") or "").replace("{type}", "480"))
            for v in data["content"]["data"] if not v.get("adult")][:PER_SOURCE]


async def _soop(http: httpx.AsyncClient) -> list[Find]:
    # The JSON the live page loads, though it is served as text/html. Grade 0 is open to all ages.
    data = await get_json(http, "https://live.sooplive.co.kr/api/main_broad_list_api.php", selectType="action",
                          selectValue="all", orderType="view_cnt", pageNo=1, lang="ko")
    return [find(f"https://play.sooplive.co.kr/{v['user_id']}/{v['broad_no']}", v["broad_title"], site="SOOP",
                 kind="video", author=v["user_nick"], published=v.get("broad_start", ""),
                 picture="https:" + v["broad_thumb"])
            for v in data["broad"] if v.get("broad_grade") == "0" and v.get("is_password") != "Y"][:PER_SOURCE]


async def _rutube(http: httpx.AsyncClient) -> list[Find]:
    # The top channels' recent videos from the Popular showcase; robots.txt closes any address with a query.
    data = await get_json(http, "https://rutube.ru/api/tags/video/6050/")
    top = sorted((v for v in data["results"] if not (v.get("is_adult") or v.get("is_hidden") or v.get("is_paid"))),
                 key=lambda v: v.get("hits") or 0, reverse=True)
    return [find(v["video_url"], v["title"], site="Rutube", kind="video", text=v.get("description", ""),
                 author=(v.get("author") or {}).get("name", ""), published=v.get("created_ts", ""),
                 picture=v.get("thumbnail_url", ""), length=int(v.get("duration") or 0) or None)
            for v in top][:PER_SOURCE]


# ---------------------------------------------------------------- open video and European public TV

async def _ted(http: httpx.AsyncClient) -> list[Find]:
    # The Talks page's own list, newest first, as the data it was rendered from: it has no summaries, so the event and topics stand in.
    page = await get_text(http, "https://www.ted.com/talks")
    data = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S).group(1))
    return [find(f"https://www.ted.com/talks/{t['slug']}", t["title"], site="TED", kind="video",
                 author=t.get("presenterDisplayName", ""),
                 text=" · ".join(filter(None, (t.get("videoContext"), ", ".join(n["name"] for n in t["topics"]["nodes"])))),
                 published=t.get("publishedAt", ""), length=int(t.get("duration") or 0) or None,
                 picture=t["primaryImageSet"][0]["url"])
            for t in data["props"]["pageProps"]["talks"]][:PER_SOURCE]


async def _odysee(http: httpx.AsyncClient) -> list[Find]:
    # The trending video claims, by Odysee's own search call; the link carries the whole claim id, which its player needs.
    answer = await http.post("https://api.na-backend.odysee.com/api/v1/proxy?m=claim_search", json={
        "jsonrpc": "2.0", "id": 1, "method": "claim_search",
        "params": {"page_size": 20, "order_by": ["trending_group", "trending_mixed"], "stream_types": ["video"],
                   "claim_type": ["stream"], "no_totals": True, "not_tags": ["mature"], "any_languages": ["en"]}})
    answer.raise_for_status()
    found = []
    for claim in answer.json()["result"]["items"]:
        value, channel = claim.get("value", {}), claim.get("signing_channel") or {}
        if not (value.get("title") and channel.get("canonical_url")):
            continue
        page = (f"https://odysee.com/{channel['canonical_url'].removeprefix('lbry://').replace('#', ':')}"
                f"/{quote(claim['name'], safe='')}:{claim['claim_id']}")
        found.append(find(page, value["title"], site="Odysee", kind="video", text=value.get("description", ""),
                          author=channel.get("name", ""), picture=(value.get("thumbnail") or {}).get("url", ""),
                          length=(value.get("video") or {}).get("duration")))
    return found[:PER_SOURCE]


async def _peertube(http: httpx.AsyncClient) -> list[Find]:
    # Sepia Search, Framasoft's index of the PeerTube instances: its trending English videos, each on its own instance.
    data = await get_json(http, "https://sepiasearch.org/api/v1/search/videos", sort="-trending", count=20,
                          nsfw="false", languageOneOf="en")
    return [find(v["url"], v["name"], site="PeerTube", kind="video", text=v.get("truncatedDescription", ""),
                 author=v["channel"]["displayName"], published=v.get("publishedAt", ""), length=v.get("duration"),
                 picture=v.get("thumbnailUrl", "")) for v in data["data"]][:PER_SOURCE]


async def _francetv(http: httpx.AsyncClient) -> list[Find]:
    # The home page's rails are JSON cards inside Next's streamed chunks. One request: robots.txt names AI crawlers.
    page = await get_text(http, "https://www.france.tv/")
    flight = "".join(_js(chunk) for chunk in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', page, re.S))
    cards: dict[int, dict] = {}
    for start in re.finditer(r'"content":(?=\{"id":\d+,"title":)', flight):
        card, _ = json.JSONDecoder().raw_decode(flight, start.end())
        if card.get("type") == "video" and card.get("url"):
            cards.setdefault(card["id"], card)
    return [find("https://www.france.tv" + c["url"], c["title"], site="france.tv", kind="video",
                 text=c.get("description", ""), published=c.get("isoDate", ""),
                 picture=((c.get("images") or {}).get("base") or {}).get("x2", ""), length=_seconds(c.get("isoDuration")))
            for c in cards.values()][:PER_SOURCE]


async def _ard(http: httpx.AsyncClient) -> list[Find]:
    # The answers the page preloads for itself: robots.txt closes the gateway they come from.
    page = await get_text(http, "https://www.ardmediathek.de/")
    state = json.loads(re.search(r'id="fetchedContextValue" type="application/json">(.*?)</script>', page, re.S).group(1))
    teasers = [t for _, fetched in state[1:] for t in fetched["data"]["teasers"]]
    # Only a single video's target is one; the others are series and pages. Its image address asks for its width.
    return [find(f"https://www.ardmediathek.de/video/{t['links']['target']['urlId']}", t["longTitle"],
                 site="ARD Mediathek", kind="video", text=(t.get("show") or {}).get("synopsis", ""),
                 author=(t.get("publicationService") or {}).get("name", ""),
                 published=t.get("broadcastedOn", ""), length=t.get("duration"),
                 picture=t["images"]["aspect16x9"]["src"].replace("{width}", "640"))
            for t in teasers if "/item/" in t["links"]["target"]["href"]][:PER_SOURCE]


async def _rtve(http: httpx.AsyncClient) -> list[Find]:
    # The lists on the Play page are schema.org data; its series entries are pages, not videos.
    page = await get_text(http, "https://www.rtve.es/play/")
    found = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        data = json.loads(block, strict=False)
        for entry in data.get("itemListElement", []) if data.get("@type") == "ItemList" else []:
            v = entry["item"]
            if v.get("@type") == "VideoObject":
                found.append(find(v["url"], v["name"], site="RTVE Play", kind="video", text=v.get("description", ""),
                                  published=v.get("uploadDate", ""), picture=v.get("thumbnailUrl", ""),
                                  length=_seconds(v.get("duration"))))
    return found[:PER_SOURCE]


# ---------------------------------------------------------------- the list

SOURCES: list[Source] = [
    Source("tencent-video", ("Tencent Video", "腾讯视频"),
           ("shows and films Tencent Video recommends on its home page", "腾讯视频首页推荐的剧集与影片"),
           "video", _tencent, "zh", "zh", "CN", "qq.com"),
    Source("iqiyi", ("iQiyi", "爱奇艺"),
           ("the most-watched series, films, anime and variety shows on iQiyi", "爱奇艺人气最高的剧集、电影、动漫和综艺"),
           "video", _iqiyi, "zh", "zh", "CN", "iqiyi.com"),
    Source("youku", ("Youku", "优酷"),
           ("the shows Youku features on its home page", "优酷首页推荐的剧集与节目"),
           "video", _youku, "zh", "zh", "CN", "youku.com"),
    Source("mgtv", ("Mango TV", "芒果TV"),
           ("the most-watched series, films, variety shows and anime on Mango TV", "芒果TV 人气最高的剧集、电影、综艺和动漫"),
           "video", _mgtv, "zh", "zh", "CN", "mgtv.com"),
    Source("cctv-video", ("CCTV Video", "央视网视频"),
           ("news clips and programme highlights on CCTV's video page", "央视网视频首页的新闻片段与节目精选"),
           "video", _cctv, "", "zh", "CN", "cctv.com"),
    Source("pearvideo", ("Pear Video", "梨视频"),
           ("short news videos from Pear Video's ranking", "梨视频排行榜上的资讯短视频"),
           "video", _pearvideo, "zh", "zh", "CN", "pearvideo.com"),
    Source("douyu-live", ("Douyu Live", "斗鱼直播"),
           ("live rooms on air now on Douyu", "斗鱼此刻正在直播的房间"),
           "video", _douyu, "", "zh", "CN", "douyu.com"),
    Source("bilibili-live", ("Bilibili Live", "哔哩哔哩直播"),
           ("live rooms with the most viewers on Bilibili", "哔哩哔哩此刻观看人数最多的直播间"),
           "video", _bilibili_live, "", "zh", "CN", "bilibili.com"),
    Source("niconico-ranking", ("Niconico Ranking", "Niconico 排行"),
           ("Niconico's most-watched videos of the day", "ニコニコ动画今日播放最多的视频"),
           "video", _niconico, "ja", "ja", "JP", "nicovideo.jp"),
    Source("chzzk-live", ("CHZZK Live", "CHZZK 直播"),
           ("live streams with the most viewers on Naver's CHZZK", "Naver 旗下 CHZZK 上观看人数最多的直播"),
           "video", _chzzk, "ko", "ko", "KR", "naver.com"),
    Source("soop-live", ("SOOP Live", "SOOP 直播"),
           ("live streams with the most viewers on SOOP (formerly AfreecaTV)", "SOOP（原 AfreecaTV）上观看人数最多的直播"),
           "video", _soop, "", "ko", "KR", "sooplive.co.kr"),
    Source("rutube-popular", ("Rutube Popular", "Rutube 热门"),
           ("popular videos from the channels Rutube features", "Rutube 精选频道的热门视频"),
           "video", _rutube, "ru", "ru", "RU", "rutube.ru"),
    Source("ted-talks", ("TED Talks", "TED 演讲"),
           ("the newest talks on ted.com", "ted.com 上最新的演讲"),
           "video", _ted, "en", "en", "", "ted.com"),
    Source("odysee-trending", ("Odysee Trending", "Odysee 热门"),
           ("trending English-language videos on Odysee", "Odysee 上正在走红的英语视频"),
           "video", _odysee, "", "en", "", "odysee.com"),
    Source("peertube-trending", ("PeerTube Trending", "PeerTube 热门"),
           ("trending videos across PeerTube instances, by Sepia Search", "各 PeerTube 站点的热门视频（Sepia Search 汇总）"),
           "video", _peertube, "en", "en", "", "sepiasearch.org"),
    Source("francetv", ("France.tv", "France.tv"),
           ("replays, films and series on the France Télévisions home page", "France Télévisions 首页上的回放、电影与剧集"),
           "video", _francetv, "fr", "fr", "FR", "france.tv"),
    Source("ard-mediathek", ("ARD Mediathek", "ARD Mediathek"),
           ("highlights from Germany's public broadcasters' library", "德国公共电视台媒体库的精选视频"),
           "video", _ard, "de", "de", "DE", "ardmediathek.de"),
    Source("rtve-play", ("RTVE Play", "RTVE Play"),
           ("news and documentary videos on Spanish public television's player", "西班牙国家电视台点播平台上的新闻与纪录片"),
           "video", _rtve, "es", "es", "ES", "rtve.es"),
]
