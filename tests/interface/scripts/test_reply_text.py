"""The character's words as the chat draws them (chat.js, markdown-it): the tables, nested lists and code a cheap
model writes come out as tables, lists and code; what a reply holds of HTML, a script or a javascript: link shows
as text and runs nothing; a picture's address is a link and nothing is fetched; addresses stop at Chinese
punctuation; __init__, C:\\Users and 2 * 3 stay as written; a reply stopped inside its code still shows the code; a
click on an address the chat was not given shows the whole address first and opens it only on 打开."""
from __future__ import annotations

import pytest
from harness.page import measured

pytestmark = pytest.mark.browser
# A time the replies were said at (seconds), as a kept chat stores it.
SAID_AT = 1_763_700_000


def _replies(browser, app, *texts: str, lang: str = ""):
    """The page, in `lang` when one is named, with `texts` as the character's replies in the main chat's history, in
    order; links unread."""
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app, lang=lang)

    def with_replies(route) -> None:
        # The page's later asks are for what came since: nothing more.
        if "after=" in route.request.url:
            route.continue_()
            return
        answer = route.fetch().json()
        answer["messages"] = [{"role": "assistant", "text": text, "seq": n, "at": SAID_AT + n}
                              for n, text in enumerate(texts, 1)]
        answer["last"] = len(texts)
        route.fulfill(json=answer)

    page.page.route("**/api/chat/history*", with_replies)
    # The page asks the app to read each linked page; here none is read.
    page.page.route("**/api/link/preview*", lambda route: route.fulfill(json={"ok": False}))
    page.page.route("**/api/link/icon*", lambda route: route.fulfill(json={}))
    page.reload()
    says = page.page.locator(".chat-messages .line .say")
    says.nth(len(texts) - 1).wait_for()
    return page, [says.nth(n) for n in range(len(texts))]


def _html(node) -> str:
    return node.evaluate("(n) => n.innerHTML")


def test_a_table_is_drawn_as_a_table_with_its_columns_aligned(app, browser):
    page, (drawn,) = _replies(browser, app,
                              "| 方案 | 价格 | 说明 |\n|------|-----:|:----:|\n| 基础版 | ¥99 | 适合个人 |\n"
                              "| 专业版 | ¥299 | 含 `API` |")
    table = drawn.locator(".say-table table")
    assert table.locator("th").all_inner_texts() == ["方案", "价格", "说明"]
    assert table.locator("tbody tr").count() == 2
    assert table.locator("td code").inner_text() == "API"
    aligned = table.locator("tbody tr").first.locator("td").evaluate_all(
        "(cells) => cells.map((c) => getComputedStyle(c).textAlign)")
    assert aligned[1:] == ["right", "center"]
    assert page.errors == []


def test_a_nested_list_keeps_its_levels(app, browser):
    page, (drawn,) = _replies(browser, app,
                              "今天的安排：\n\n1. **上午**\n   - 跑步 30 分钟\n   - 吃早餐\n2. **下午**\n   - 写报告\n"
                              "     - 先列提纲\n3. 晚上休息")
    top = drawn.locator(":scope > ol > li")
    assert top.count() == 3
    assert top.nth(0).locator(":scope > strong").inner_text() == "上午"
    assert top.nth(0).locator(":scope > ul > li").all_inner_texts() == ["跑步 30 分钟", "吃早餐"]
    assert top.nth(1).locator(":scope > ul > li > ul > li").inner_text() == "先列提纲"
    assert page.errors == []


def test_code_with_its_language_is_drawn_as_code_with_a_copy_button(app, browser):
    page, (drawn,) = _replies(browser, app,
                              "可以这样写：\n\n```python\ndef add(a, b):\n    return a + b\n```\n\n运行即可。")
    box = drawn.locator(".code")
    assert box.locator(".code-lang").inner_text() == "python"
    assert box.locator("pre code").evaluate("(n) => n.textContent") == "def add(a, b):\n    return a + b"
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    box.locator(".code-copy").click()
    # Windows' clipboard gives the lines back with \r\n.
    copied = page.page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
    assert copied == "def add(a, b):\n    return a + b"
    assert [p.inner_text() for p in drawn.locator(":scope > p").all()] == ["可以这样写：", "运行即可。"]
    assert page.errors == []


def test_a_reply_stopped_inside_its_code_still_shows_the_code(app, browser):
    page, (drawn,) = _replies(browser, app, "代码如下：\n\n```js\nconst a = 1;\nconst b")
    assert drawn.locator(".code pre code").evaluate("(n) => n.textContent") == "const a = 1;\nconst b"
    assert page.errors == []


