"""The official players a card may embed: one list that what a card may carry
(pagefacts.allowed_player, life's cards) and what the page lets load (its CSP
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
    ("embed.ted.com", r"/talks/[\w-]+"),
    ("odysee.com", r"/\$/embed/[^/]+/[0-9a-f]{40}"),
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
    ("x.com", r"/\w+/status/(\d+)/?", r"https://platform.twitter.com/embed/Tweet.html?id=\1&dnt=true"),
    ("twitter.com", r"/\w+/status/(\d+)/?", r"https://platform.twitter.com/embed/Tweet.html?id=\1&dnt=true"),
    ("threads.com", r"/(@[\w.]+)/post/([\w-]+)/?", r"https://www.threads.com/\1/post/\2/embed"),
    ("threads.net", r"/(@[\w.]+)/post/([\w-]+)/?", r"https://www.threads.com/\1/post/\2/embed"),
    ("instagram.com", r"/(p|reel)/([\w-]+)/?", r"https://www.instagram.com/\1/\2/embed/captioned/"),
    ("reddit.com", r"/r/(\w+)/comments/(\w+)(?:/[^/]*)?/?", r"https://embed.reddit.com/r/\1/comments/\2/?embed=true"),
    ("snapchat.com", r"/spotlight/([\w-]+)/?", r"https://www.snapchat.com/spotlight/\1/embed"),
    ("pinterest.com", r"/pin/(\d+)/?", r"https://assets.pinterest.com/ext/embed.html?id=\1"),
    ("ted.com", r"/talks/([\w-]+)/?", r"https://embed.ted.com/talks/\1"),
    # Odysee's page address ends in the claim's name and its whole id, which is what its player takes.
    ("odysee.com", r"/@[^/]+/([^/:]+):([0-9a-f]{40})/?", r"https://odysee.com/$/embed/\1/\2"),
)
_FACEBOOK_VIDEO = re.compile(r"/([\w.-]+/videos/(?:[\w-]+/)?\d+|reel/\d+|watch)/?")
# Douyin's and TikTok's videos and picture notes in every form their links take: (the platform's domain, its path,
# or "?" and its query, as a pattern whose groups are the user and the id; the one address it is). A short link
# (v.douyin.com, vm.tiktok.com, vt.tiktok.com, tiktok.com/t/) names no id: it is left as it is, and read where it
# redirects.
_SHORT_VIDEO = (
    ("douyin.com", r"/(?:video|share/video|light)/(\d{6,})/?", "https://www.douyin.com/video/{0}"),
    ("douyin.com", r"/(?:note|share/note|share/slides)/(\d{6,})/?", "https://www.douyin.com/note/{0}"),
    # A video opened over a list (精选, a profile, search) keeps the list's address with modal_id.
    ("douyin.com", r"?(?:.*&)?modal_id=(\d{6,})(?:&.*)?", "https://www.douyin.com/video/{0}"),
    ("iesdouyin.com", r"/share/video/(\d{6,})/?", "https://www.douyin.com/video/{0}"),
    ("iesdouyin.com", r"/share/(?:note|slides)/(\d{6,})/?", "https://www.douyin.com/note/{0}"),
    ("tiktok.com", r"/@([\w.-]*)/video/(\d{6,})/?", "https://www.tiktok.com/@{0}/video/{1}"),
    ("tiktok.com", r"/@([\w.-]*)/photo/(\d{6,})/?", "https://www.tiktok.com/@{0}/photo/{1}"),
    # TikTok's own redirect of an address with no user in it goes to /@/video/<id>.
    ("tiktok.com", r"/v/(\d{6,})\.html", "https://www.tiktok.com/@/video/{0}"),
    ("tiktok.com", r"/(?:embed/v2|embed|player/v1)/(\d{6,})/?", "https://www.tiktok.com/@/video/{0}"),
)
# The platforms whose finds are only their videos and notes: a row of theirs that is neither (a profile, a tag) is
# not one.
ITEMS_ONLY = ("douyin.com", "tiktok.com")


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def frame_sources() -> tuple[str, ...]:
    """What the page's CSP frame-src lists: each host, with the fixed start of its player's path where
    the host is also a site of its own."""
    out = []
    for host, path in PLAYERS:
        fixed = re.split(r"[\\(\[{.*+?|]", path.replace(r"\$", "$"), maxsplit=1)[0]
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


def canonical(url: str) -> str:
    """The one address of a Douyin or TikTok video or picture note, from any form of its link (a modal, a share
    page, the mobile site, an embed); "" for any other address."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https"):
        return ""
    for domain, pattern, one in _SHORT_VIDEO:
        match = _on(host, domain) and (re.fullmatch(pattern[1:], parts.query) if pattern[0] == "?"
                                       else re.fullmatch(pattern, parts.path))
        if match:
            return one.format(*match.groups())
    return ""


def player_for(url: str) -> str:
    """The official player of a platform's page, made from its address alone, else ""."""
    video = re.fullmatch(r"https://www\.(douyin|tiktok)\.com/(?:@[\w.-]*/)?video/(\d+)", canonical(url))
    if video:
        return (f"https://open.douyin.com/player/video?vid={video[2]}&autoplay=0" if video[1] == "douyin"
                else f"https://www.tiktok.com/player/v1/{video[2]}")
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
