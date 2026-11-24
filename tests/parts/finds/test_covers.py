"""A find's cover: which addresses a source's cover may come from, the formats and sizes the library takes from
them, the visitor's request that fetches one (the thing's page as referer, no cookies, public https addresses
only, every redirect checked again), and the cover of a signed-in feed's row."""
from __future__ import annotations

import asyncio
import io
from urllib.parse import urlsplit

import httpx
import pytest
from PIL import Image, features

from mibo import pagefacts, signedread
from mibo.library import Library
from mibo.panereading import page_of
from mibo.sources import base, catalog

PAGE = "https://shore.example/story/1"


def picture(fmt: str, size=(640, 400), color="teal") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return out.getvalue()


@pytest.fixture
def public(monkeypatch):
    """Every name is public but the internal one a redirect may lead to."""
    async def only_public(address: str) -> bool:
        return urlsplit(address).hostname != "intranet.example"
    monkeypatch.setattr(catalog, "public_address", only_public)


def cover(handler, address: str, referer: str = PAGE) -> bytes:
    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await catalog._cover(http, address, referer)
    return asyncio.run(run())


def seen(bytes_: bytes) -> tuple[str, tuple[int, int]]:
    with Image.open(io.BytesIO(bytes_)) as image:
        return image.format, image.size


# ------------------------------------------------------------- addresses --

def test_a_cover_named_over_http_or_without_a_scheme_is_asked_for_over_https() -> None:
    assert base.find(PAGE, "t", picture="http://img.shore.example/a.jpg").picture == "https://img.shore.example/a.jpg"
    assert base.find(PAGE, "t", picture="//img.shore.example/a.jpg").picture == "https://img.shore.example/a.jpg"
    assert base.find(PAGE, "t", picture="/relative/a.jpg").picture == ""
    assert base.find(PAGE, "t", picture="data:image/png;base64,AAAA").picture == ""


def test_a_wordpress_or_bunny_cover_is_asked_for_at_card_size() -> None:
    wordpress = "https://shore.example/wp-content/uploads/2026/11/boat.jpg"
    assert base.find(PAGE, "t", picture=wordpress).picture == wordpress + "?w=640"
    assert base.find(PAGE, "t", picture=wordpress + "?resize=9").picture == wordpress + "?resize=9"
    assert base.find(PAGE, "t", picture="https://pdr.b-cdn.net/c/a.jpg").picture == "https://pdr.b-cdn.net/c/a.jpg?width=640"


def test_a_page_names_its_cover_by_the_twitter_or_open_graph_kin_too() -> None:
    for key in ("og:image:url", "twitter:image:src"):
        got = pagefacts.facts_from({"meta": [[key, "/img/c.jpg"]]}, "https://shore.example/a")
        assert got["picture"] == "https://shore.example/img/c.jpg"


# ---------------------------------------------------------- what is fetched --

def test_the_things_page_goes_as_referer_and_an_image_host_that_wants_it_answers(public) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cookie" not in request.headers
        if request.headers.get("referer") != PAGE:
            return httpx.Response(403)
        return httpx.Response(200, content=picture("PNG"))
    assert seen(cover(handler, "https://img.shore.example/c.png")) == ("JPEG", (480, 300))
    assert cover(lambda request: httpx.Response(403), "https://img.shore.example/c.png") == b""


def test_a_webp_cover_is_made_into_a_small_jpeg(public) -> None:
    assert seen(cover(lambda r: httpx.Response(200, content=picture("WEBP")), "https://img.shore.example/c.webp")) == (
        "JPEG", (480, 300))


@pytest.mark.skipif(not features.check("avif"), reason="this Pillow reads no AVIF")
def test_an_avif_cover_is_made_into_a_small_jpeg(public) -> None:
    assert cover(lambda r: httpx.Response(200, content=picture("AVIF")), "https://img.shore.example/c.avif")


def test_a_redirect_is_followed_over_https_and_never_to_an_internal_address(public) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "img.shore.example":
            return httpx.Response(302, headers={"location": "http://cdn.shore.example/c.png"})
        if host == "cdn.shore.example":
            assert request.url.scheme == "https"
            return httpx.Response(200, content=picture("PNG"))
        raise AssertionError(f"went to {host}")
    assert cover(handler, "https://img.shore.example/c.png")
    leads_in = lambda r: httpx.Response(302, headers={"location": "https://intranet.example/c.png"})  # noqa: E731
    assert cover(leads_in, "https://img.shore.example/c.png") == b""


