"""What a page says about itself, read as a signed-out visitor reads it.

Which addresses a visitor may go to, a page's own facts (Open Graph, Twitter card, schema.org JSON-LD and its
readable text) as library Item fields, the wall it shows a visitor, and its picture made small for the library.
"""
from __future__ import annotations

import html
import io
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from . import players
from .ingestion import _RESERVED_LOCAL_NAMES, MAX_IMAGE_PIXELS, _is_internal_ip, _resolve_public_target
from .library import PICTURE_MAX_BYTES, TEXT_MAX
from .players import player_for
from .web import read as reading

PICTURE_SIDE = 480
PICTURE_FETCH_MAX = 8_000_000
DESCRIPTION_MAX = 1000
_KNOWN_SITES = {"bilibili.com": "Bilibili", "b23.tv": "Bilibili", "youtube.com": "YouTube",
                "youtu.be": "YouTube"}
_VIDEO_TYPES = {"VideoObject"}
_ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "ReportageNewsArticle", "TechArticle",
                  "ScholarlyArticle", "AnalysisNewsArticle"}
_POST_TYPES = {"SocialMediaPosting", "DiscussionForumPosting"}
_ISO_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?")

# ---------------------------------------------------------------- addresses

def host_ok(host: str) -> bool:
    """False for a name or literal address that is this computer or its network."""
    host = (host or "").strip("[]").rstrip(".").lower()
    if not host or host in _RESERVED_LOCAL_NAMES or host.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return True
    return not _is_internal_ip(host)


async def public_address(url: str) -> bool:
    """http(s) to a name whose every address is public."""
    return await _resolve_public_target(url) is not None


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def site_name(url: str) -> str:
    host = host_of(url)
    for domain, name in _KNOWN_SITES.items():
        if _on(host, domain):
            return name
    return host[4:] if host.startswith("www.") else host


def allowed_player(url: str) -> str:
    """`url` when it is an official player on the list (players.PLAYERS), a YouTube embed made cookieless;
    else ""."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    if urlsplit(url).scheme == "https" and (_on(host, "youtube.com") or _on(host, "youtube-nocookie.com")):
        return player_for(url)
    return players.allowed(url)


# ---------------------------------------------------------------- facts

def _text(value: Any, limit: int = 300) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join(html.unescape(str(value)).split())[:limit]


def _person(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name")
    name = _text(value, 120)
    return "" if name.startswith(("http://", "https://")) else name


def _image(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    return _text(value, 2000)


def _seconds(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if 0 < value < 360_000 else None
    text = str(value or "").strip()
    if text.isdigit():
        return _seconds(int(text))
    match = _ISO_DURATION.fullmatch(text)
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
    return _seconds(int(days * 86400 + hours * 3600 + minutes * 60 + seconds))


def _ld_objects(blobs: Any) -> list[dict]:
    found: list[dict] = []
    for blob in (blobs if isinstance(blobs, list) else [])[:10]:
        try:
            queue = [json.loads(blob)] if isinstance(blob, str) else []
        except ValueError:
            continue
        while queue and len(found) < 50:
            value = queue.pop(0)
            if isinstance(value, list):
                queue.extend(value[:20])
            elif isinstance(value, dict):
                found.append(value)
                if isinstance(value.get("@graph"), list):
                    queue.extend(value["@graph"][:30])
    return found


def _types(obj: dict) -> set[str]:
    kind = obj.get("@type")
    return {str(k) for k in (kind if isinstance(kind, list) else [kind]) if isinstance(k, str)}


def _absolute(base: str, address: str) -> str:
    if not address:
        return ""
    url = urljoin(base, address.strip())
    return url if urlsplit(url).scheme in ("http", "https") else ""


def _embed(data: dict, meta: dict[str, str], main: dict, url: str) -> str:
    """The page's player: its own address's or its canonical one's, else the first player on the list it declares."""
    embed = player_for(url) or player_for(_text(data.get("canonical"), 2000))
    for declared in (meta.get("og:video:secure_url"), meta.get("og:video:url"), meta.get("og:video"),
                     meta.get("twitter:player"), main.get("embedUrl")):
        if embed:
            break
        embed = allowed_player(_absolute(url, _text(declared, 2000)))
    return embed


def _kind(embed: bool, kinds: set[str], og_type: str, text: str) -> str:
    if embed or kinds & _VIDEO_TYPES or og_type.startswith("video"):
        return "video"
    if kinds & _ARTICLE_TYPES or og_type == "article":
        return "article"
    if kinds & _POST_TYPES:
        return "post"
    return "article" if len(text) >= 1500 else "page"


