"""The official players a card may embed: one list that what a card may carry
(roam.allowed_player, life's cards) and what the page lets load (its CSP
frame-src, life.PLAYER_HOSTS) both read.

Each is a platform's own embed, tried in a frame on another page by the
platform probes of 2026-11-19. A host that is also the platform's main site
is allowed only on its player's path, in the CSP too. A link to a
platform's page becomes its player where the address alone says which
thing it is (`player_for`); the others come only from what a page declares
(og:video, twitter:player, a VideoObject's embedUrl).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, urlsplit

# (host, the player's path as a pattern)
PLAYERS = (
    ("www.youtube-nocookie.com", r"/embed/[\w-]{11}"),
    ("www.youtube.com", r"/embed/[\w-]{11}"),
    ("player.bilibili.com", r"/player\.html"),
    ("player.vimeo.com", r"/video/\d+"),
    ("embed.nicovideo.jp", r"/watch/[a-z]{2}\d+"),
    ("rutube.ru", r"/play/embed/[0-9a-f]{32}/?"),
    ("www.acfun.cn", r"/player/ac\d+"),
    ("liveshare.huya.com", r"/iframe/\d+"),
    ("www.tiktok.com", r"/player/v1/\d+"),
    ("open.douyin.com", r"/player/video"),
    ("platform.twitter.com", r"/embed/Tweet\.html"),
    ("www.threads.com", r"/@[\w.]+/post/[\w-]+/embed/?"),
    ("www.instagram.com", r"/(p|reel)/[\w-]+/embed(/captioned)?/?"),
    ("www.facebook.com", r"/plugins/(video|post)\.php"),
    ("embed.reddit.com", r"/r/\w+/comments/\w+(/[^/]*)?/?"),
    ("embed.bsky.app", r"/embed/did:[\w:.]+/app\.bsky\.feed\.post/\w+"),
    ("embed.tumblr.com", r"/embed/post/[\w:-]+/\d+(/v2)?"),
    ("www.linkedin.com", r"/embed/feed/update/urn:li:(share|ugcPost):\d+"),
    ("www.snapchat.com", r"/spotlight/[\w-]+/embed/?"),
    ("assets.pinterest.com", r"/ext/embed\.html"),
    ("embed.pixiv.net", r"/oembed_iframe\.php"),
)
_YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_BV = re.compile(r"/video/(BV[0-9A-Za-z]{10})")
# (the platform's domain, its page's path, the player): \1, \2 are the path's groups.
_FROM_PAGE = (
    ("vimeo.com", r"/(\d+)/?", r"https://player.vimeo.com/video/\1"),
    ("nicovideo.jp", r"/watch/([a-z]{2}\d+)/?", r"https://embed.nicovideo.jp/watch/\1"),
    ("rutube.ru", r"/video/([0-9a-f]{32})/?", r"https://rutube.ru/play/embed/\1"),
    ("acfun.cn", r"/v/(ac\d+)/?", r"https://www.acfun.cn/player/\1"),
    ("huya.com", r"/(\d+)/?", r"https://liveshare.huya.com/iframe/\1"),
    ("tiktok.com", r"/@[\w.-]+/video/(\d+)/?", r"https://www.tiktok.com/player/v1/\1"),
    ("douyin.com", r"/video/(\d+)/?", r"https://open.douyin.com/player/video?vid=\1&autoplay=0"),
    ("x.com", r"/\w+/status/(\d+)/?", r"https://platform.twitter.com/embed/Tweet.html?id=\1&dnt=true"),
    ("twitter.com", r"/\w+/status/(\d+)/?", r"https://platform.twitter.com/embed/Tweet.html?id=\1&dnt=true"),
    ("threads.com", r"/(@[\w.]+)/post/([\w-]+)/?", r"https://www.threads.com/\1/post/\2/embed"),
    ("threads.net", r"/(@[\w.]+)/post/([\w-]+)/?", r"https://www.threads.com/\1/post/\2/embed"),
    ("instagram.com", r"/(p|reel)/([\w-]+)/?", r"https://www.instagram.com/\1/\2/embed/captioned/"),
    ("reddit.com", r"/r/(\w+)/comments/(\w+)(?:/[^/]*)?/?", r"https://embed.reddit.com/r/\1/comments/\2/?embed=true"),
    ("snapchat.com", r"/spotlight/([\w-]+)/?", r"https://www.snapchat.com/spotlight/\1/embed"),
    ("pinterest.com", r"/pin/(\d+)/?", r"https://assets.pinterest.com/ext/embed.html?id=\1"),
)
_FACEBOOK_VIDEO = re.compile(r"/([\w.-]+/videos/(?:[\w-]+/)?\d+|reel/\d+|watch)/?")


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def frame_sources() -> tuple[str, ...]:
    """What the page's CSP frame-src lists: each host, with the fixed start of its player's path where
    the host is also a site of its own."""
    out = []
    for host, path in PLAYERS:
        fixed = re.split(r"[\\(\[{.*+?|]", path, maxsplit=1)[0]
        prefix = fixed[:fixed.rfind("/") + 1] or "/"
        out.append(host + (prefix if prefix != "/" else ""))
    return tuple(out)


def allowed(url: str) -> str:
    """`url` when it is an https player on the list, on its player's path; else ""."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.port is not None:
        return ""
    return url if any(host == h and re.fullmatch(p, parts.path) for h, p in PLAYERS) else ""


def youtube_id(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host, path = (parts.hostname or "").lower(), parts.path
    ident = ""
    if _on(host, "youtu.be"):
        ident = path.strip("/").split("/")[0]
    elif _on(host, "youtube.com") or _on(host, "youtube-nocookie.com"):
        if path == "/watch":
            ident = (parse_qs(parts.query).get("v") or [""])[0]
        else:
            bits = path.strip("/").split("/")
            if len(bits) >= 2 and bits[0] in ("shorts", "embed", "live", "v"):
                ident = bits[1]
    return ident if _YT_ID.fullmatch(ident) else ""


def bilibili_id(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not _on((parts.hostname or "").lower(), "bilibili.com"):
        return ""
    match = _BV.search(parts.path)
    return match.group(1) if match else ""


def player_for(url: str) -> str:
    """The official player of a platform's page, made from its address alone, else ""."""
    ident = youtube_id(url)
    if ident:
        return f"https://www.youtube-nocookie.com/embed/{ident}"
    ident = bilibili_id(url)
    if ident:
        return f"https://player.bilibili.com/player.html?bvid={ident}&autoplay=0"
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower()
    for domain, path, player in _FROM_PAGE:
        match = re.fullmatch(path, parts.path)
        if _on(host, domain) and match:
            return match.expand(player)
    if _on(host, "facebook.com") and _FACEBOOK_VIDEO.fullmatch(parts.path) and (parts.path != "/watch" or parts.query):
        page = f"https://www.facebook.com{parts.path}" + (f"?{parts.query}" if parts.path == "/watch" else "")
        return f"https://www.facebook.com/plugins/video.php?href={quote(page, safe='')}&show_text=false"
    return ""