def test_an_address_stops_at_chinese_punctuation_and_opens_as_every_link_does(app, browser):
    page, (drawn,) = _replies(browser, app,
                              "详情见 https://example.com/docs/start，也可以看（https://example.org/faq）。")
    links = drawn.locator("a")
    assert links.evaluate_all("(ns) => ns.map((n) => [n.href, n.target, n.textContent])") == [
        ["https://example.com/docs/start", "_blank", "example.com"],
        ["https://example.org/faq", "_blank", "example.org"]]
    assert drawn.inner_text() == "详情见 example.com，也可以看（example.org）。"
    assert page.errors == []


def test_html_and_scripts_in_a_reply_show_as_text_and_run_nothing(app, browser):
    words = "这是<b>加粗</b>吗？<script>window.__ran = 1</script><img src=x onerror=\"window.__ran = 2\">"
    page, (drawn,) = _replies(browser, app, words)
    assert drawn.inner_text() == words
    assert drawn.locator("b, script, img").count() == 0
    assert page.page.evaluate("window.__ran") is None
    assert page.errors == []


def test_a_javascript_link_is_not_a_link_and_a_web_link_is(app, browser):
    page, (drawn,) = _replies(browser, app,
                              "[点这里](javascript:window.__ran=1) 和 [官网](https://example.com/home)")
    assert drawn.locator("a").evaluate_all("(ns) => ns.map((n) => [n.href, n.textContent, n.title])") == [
        ["https://example.com/home", "官网", "https://example.com/home"]]
    assert "点这里" in drawn.inner_text()
    assert page.errors == []


def test_a_picture_in_a_reply_is_a_link_and_is_never_fetched(app, browser):
    page, (drawn,) = _replies(browser, app, "![示意图](https://example.com/pic.png)")
    assert drawn.locator("img").count() == 0
    assert drawn.locator("a").evaluate_all("(ns) => ns.map((n) => [n.href, n.textContent])") == [
        ["https://example.com/pic.png", "示意图"]]
    assert page.refused == []


def test_code_like_words_stay_as_written_and_chinese_bold_is_bold(app, browser):
    page, (written, bold) = _replies(browser, app,
                                     "调用 __init__ 方法，路径是 C:\\Users\\me，2 * 3 = 6，x**2 + y**2，snake_case_name。",
                                     "**注意：**明天下雨。**提示（重要）**请带伞。")
    assert written.inner_text() == "调用 __init__ 方法，路径是 C:\\Users\\me，2 * 3 = 6，x**2 + y**2，snake_case_name。"
    assert written.locator("strong, em").count() == 0
    assert bold.locator("strong").all_inner_texts() == ["注意：", "提示（重要）"]
    assert bold.inner_text() == "注意：明天下雨。提示（重要）请带伞。"
    assert page.errors == []


def test_a_click_on_an_address_not_given_shows_it_whole_and_opens_it_only_on_open(app, browser):
    composed = "https://leak.example/c?d=%E5%A6%88%E5%A6%88%E7%9A%84%E7%94%9F%E6%97%A5"
    page, (drawn,) = _replies(browser, app, f"潮汐表见 https://example.com/tides ，更多内容请看[这里]({composed})。",
                              lang="zh")
    # The app says which addresses the chat was given (given.py); here the composed one is not.
    page.page.route("**/api/link/given*", lambda route: route.fulfill(
        json={"given": "leak.example" not in route.request.url}))
    drawn.locator("a", has_text="这里").click()
    ask = drawn.locator(".lk-ask")
    ask.wait_for()
    assert ask.locator(".lk-ask-address").inner_text() == "https://leak.example/c?d=妈妈的生日"
    assert ask.locator("button").all_inner_texts() == ["打开", "取消"]
    page.page.wait_for_timeout(300)
    assert page.refused == []
    ask.locator("button", has_text="取消").click()
    assert drawn.locator(".lk-ask").count() == 0 and page.refused == []
    drawn.locator("a", has_text="这里").click()
    with page.context.expect_page():
        drawn.locator(".lk-ask button", has_text="打开").click()
    page.page.wait_for_timeout(300)
    assert any(url.startswith("https://leak.example/c?d=") for url in page.refused)
    # A given address opens at once, with nothing shown first.
    with page.context.expect_page():
        drawn.locator("a", has_text="example.com").click()
    page.page.wait_for_timeout(300)
    assert drawn.locator(".lk-ask").count() == 0
    assert any(url.startswith("https://example.com/tides") for url in page.refused)
    assert page.errors == []


def test_headings_quotes_and_rules_are_drawn_and_a_line_of_dashes_is_a_rule(app, browser):
    page, (blocks, dashes) = _replies(browser, app, "## 总结\n\n> 引用一句话\n\n结束",
                                      "第一段\n---\n第二段")
    assert blocks.locator("h4").inner_text() == "总结"
    assert blocks.locator("blockquote").inner_text() == "引用一句话"
    assert dashes.evaluate("(n) => [...n.children].map((c) => c.tagName)") == ["P", "HR", "P"]
    # No blank lines between the blocks: the drawn reply is as tall as its blocks.
    assert "\n\n" not in _html(blocks)
    assert page.errors == []
