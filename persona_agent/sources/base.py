"""Places the character reads for its owner without anyone signing in.

A source is one public place (a site's hot list, a feed, an open API) and a
function that reads what is there now. Each module beside this one lists its
own in `SOURCES`; the package gathers them into one catalogue, each round
reads some of it (see `weights`), and what they bring goes into the library
with the walks' finds.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable, Optional
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx

from ..library import Item
from ..roam import player_for, site_name

# Seconds one source has to answer; a slow one is skipped until the next round.
TIMEOUT_S = 15
# A connection that takes this long has failed: shorter than TIMEOUT_S, so the failure is seen and recorded.
CONNECT_S = 8
# What one source may bring in one round.
PER_SOURCE = 12
# Sites answer a browser's request more readily than a script's.
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0 Safari/537.36"),
           "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
GROUPS = ("news", "tech", "video", "community", "science", "culture", "own")
_TAG = re.compile(r"<[^>]+>")
# A post's own stylesheet, script or comment reads as code once the tags are gone.
_HIDDEN = re.compile(r"<(style|script)\b.*?</\1\s*>|<!--.*?-->", re.S | re.I)
# The text is already decoded, so a declared encoding (ISO-8859-1, GBK) no longer holds.
_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_RSS10 = "{http://purl.org/rss/1.0/}"
_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_IMG = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


@dataclass
class Find:
    """One thing a source brought: the item, and its cover's address when the source names one."""
    item: Item
    picture: str = ""


@dataclass(frozen=True)
class Source:
    key: str                    # lower case, unique: "hackernews"
    name: tuple[str, str]       # (English, Chinese)
    about: tuple[str, str]      # one line saying what comes from it, (English, Chinese)
    group: str                  # one of GROUPS
    fetch: Callable[[httpx.AsyncClient], Awaitable[list[Find]]]
    # Whose first rounds lean on it: readers of "zh", of "en", "all" or "" (nobody in particular).
    default: str = ""
    # The language what it brings is written in; "" for the person's own feeds.
    lang: str = "en"
    # The country or area whose platform or local press it is ("CN", "JP", "US"...); "" when global.
    region: str = ""


def written_in(lang: str, sources: list[Source], keys: set[str] | None = None) -> list[Source]:
    """`sources` with those in `keys` (all of them when None) marked as written in `lang`."""
    return [replace(s, lang=lang) if keys is None or s.key in keys else s for s in sources]


def local_to(region: str, sources: list[Source], keys: set[str] | None = None) -> list[Source]:
    """`sources` with those in `keys` (all of them when None) marked as local to `region`."""
    return [replace(s, region=region) if keys is None or s.key in keys else s for s in sources]


def client(transport: Optional[httpx.AsyncBaseTransport] = None,
           mounts: Optional[dict[str, httpx.AsyncBaseTransport]] = None) -> httpx.AsyncClient:
    """The sources' client; a round passes the transport that records reachability (`situation.client_options`)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=CONNECT_S), headers=HEADERS,
                             follow_redirects=True, transport=transport, mounts=mounts)


async def get_text(http: httpx.AsyncClient, url: str, **params) -> str:
    answer = await http.get(url, params=params or None)
    answer.raise_for_status()
    return answer.text


async def get_json(http: httpx.AsyncClient, url: str, **params):
    answer = await http.get(url, params=params or None)
    answer.raise_for_status()
    return answer.json()


def plain(text: object, limit: int = 600) -> str:
    """Markup taken out of a summary, cut at `limit`."""
    words = " ".join(html.unescape(_TAG.sub(" ", _HIDDEN.sub(" ", str(text or "")))).split())
    return words[:limit]


# Image hosts that cut a picture to size when the address asks. Many feeds name
# the full original (often over the half megabyte a cover is read to), so the
# cover is asked for at card size instead: (host ends with, pattern, replacement).
_SMALLER = (
    ("brightspotcdn.com", re.compile(r"/resize/[^/]+/"), "/resize/640/"),                   # NPR
    ("nyt.com", re.compile(r"-(?:mediumSquareAt3X|superJumbo|jumbo)\.jpg$"), "-articleLarge.jpg"),
    ("365dm.com", re.compile(r"/\d+x\d+/"), "/768x432/"),                                   # Sky News
    ("apartmenttherapy.info", re.compile(r"/image/upload/+"), "/image/upload/f_jpg,q_auto:eco,c_fill,w_640/"),
    ("", re.compile(r"/master/pass/"), "/master/w_640,c_limit/"),                           # Condé Nast titles
)
_QUERY_SMALLER = (("natgeofe.com", "w=640"), ("ignimgs.com", "width=640"), ("polygonimages.com", "w=640"),
                  ("tmtpost.com", "imageView2/2/w/640"))


def smaller(picture: str) -> str:
    """The cover's address at card size, where its host can do that."""
    host = urlsplit(picture).hostname or ""
    for ending, pattern, replacement in _SMALLER:
        if host.endswith(ending):
            picture = pattern.sub(replacement, picture, count=1)
    for ending, query in _QUERY_SMALLER:
        if host.endswith(ending) and "?" not in picture:
            return f"{picture}?{query}"
    # Bilibili's image host takes the size after an @.
    if host.endswith("hdslb.com") and "@" not in urlsplit(picture).path:
        return picture + "@640w_360h_1c.jpg"
    return picture