def facts_from(data: Any, url: str) -> dict:
    """Item fields from what reader.js read off a page (its meta pairs, JSON-LD blobs, canonical address
    and text); every value checked, as the page wrote it."""
    data = data if isinstance(data, dict) else {}
    meta: dict[str, str] = {}
    for row in data.get("meta") if isinstance(data.get("meta"), list) else []:
        if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str) and isinstance(row[1], str):
            meta.setdefault(row[0], row[1])
    objects = _ld_objects(data.get("ld"))
    main = (next((o for o in objects if _types(o) & _VIDEO_TYPES), None)
            or next((o for o in objects if _types(o) & _ARTICLE_TYPES), None)
            or next((o for o in objects if _types(o) & _POST_TYPES), None) or {})

    def first(*values: Any, limit: int = 300) -> str:
        return next((t for t in (_text(v, limit) for v in values) if t), "")

    published = first(main.get("datePublished"), main.get("uploadDate"), meta.get("article:published_time"),
                      meta.get("datepublished"), meta.get("uploaddate"), limit=40)
    pictures = [meta.get("og:image:secure_url"), meta.get("og:image"), meta.get("twitter:image"),
                _image(main.get("thumbnailUrl")), _image(main.get("image"))]
    picture = next((p for p in (_absolute(url, _text(v, 2000)) for v in pictures)
                    if p and len(p) <= 2000), "")
    embed = _embed(data, meta, main, url)
    length = (_seconds(main.get("duration")) or _seconds(meta.get("og:video:duration"))
              or _seconds(meta.get("video:duration")) or _seconds(meta.get("duration")))
    text = str(data.get("text") or "") if isinstance(data.get("text"), str) else ""
    # reader.js marks headings with "## "; an item's text is plain.
    text = "\n".join(" ".join(line.split()).removeprefix("## ") for line in text.splitlines()).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)[:TEXT_MAX]
    kind = _kind(bool(embed), _types(main), meta.get("og:type", "").lower(), text)
    free = main.get("isAccessibleForFree")
    if kind == "video":
        # A video page's text is its surroundings; its words are in the description.
        text = ""
    known = site_name(url) if any(_on(host_of(url), d) for d in _KNOWN_SITES) else ""
    return {
        "title": first(meta.get("og:title"), meta.get("twitter:title"), main.get("headline"), main.get("name"),
                       data.get("title")),
        "site": known or first(meta.get("og:site_name"), meta.get("application-name"), limit=80) or site_name(url),
        "author": _person(main.get("author")) or first(meta.get("author"), limit=120),
        "published": published,
        "length": length,
        # A page's own description first: a post's or a video's main text is often a banner or a reply.
        "description": first(meta.get("og:description"), meta.get("twitter:description"), meta.get("description"),
                             main.get("description"), limit=DESCRIPTION_MAX),
        "picture": picture,
        "embed": embed,
        "text": text,
        "kind": kind,
        "paywall": free is False or str(free).lower() == "false",
    }


def wall_of(data: Any, url: str, facts: dict) -> str:
    """Why this page is not for a visitor: a sign-in or check address, the wall reader.js saw
    ("verification", "sign_in", "error"; a sign-in layer or an empty page only when nothing of the page reads,
    not even its title), or "paywall"; "" for none."""
    found = reading.wall_at(url)
    if found:
        return found
    sign = data.get("wall") if isinstance(data, dict) and isinstance(data.get("wall"), dict) else {}
    kind = str(sign.get("kind") or "")
    if kind and not (kind in ("sign_in_overlay", "empty") and facts.get("title")):
        return kind
    return "paywall" if facts.get("paywall") else ""


def small_picture(data: bytes) -> bytes:
    """A JPEG of the picture fitting PICTURE_SIDE and under the library's size limit, or b""."""
    try:
        from PIL import Image
    except ImportError:
        return b""
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                return b""
            source.draft("RGB", (PICTURE_SIDE * 2, PICTURE_SIDE * 2))
            picture = source.convert("RGB")
        picture.thumbnail((PICTURE_SIDE, PICTURE_SIDE))
        for quality in (82, 70, 55):
            out = io.BytesIO()
            picture.save(out, "JPEG", quality=quality, optimize=True)
            if out.tell() <= PICTURE_MAX_BYTES:
                return out.getvalue()
    except Exception:
        return b""
    return b""
