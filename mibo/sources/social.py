"""Social platforms and the large reading and listening platforms: code, communities, books, comics, music, podcasts.

Every address here answered a plain visitor without a key, a sign-in or a cookie, and its robots.txt allowed it,
when this was written (2026-11-23). These did not: Reddit, Hupu, Quora, IMDb, Flickr, note and Deezer's API turn
programs away in robots.txt; Weibo's hot search, Letterboxd, pixiv and MangaDex answer a visitor check; NGA,
Threads, Jike and Xiaoheihe ask for a sign-in or a signed request; Xiaoyuzhou and Ximalaya's pages carry no list.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx

from .base import PER_SOURCE, Find, Source, find, get_json, get_text, plain


def _bare(url: str) -> str:
    """A link without its tracking query."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _page_state(page: str, script_id: str) -> dict:
    """The JSON a server-rendered page carries in its `<script id=...>` tag."""
    match = re.search(rf'<script[^>]*id="{script_id}"[^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise ValueError(f"the page no longer carries {script_id}")
    return json.loads(match.group(1))


# ---------------------------------------------------------------- GitHub

_REPO = re.compile(r'<h2 class="h3 lh-condensed">.*?href="/([\w.-]+/[\w.-]+)"', re.S)
_REPO_ABOUT = re.compile(r'<p class="col-9[^"]*">(.*?)</p>', re.S)
_REPO_LANGUAGE = re.compile(r'<span itemprop="programmingLanguage">([^<]+)</span>')
_REPO_STARS = re.compile(r"([\d,]+) stars today")


async def _github_trending(http: httpx.AsyncClient) -> list[Find]:
    page = await get_text(http, "https://github.com/trending", since="daily")
    found = []
    for block in page.split('<article class="Box-row">')[1:]:
        repo = _REPO.search(block)
        if not repo:
            continue
        about, language, stars = _REPO_ABOUT.search(block), _REPO_LANGUAGE.search(block), _REPO_STARS.search(block)
        facts = [plain(about.group(1))] if about else []
        facts += [language.group(1)] if language else []
        facts += [f"{stars.group(1)} stars today"] if stars else []
        found.append(find(f"https://github.com/{repo.group(1)}", repo.group(1), site="GitHub", kind="page",
                          text=" ｜ ".join(facts)))
    return found[:PER_SOURCE]


# ---------------------------------------------------------------- Douban

async def _douban_nowplaying(http: httpx.AsyncClient) -> list[Find]:
    # The films in cinemas, the most wanted first; the list is one city's, but the releases are the country's.
    page = await get_text(http, "https://movie.douban.com/cinema/nowplaying/beijing/")
    films = []
    for block in page.split('class="list-item"')[1:]:
        facts = dict(re.findall(r'data-(\w+)="([^"]*)"', block.split(">", 1)[0]))
        poster = re.search(r'<img src="([^"]+)"', block)
        if facts.get("category") == "nowplaying" and poster:
            films.append((int(facts.get("votecount") or 0), facts, poster.group(1)))
    found = []
    for _, facts, poster in sorted(films, key=lambda film: -film[0])[:PER_SOURCE]:
        score = f"豆瓣 {facts['score']}" if facts.get("score", "0") not in ("", "0") else ""
        about = " ｜ ".join(part for part in (score, facts.get("region", ""), facts.get("duration", ""),
                                              facts.get("director", ""), facts.get("actors", "")) if part)
        found.append(find(f"https://movie.douban.com/subject/{facts['subject']}/", facts["title"], site="豆瓣电影",
                          kind="page", text=about, author=facts.get("director", ""), picture=poster))
    return found


_CHART_ROW = re.compile(r'<a class="nbg" href="([^"]+)"\s+title="([^"]*)">\s*<img src="([^"]+)".*?<p>(.*?)</p>'
                        r'(?:.*?<span class="rating_nums">([\d.]*)</span>)?', re.S)


async def _douban_new_films(http: httpx.AsyncClient) -> list[Find]:
    page = await get_text(http, "https://movie.douban.com/chart")
    found = []
    for block in page.split('<tr class="item">')[1:]:
        film = _CHART_ROW.search(block)
        if film:
            url, title, cover, facts, score = film.groups()
            found.append(find(url, title, site="豆瓣电影", kind="page",
                              text=plain(facts) + (f" ｜ 豆瓣 {score}" if score else ""),
                              picture=cover.replace("/s_ratio_poster/", "/m_ratio_poster/")))
    return found[:PER_SOURCE]


_TOPIC = re.compile(r'<div class="likes">(\d+)<br>.*?<h3><a href="([^"]+)"[^>]*>([^<]+)</a></h3>'
                    r'(?:.*?<img src="([^"]+)")?.*?<span class="from">来自<a [^>]*>([^<]+)</a>', re.S)


async def _douban_groups(http: httpx.AsyncClient) -> list[Find]:
    # The 小组 front page: today's most liked topics across the groups.
    page = await get_text(http, "https://www.douban.com/group/explore")
    found = []
    for block in page.split('<div class="channel-item">')[1:]:
        topic = _TOPIC.search(block)
        if topic:
            likes, url, title, cover, group = topic.groups()
            found.append(find(_bare(url), title, site="豆瓣小组", kind="post", text=f"{group} ｜ {likes} 人喜欢",
                              picture=cover or ""))
    return found[:PER_SOURCE]


# ---------------------------------------------------------------- Apple's public charts

# (storefront, language, region, its name in English, in Chinese)
_STOREFRONTS = (
    ("us", "en", "US", "US", "美国"), ("cn", "zh", "CN", "China", "中国大陆"),
    ("tw", "zh-Hant", "TW", "Taiwan", "台湾"), ("jp", "ja", "JP", "Japan", "日本"),
    ("kr", "ko", "KR", "Korea", "韩国"), ("es", "es", "ES", "Spain", "西班牙"),
    ("fr", "fr", "FR", "France", "法国"), ("de", "de", "DE", "Germany", "德国"),
    ("br", "pt", "BR", "Brazil", "巴西"), ("ru", "ru", "RU", "Russia", "俄罗斯"),
)


def _apple(media: str, chart: str, kind: str, store: str, name: tuple[str, str], about: tuple[str, str],
           lang: str, region: str, default: str = "") -> Source:
    """One storefront's chart from Apple's own feed generator (rss.marketingtools.apple.com)."""
    async def fetch(http: httpx.AsyncClient) -> list[Find]:
        data = await get_json(http, f"https://rss.marketingtools.apple.com/api/v2/{store}/{media}/{chart}/{PER_SOURCE}/{kind}.json")
        return [find(item["url"], item["name"], site=name[0].split(" · ")[0], kind="page",
                     text=" ｜ ".join([item["artistName"], *(genre["name"] for genre in item.get("genres", []))]),
                     author=item["artistName"], published=item.get("releaseDate", ""),
                     # The artwork's address names its size; this one is card size, as a jpeg.
                     picture=re.sub(r"/\d+x\d+bb\.\w+$", "/600x600bb.jpg", item.get("artworkUrl100", "")))
                for item in data["feed"]["results"]][:PER_SOURCE]

    return Source(f"apple-{media}-{store}", name, about, "culture", fetch, default, lang, region, "apple.com")


# ---------------------------------------------------------------- communities

async def _lemmy_hot(http: httpx.AsyncClient) -> list[Find]:
    data = await get_json(http, "https://lemmy.world/api/v3/post/list", sort="Hot", type_="All", limit=PER_SOURCE * 2)
    return [find(f"https://lemmy.world/post/{view['post']['id']}", view["post"]["name"], site="Lemmy", kind="post",
                 text=view["post"].get("body", ""), author=view["creator"]["name"],
                 published=view["post"]["published"], picture=view["post"].get("thumbnail_url", ""))
            for view in data["posts"] if not view["post"]["nsfw"] and not view["community"]["nsfw"]][:PER_SOURCE]


def _tumblr_posts(node: object):
    """The posts anywhere in the page's state, wherever the page nests them."""
    if isinstance(node, dict):
        if "postUrl" in node and "blogName" in node:
            yield node
        else:
            for child in node.values():
                yield from _tumblr_posts(child)
    elif isinstance(node, list):
        for child in node:
            yield from _tumblr_posts(child)


async def _tumblr_trending(http: httpx.AsyncClient) -> list[Find]:
    page = await get_text(http, "https://www.tumblr.com/explore/trending")
    found = []
    for post in _tumblr_posts(_page_state(page, "___INITIAL_STATE___")):
        # A post with no words has nothing to be titled by.
        if post["isNsfw"] or post["classification"] != "clean" or not post["summary"]:
            continue
        pictures = [block["media"][0]["url"] for block in post["content"] if block["type"] == "image"]
        text = " ".join(block["text"] for block in post["content"] if block["type"] == "text")
        found.append(find(post["postUrl"], post["summary"], site="Tumblr", kind="post", text=text,
                          author=post["blogName"], picture=pictures[0] if pictures else "",
                          published=datetime.fromtimestamp(int(post["timestamp"]), timezone.utc).isoformat()))
    return found[:PER_SOURCE]


async def _csdn_hot(http: httpx.AsyncClient) -> list[Find]:
    data = await get_json(http, "https://blog.csdn.net/phoenix/web/blog/hot-rank", page=0, pageSize=PER_SOURCE,
                          child_channel="")
    return [find(_bare(post["articleDetailUrl"]), post["articleTitle"], site="CSDN", author=post.get("nickName", ""),
                 text=f"{post['viewCount']} 阅读 ｜ {post['commentCount']} 评论", picture=next(iter(post["picList"] or []), ""))
            for post in data["data"]][:PER_SOURCE]


# ---------------------------------------------------------------- books and comics

async def _goodreads_new(http: httpx.AsyncClient) -> list[Find]:
    # The month's releases, the most added to shelves first.
    now = datetime.now(timezone.utc)
    page = await get_text(http, f"https://www.goodreads.com/book/popular_by_date/{now.year}/{now.month}")
    state = _page_state(page, "__NEXT_DATA__")["props"]["pageProps"]["apolloState"]
    chart = next(value for key, value in state["ROOT_QUERY"].items() if key.startswith("getTopList"))
    found = []
    for edge in chart["edges"]:
        book = state[edge["node"]["__ref"]]
        author = state[book["primaryContributorEdge"]["node"]["__ref"]]["name"]
        found.append(find(book["webUrl"], book["title"], site="Goodreads", kind="page", text=book.get("description", ""),
                          author=author, picture=book.get("imageUrl") or ""))
    return found[:PER_SOURCE]


def _weread(key: str, name: tuple[str, str], about: tuple[str, str], chart: str, default: str = "") -> Source:
    """A WeRead ranking: the list its web page loads, one JSON answer."""
    async def fetch(http: httpx.AsyncClient) -> list[Find]:
        data = await get_json(http, f"https://weread.qq.com/web/bookListInCategory/{chart}", rank=1)
        found = []
        for entry in data["books"][:PER_SOURCE]:
            book = entry["bookInfo"]
            # The page's own address is the book's hash, which the deep link carries.
            code = re.search(r"[?&]v=(\w+)", book["deepLink"])
            if code:
                found.append(find(f"https://weread.qq.com/web/bookDetail/{code.group(1)}", book["title"],
                                  site="微信读书", kind="page", text=book.get("intro", ""), author=book.get("author", ""),
                                  picture=book.get("cover", "")))
        return found

    # Tencent's reading app shares qq.com with Tencent Video, so it names no platform of its own.
    return Source(key, name, about, "culture", fetch, default, "zh", "CN")


_WEBTOON = re.compile(r'<a href="(https://www\.webtoons\.com/en/[^"]+/list\?title_no=\d+)".*?'
                      r'data-title-unsuitable-for-children="(\w+)".*?<img[^>]+src="([^"]+)".*?'
                      r'<strong class="title">([^<]+)</strong>.*?<div class="genre">([^<]*)</div>'
                      r'.*?<div class="view_count[^"]*">([^<]*)</div>', re.S)


async def _webtoon_popular(http: httpx.AsyncClient) -> list[Find]:
    page = await get_text(http, "https://www.webtoons.com/en/ranking/popular")
    return [find(url, title, site="WEBTOON", kind="page", text=f"{genre} ｜ {likes} likes", picture=cover)
            for url, adult, cover, title, genre, likes in _WEBTOON.findall(page) if adult == "false"][:PER_SOURCE]


async def _naver_webtoon(http: httpx.AsyncClient) -> list[Find]:
    # The webtoons that update today, the most popular first.
    data = await get_json(http, "https://comic.naver.com/api/webtoon/titlelist/weekday", order="user")
    return [find(f"https://comic.naver.com/webtoon/list?titleId={title['titleId']}", title["titleName"],
                 site="네이버 웹툰", kind="page", author=title["author"],
                 picture=title["thumbnailUrl"])
            for title in data["titleListMap"][data["dayOfWeek"]] if not title["adult"] and not title["rest"]][:PER_SOURCE]


_MAL_ROW = re.compile(r'<h3 class="[^"]*anime_ranking_h3"><a href="([^"]+)"[^>]*>([^<]+)</a>.*?'
                      r'<div class="information di-ib mt4">(.*?)</div>.*?score-label score-\w+">([\d.]+|N/A)<', re.S)
_MAL_COVER = re.compile(r'data-src="([^"?]+)')


async def _mal_airing(http: httpx.AsyncClient) -> list[Find]:
    page = await get_text(http, "https://myanimelist.net/topanime.php", type="airing")
    found = []
    for block in page.split('<tr class="ranking-list">')[1:]:
        anime, cover = _MAL_ROW.search(block), _MAL_COVER.search(block)
        if anime:
            url, title, facts, score = anime.groups()
            found.append(find(url, title, site="MyAnimeList", kind="page",
                              text=plain(facts.replace("<br>", " ｜ ")) + ("" if score == "N/A" else f" ｜ score {score}"),
                              # The list shows a 50 by 70 thumbnail; the image host has the picture at its own size.
                              picture=re.sub(r"/r/\d+x\d+/", "/", cover.group(1)) if cover else ""))
    return found[:PER_SOURCE]


# ---------------------------------------------------------------- QQ Music

def _qq_music(key: str, name: tuple[str, str], about: tuple[str, str], chart: int) -> Source:
    async def fetch(http: httpx.AsyncClient) -> list[Find]:
        query = {"toplist": {"module": "musicToplist.ToplistInfoServer", "method": "GetDetail",
                             "param": {"topid": chart, "offset": 0, "num": PER_SOURCE, "period": ""}}}
        data = await get_json(http, "https://u.y.qq.com/cgi-bin/musicu.fcg", data=json.dumps(query, separators=(",", ":")))
        # The chart names no page for a song but its album's.
        return [find(f"https://y.qq.com/n/ryqq/albumDetail/{song['albumMid']}", song["title"], site="QQ音乐", kind="page",
                     text=song["singerName"], author=song["singerName"],
                     picture=f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{song['albumMid']}.jpg")
                for song in data["toplist"]["data"]["data"]["song"]][:PER_SOURCE]

    # QQ Music shares qq.com with Tencent Video, so it names no platform of its own.
    return Source(key, name, about, "culture", fetch, "", "zh", "CN")


SOURCES: list[Source] = [
    Source("github-trending", ("GitHub Trending", "GitHub 趋势"), ("the repositories gaining the most stars today", "今天星标增长最快的开源项目"),
           "tech", _github_trending, default="all", platform="github.com"),
    Source("douban-nowplaying", ("Douban: In Cinemas", "豆瓣·正在热映"), ("the films in cinemas, most wanted first", "正在影院上映的电影，按想看人数排序"),
           "culture", _douban_nowplaying, lang="zh", region="CN", platform="douban.com"),
    Source("douban-new-films", ("Douban: New Films", "豆瓣·新片榜"), ("Douban's chart of the newest films", "豆瓣的新片榜"),
           "culture", _douban_new_films, lang="zh", region="CN", platform="douban.com"),
    Source("douban-groups", ("Douban Groups", "豆瓣小组精选"), ("the topics Douban's groups like most today", "豆瓣小组今日最受喜欢的话题"),
           "community", _douban_groups, default="zh", lang="zh", region="CN", platform="douban.com"),
    Source("csdn-hot", ("CSDN Hot", "CSDN 热榜"), ("the programming posts read most on CSDN", "CSDN 上阅读最多的技术文章"),
           "tech", _csdn_hot, lang="zh", region="CN", platform="csdn.net"),
    Source("lemmy-hot", ("Lemmy Hot", "Lemmy 热门"), ("what is hot across the fediverse's Reddit-like communities", "联邦宇宙里类 Reddit 社区的热门帖子"),
           "community", _lemmy_hot, platform="lemmy.world"),
    Source("tumblr-trending", ("Tumblr Trending", "Tumblr 趋势"), ("the posts Tumblr is trending now", "Tumblr 当下的热门帖子"),
           "community", _tumblr_trending, platform="tumblr.com"),
    Source("goodreads-new", ("Goodreads: New Releases", "Goodreads·本月新书"), ("this month's releases that readers add to their shelves most", "本月出版、读者收藏最多的新书"),
           "culture", _goodreads_new, platform="goodreads.com"),
    _weread("weread-rising", ("WeRead Rising", "微信读书飙升榜"), ("the books climbing fastest on WeRead", "微信读书上上升最快的书"), "rising"),
    _weread("weread-new", ("WeRead New Books", "微信读书新书榜"), ("the new books WeRead readers rate highest", "微信读书上评分最高的新书"), "newbook"),
    Source("webtoon-popular", ("WEBTOON Popular", "WEBTOON 人气榜"), ("the comics most read on WEBTOON", "WEBTOON 上阅读最多的漫画"),
           "culture", _webtoon_popular, platform="webtoons.com"),
    Source("naver-webtoon", ("Naver Webtoon", "Naver 웹툰"), ("today's updated Naver Webtoons, most popular first", "Naver 웹툰今天更新的作品，按人气排序"),
           "culture", _naver_webtoon, lang="ko", region="KR"),
    Source("mal-airing", ("MyAnimeList: Airing", "MyAnimeList·热播榜"), ("the airing anime with the highest MyAnimeList scores", "MyAnimeList 上评分最高的在播动画"),
           "culture", _mal_airing, platform="myanimelist.net"),
    _qq_music("qqmusic-hot", ("QQ Music: Hot songs", "QQ音乐·热歌榜"), ("the songs QQ Music listeners play most", "QQ音乐用户播放最多的歌曲"), 26),
    _qq_music("qqmusic-rising", ("QQ Music: Rising", "QQ音乐·飙升榜"), ("the songs rising fastest on QQ Music", "QQ音乐上上升最快的歌曲"), 62),
]

for store, lang, region, en, zh in _STOREFRONTS:
    SOURCES.append(_apple("podcasts", "top", "podcasts", store, (f"Apple Podcasts · {en}", f"Apple 播客·{zh}"),
                          (f"the shows most listened to on Apple Podcasts ({en})", f"Apple 播客{zh}区收听最多的节目"),
                          lang, region, default="en" if store == "us" else ""))
    SOURCES.append(_apple("music", "most-played", "songs", store, (f"Apple Music · {en}", f"Apple Music·{zh}"),
                          (f"the songs most played on Apple Music ({en})", f"Apple Music {zh}区播放最多的歌曲"),
                          lang, region))