def find(url: str, title: str, *, site: str = "", kind: str = "", text: str = "", author: str = "",
         published: str = "", picture: str = "", length: Optional[int] = None) -> Find:
    """A find from its public facts. A YouTube or Bilibili address becomes a
    video with its player; `kind` is otherwise article, post or page."""
    player = player_for(url)
    return Find(Item(url=url, site=site or site_name(url), kind="video" if player else (kind or "article"),
                     title=plain(title, 200), author=plain(author, 80), published=published,
                     length=length, description=plain(text), embed=player),
                smaller(picture) if picture.startswith("https://") else "")


def _when(text: str) -> str:
    """A feed's date as ISO 8601, or as it was written."""
    text = (text or "").strip()
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        return text


def parse_feed(text: str, base_url: str, *, site: str = "") -> list[Find]:
    """The entries of an RSS 2.0, RSS 1.0 or Atom document, newest as the feed has them."""
    root = ElementTree.fromstring(_DECLARATION.sub("", text, count=1).encode("utf-8"))
    found: list[Find] = []
    for entry in root.iter():
        tag = entry.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        # RSS 1.0 puts link and title in its own namespace; read them as RSS 2.0's.
        fields = {child.tag.removeprefix(_RSS10): child for child in entry}

        def first(*names: str) -> str:
            for name in names:
                node = fields.get(name)
                if node is not None and (node.text or "").strip():
                    return node.text.strip()
            return ""

        link = first("link", f"{_ATOM}id") if not any(c.tag == f"{_ATOM}link" for c in entry) else ""
        for child in entry:
            if child.tag == f"{_ATOM}link" and child.get("rel", "alternate") == "alternate" and child.get("href"):
                link = child.get("href")
                break
        link = urljoin(base_url, link or first("guid"))
        title = first("title", f"{_ATOM}title")
        if not link.startswith(("http://", "https://")) or not title:
            continue
        body = first(f"{_CONTENT}encoded", "description", f"{_ATOM}summary", f"{_ATOM}content")
        picture = ""
        # YouTube and some publishers keep the picture one level down, in media:group.
        group = entry.find(f"{_MEDIA}group")
        for child in [*entry, *(group if group is not None else ())]:
            if child.tag in (f"{_MEDIA}thumbnail", f"{_MEDIA}content", "enclosure"):
                kind = child.get("type", "image") if child.tag != f"{_MEDIA}thumbnail" else "image"
                if child.get("url") and kind.startswith("image"):
                    picture = child.get("url")
                    break
        if not picture:
            # NPR opens some stories with a one-pixel tracking image; the picture is the first real one.
            shown = [src for src in _IMG.findall(body) if "/tracking/" not in src]
            picture = urljoin(link, html.unescape(shown[0])) if shown else ""
        author = first("author", f"{_DC}creator")
        if not author:
            node = fields.get(f"{_ATOM}author")
            name = node.find(f"{_ATOM}name") if node is not None else None
            author = (name.text or "").strip() if name is not None else ""
        found.append(find(link, title, site=site, text=body, author=author, picture=picture,
                          published=_when(first("pubDate", f"{_DC}date", f"{_ATOM}published", f"{_ATOM}updated"))))
    return found


def feed_source(key: str, name: tuple[str, str], about: tuple[str, str], group: str, url: str, *,
                site: str = "", default: str = "") -> Source:
    """A source that is one feed address."""
    async def fetch(http: httpx.AsyncClient) -> list[Find]:
        return parse_feed(await get_text(http, url), url, site=site or name[0])[:PER_SOURCE]

    return Source(key, name, about, group, fetch, default)