def test_a_cover_over_the_fetch_limit_is_not_read(public) -> None:
    told = lambda r: httpx.Response(200, headers={"content-length": str(pagefacts.PICTURE_FETCH_MAX + 1)}, content=b"x")  # noqa: E731
    assert cover(told, "https://img.shore.example/c.jpg") == b""
    streamed = lambda r: httpx.Response(200, content=b"x" * (pagefacts.PICTURE_FETCH_MAX + 1))  # noqa: E731
    assert cover(streamed, "https://img.shore.example/c.jpg") == b""


def test_a_camera_jpeg_of_many_pixels_is_read_at_a_fraction_but_other_formats_are_not(monkeypatch) -> None:
    monkeypatch.setattr(pagefacts, "MAX_IMAGE_PIXELS", 4_000_000)
    assert seen(pagefacts.small_picture(picture("JPEG", (4000, 3000)))) == ("JPEG", (480, 360))
    assert pagefacts.small_picture(picture("PNG", (4000, 3000))) == b""
    monkeypatch.setattr(pagefacts, "JPEG_PIXELS_MAX", 8_000_000)
    assert pagefacts.small_picture(picture("JPEG", (4000, 3000))) == b""


def test_an_svg_is_no_cover() -> None:
    assert pagefacts.small_picture(b'<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9"/>') == b""


# ------------------------------------------------------ a signed-in feed's rows --

ROWS = [{"title": "A dance", "link": "https://www.douyin.com/video/7300000000000000001",
         "picture": "https://p3.douyinpic.example/cover.webp"},
        {"title": "A note", "link": "https://www.douyin.com/note/7300000000000000002"}]


def test_a_feed_rows_cover_goes_with_its_row_only_for_a_feed_read() -> None:
    data = {"kind": "list", "rows": ROWS}
    assert [r.get("picture") for r in page_of("https://www.douyin.com/", data)["rows"]] == [None, None]
    assert [r.get("picture") for r in page_of("https://www.douyin.com/", data, pictures=True)["rows"]] == [
        ROWS[0]["picture"], None]


def test_a_feed_row_keeps_its_cover_fetched_as_a_visitor_with_the_rows_page_as_referer(tmp_path, monkeypatch, public) -> None:
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, content=picture("WEBP"))
    monkeypatch.setattr(base, "client", lambda **options: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    runtime = tmp_path / "runtime"
    assert signedread.keep_finds(runtime, "douyin.com", ROWS) == 2
    library = Library(runtime)
    dance, note = (library.get(i.id) for i in sorted(library.items(), key=lambda i: i.title))
    assert dance.picture and library.picture_path(dance.id) and not note.picture
    assert [(r.url.host, r.headers["referer"], "cookie" in r.headers) for r in asked] == [
        ("p3.douyinpic.example", ROWS[0]["link"], False)]


# ------------------------------------------------------------ the pages' own covers --

def test_one_sites_pages_are_asked_for_their_covers_one_at_a_time(tmp_path, monkeypatch, public) -> None:
    monkeypatch.setattr(catalog, "PAGE_PAUSE_S", 0)
    busy = {"now": 0, "most": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".jpg"):
            return httpx.Response(200, content=picture("JPEG"))
        busy["now"] += 1
        busy["most"] = max(busy["most"], busy["now"]) if request.url.host == "shore.example" else busy["most"]
        await asyncio.sleep(0.02)
        busy["now"] -= 1
        return httpx.Response(200, headers={"content-type": "text/html"}, content=(
            f'<meta property="og:image" content="https://img.shore.example/{request.url.path.strip("/")}.jpg">').encode())

    library = Library(tmp_path)
    finds = [base.find(f"https://shore.example/{n}", f"story {n}") for n in "abcd"]
    for found in finds:
        library.add(found.item)

    async def run() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await catalog._fill(http, library, finds, asyncio.Semaphore(6))
    assert asyncio.run(run()) == 4
    assert busy["most"] == 1
