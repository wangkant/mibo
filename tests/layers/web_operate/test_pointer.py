"""The pointer and the page's drawn parts in act (surface.py's steps, web/operate.Hands, web/pageops.Page), as
Playwright MCP, Playwright and Stagehand take them: a drag from a ref or a point to a ref or a point, through
route points; a point from a ref's top left (Playwright's click position); text selected by what it says; keys
by Playwright's names and the short ones; a clickable bar of short parts read as one control a part; a control
with no words named by its picture, its id or its class; a drawing given with its shapes and a row of colour
boxes with their colours, each with a ref; a text area's text whole. Every press still goes through the gate,
judged by the control the person would see pressed: a click or a drag at a point of a ref as that ref, a bare
point as the control the look lists there and a point in another site's frame as a press nothing reads, a part of
a clickable with what the clickable is, a drawn part by its own name and never by its colour; a point outside the
view presses nothing, a secret field's text is never selected, and a text area that holds a code is hidden in the
look and in a read.

The pages are the operating benchmark's (tools/opsite P1-P4) and the tests' own, served by the stand-in site to
headless Chromium; the steps are scripted as the act tool gives them, the cards answered by the test."""
from __future__ import annotations

import asyncio
import json
import re
import time
from types import SimpleNamespace

import pytest

from mibo import installed_browser
from mibo.web import gate, operate, pageops
from mibo.web.tabs import PaneTab

BROWSER = installed_browser.find_browser()


@pytest.fixture(scope="module")
def pane():
    try:
        import playwright  # noqa: F401
    except ImportError as missing:
        pytest.skip(f"no Playwright: {missing}")
    from harness.pane import Pane
    started = Pane.start(BROWSER)
    if started is None:
        pytest.skip("no headless browser")
    yield started
    started.stop()


@pytest.fixture
def on(pane, site, tmp_path):
    """`on(path, no)`: the page open in a tab with its Hands, every card answered yes but those of the kinds in
    `no`; `.cards` the
    cards shown, `.steps(*steps)` runs act steps (refs by name from the last look, as the test finds them),
    `.look()` the state, `.check(task)` the site's verdict."""
    loop = asyncio.new_event_loop()
    opened = []

    def open_(path: str, no: tuple = ()):
        cards: list[dict] = []

        async def ask(card: dict) -> dict:
            cards.append(card)
            return {"yes": card["kind"] not in no, "never": False}
        tab = pane.open_tab(site.url + path)
        hands = operate.Hands(PaneTab(pane, tab), ask=ask, allowed=gate.Allowed(tmp_path / "allow"),
                              attended=lambda: True)
        opened.append(hands)

        def look() -> str:
            return loop.run_until_complete(hands.look())["state"]

        def steps(*given: dict) -> dict:
            return loop.run_until_complete(hands.steps([operate.action_of({"what": "step", **s}) for s in given]))

        def ref(pattern: str) -> int:
            """The ref of the first line of the last look matching `pattern`."""
            line = next(x for x in hands.page.lines if re.search(pattern, x))
            return int(re.match(r"\*?\[(\d+)\]", line).group(1))
        def check(task: str, wait: float = 5) -> dict:
            """The site's verdict once what a yes on a card let go has reached it (`wait` seconds at most)."""
            began = time.monotonic()
            while not (verdict := site.serve.tasks.check(task, site.state()))["ok"] and time.monotonic() - began < wait:
                time.sleep(0.1)
            return verdict
        return SimpleNamespace(hands=hands, cards=cards, look=look, steps=steps, ref=ref, check=check,
                               page=lambda js: pane.cdp("Runtime.evaluate", {"expression": js, "returnByValue": True},
                                                        tab=tab)["result"].get("value"))
    yield open_
    for hands in opened:
        loop.run_until_complete(hands.close())
    loop.close()


@pytest.mark.browser
@pytest.mark.slow
def test_a_slider_drawn_from_divs_is_dragged_by_points_and_its_save_asks_first(on):
    p = on("/t/t43-volume.html")
    state = p.look()
    # The knob has no name and no role: it is shown by its class, as a small part that takes the focus.
    knob = p.ref(r"generic \{knob\}")
    # From 30 to 70 is 80 pixels right of the knob's centre, which is 10,10 from its top left.
    got = p.steps({"do": "drag", "ref": knob, "to": knob, "to_x": 90, "to_y": 10},
                  {"do": "click", "ref": p.ref(r'button "保存"')})
    assert got["status"] == "ok", got["lines"]
    assert p.page("value.textContent") in ("69", "70", "71"), state
    assert len(p.cards) == 1 and p.check("P1")["ok"], p.check("P1")


@pytest.mark.browser
@pytest.mark.slow
def test_reply_and_forward_in_one_bar_are_a_control_each_and_the_send_arrow_is_named_by_its_picture(on):
    p = on("/t/t44-mailbar.html")
    state = p.look()
    assert re.search(r'clickable "回复"', state) and re.search(r'clickable "转发"', state), state
    assert "回复 转发" not in state
    p.steps({"do": "click", "ref": p.ref(r'clickable "转发"')})
    state = p.look()
    # A picture drawn by CSS and the words of its id name the send arrow, as browser-use shows an id.
    send = p.ref(r"clickable \{send forward\}")
    got = p.steps({"do": "type", "ref": p.ref(r"textbox"), "text": "bob@example.com"},
                  {"do": "click", "ref": send})
    assert got["status"] == "ok", got["lines"]
    # The gate reads 转发 as a repost and asks about it too; the send is put to the person with what it sends.
    assert [c["kind"] for c in p.cards][-1] == "send" and p.cards[-1]["text"] == "bob@example.com"
    assert p.check("P2")["ok"], p.check("P2")


@pytest.mark.browser
@pytest.mark.slow
def test_a_drawing_comes_with_its_shapes_and_colour_boxes_and_a_point_from_its_top_left_lands(on):
    p = on("/t/t45-board.html")
    state = p.look()
    board = p.ref(r"drawing svg")
    # A shape's point is its centre, said as one, so it is not read as a corner.
    assert re.search(r"circle red #e53935 28x28, its centre at 41,41 of \[\d+\]", state), state
    assert re.search(r"rect grey #333333 \d+x\d+, its centre at 186,66 of \[\d+\]", state), state
    grey = p.ref(r"box grey #808080")
    # The red dot is dragged by a point of the drawing, the frame taken by its ref.
    got = p.steps({"do": "click", "ref": grey},
                  {"do": "drag", "ref": board, "x": 40, "y": 40, "to": p.ref(r"rect grey")},
                  {"do": "click", "ref": p.ref(r'button "提交"')})
    assert got["status"] == "ok", got["lines"]
    assert p.check("P3")["ok"], p.check("P3")


@pytest.mark.browser
@pytest.mark.slow
def test_a_drag_drawn_through_route_points_passes_each_of_them(on):
    p = on("/t/t45-board.html")
    p.look()
    p.page("window.seen = []; document.addEventListener('mousemove', (e) => e.buttons && seen.push(e.clientX))")
    board, frame = p.ref(r"drawing svg"), p.ref(r"rect grey")
    got = p.steps({"do": "drag", "ref": board, "x": 60, "y": 100, "to": frame, "to_x": 35, "to_y": 35,
                   "route": [[100, 120], [140, 120], [180, 110]]})
    assert got["status"] == "ok", got["lines"]
    # What moved is inside the drawing: the drawing standing still is not said as a drag that failed.
    assert "did not move" not in got["lines"][0], got["lines"]
    left = p.page("board.getBoundingClientRect().left")
    assert [round(x - left) for x in p.page("seen")][:3] == [100, 140, 180]
    assert p.page("+blue.getAttribute('cx')") == pytest.approx(185, abs=2)


@pytest.mark.browser
@pytest.mark.slow
def test_a_drag_from_a_point_of_a_drawing_lets_go_at_a_point_of_the_same_drawing_when_no_end_ref_is_given(on):
    p = on("/t/t45-board.html")
    p.look()
    got = p.steps({"do": "drag", "ref": p.ref(r"drawing svg"), "x": 60, "y": 100, "to_x": 185, "to_y": 65})
    assert got["status"] == "ok", got["lines"]
    assert (p.page("+blue.getAttribute('cx')"), p.page("+blue.getAttribute('cy')")) == \
        (pytest.approx(185, abs=2), pytest.approx(65, abs=2))


@pytest.mark.browser
def test_words_are_selected_where_the_page_shows_them_and_the_page_quotes_them(on):
    p = on("/t/t46-quote.html")
    p.look()
    got = p.steps({"do": "select_text", "text": "周末去爬山"}, {"do": "click", "ref": p.ref(r'button "引用所选"')})
    assert got["status"] == "ok", got["lines"]
    assert len(p.cards) == 1 and p.check("P4")["ok"], p.check("P4")


@pytest.mark.browser
@pytest.mark.slow
def test_a_drag_that_starts_on_a_send_arrow_is_put_to_the_person_as_its_press_would_be(on):
    p = on("/t/t44-mailbar.html", no=("send",))
    p.look()
    p.steps({"do": "click", "ref": p.ref(r'clickable "转发"')})
    p.look()
    p.steps({"do": "type", "ref": p.ref(r"textbox"), "text": "bob@example.com"})
    got = p.steps({"do": "drag", "ref": p.ref(r"clickable \{send forward\}"), "x": 10, "y": 10, "to_x": 5, "to_y": 5})
    assert p.cards[-1]["kind"] == "send" and got["status"] == "declined", got["lines"]
    # Declined on the card: the press never happened, so there is nothing to wait for.
    assert not p.check("P2", wait=0)["ok"]


@pytest.mark.browser
def test_a_point_outside_the_view_presses_nothing(on):
    p = on("/t/t46-quote.html")
    p.look()
    p.page("window.downs = 0; document.addEventListener('mousedown', () => downs++)")
    got = p.steps({"do": "click", "x": 5000, "y": 40})
    assert got["status"] == "failed" and "outside the view" in got["lines"][0]
    assert p.page("downs") == 0


@pytest.mark.browser
def test_text_in_a_secret_field_is_never_selected(on, site):
    site.put("/secret", '<!doctype html><meta charset="utf-8"><title>s</title><label>Password '
                        '<input id="pw" type="password" value="hunter22"></label>')
    p = on("/secret")
    p.look()
    got = p.steps({"do": "select_text", "ref": p.ref(r"\[secret\]")})
    assert got["status"] == "refused"
    assert p.page("pw.selectionEnd - pw.selectionStart") == 0


@pytest.mark.browser
@pytest.mark.slow
def test_a_long_text_area_is_shown_and_read_whole(on, site):
    words = " ".join(f"word{n}" for n in range(300))
    site.put("/long", f'<!doctype html><meta charset="utf-8"><title>l</title><textarea id="t">{words}</textarea>'
                      f'<input aria-label="Answer">')
    p = on("/long")
    assert words in p.look()
    got = p.steps({"do": "read", "question": "the text"})
    assert words in got["texts"][0]["text"]


# Controls whose press the gate must judge by what the person sees: an icon button and a buy button whose words sit
# in a child, a counter that answers a double click and a right click, a clickable bar with a destructive class split
# into two parts, an icon with its label, colour boxes that are buttons by their role and name, a nameless colour
# box with a handler, a drawn pin with its own label, a frame from another site, and an svg icon named by its title. Each press is heard by the
# site as GET /hit?<what>.
CONTROLS = """<!doctype html><meta charset="utf-8"><title>c</title>
<style>.bar{cursor:pointer;display:flex;gap:8px;width:220px}.bar span{width:80px}
.sw{display:inline-block;width:24px;height:24px;margin:2px}</style>
<button id="del" aria-label="Delete draft" onclick="hit('del')"><svg width="24" height="24"><path d="M2 2h20v20H2z"
 fill="#888"/></svg></button>
<button id="buy" onclick="hit('buy')"><span>Buy now</span></button>
<button id="count" ondblclick="hit('double')" oncontextmenu="hit('menu'); return false">Count</button>
<div class="bar btn-delete" id="wipe" onclick="hit('wipe')"><span>清理</span><span>全部</span></div>
<div class="bar btn-remove" id="drop" onclick="hit('drop')"><svg width="16" height="16"><rect width="16" height="16"
 fill="#999"/></svg><span>整理</span></div>
<div><span class="sw" role="button" aria-label="Delete photo" style="background:#e53935" onclick="hit('photo')"></span><span
 class="sw" role="button" aria-label="Delete album" style="background:#808080" onclick="hit('album')"></span></div>
<div><span class="sw" style="background:#1e88e5" onclick="hit('blue')"></span><span class="sw" style="background:#43a047"
 onclick="hit('green')"></span></div>
<span id="gear" style="cursor:pointer;display:inline-block" onclick="hit('gear')"><svg width="20" height="20"><title>Account
 settings</title><circle cx="10" cy="10" r="8" fill="#555"/></svg></span>
<svg id="map" width="80" height="60"><circle cx="30" cy="30" r="12" fill="#777777" aria-label="Remove pin"
 onclick="hit('pin')"/></svg>
<iframe id="away" src="AWAY/inner" width="200" height="80"></iframe>
<script>function hit(w) { fetch('/hit?' + w); }</script>"""
INNER = """<!doctype html><meta charset="utf-8"><button style="width:180px;height:60px"
 onclick="fetch('/hit?frame')">Go</button>"""


@pytest.fixture
def controls(on, site):
    site.put("/controls", CONTROLS.replace("AWAY", site.url.replace("127.0.0.1", "localhost")))
    site.put("/inner", INNER)
    # Every card is said no to: whatever a card stops is never pressed.
    p = on("/controls", no=gate.KINDS)
    p.look()
    return p


def hits(site) -> list[str]:
    return sorted({line.split("?", 1)[1] for line in site.log if line.startswith("GET /hit?")})


@pytest.mark.browser
def test_a_click_at_a_point_of_a_ref_is_judged_by_the_ref_as_a_click_on_it_alone_would_be(controls, site):
    p = controls
    for ref, kind in ((p.ref(r'button "Delete draft"'), "delete"), (p.ref(r'button "Buy now"'), "order")):
        got = p.steps({"do": "click", "ref": ref, "x": 12, "y": 10})
        assert got["status"] == "declined" and p.cards[-1]["kind"] == kind, got["lines"]
    time.sleep(0.5)
    assert hits(site) == []


@pytest.mark.browser
def test_a_double_or_right_click_at_a_point_of_a_ref_is_that_click(controls, site):
    p = controls
    count = p.ref(r'button "Count"')
    p.steps({"do": "click", "ref": count, "x": 5, "y": 5, "double": True})
    p.steps({"do": "click", "ref": count, "x": 5, "y": 5, "right": True})
    # Each press is watched a moment after it, so what it set off has arrived.
    assert hits(site) == ["double", "menu"]


@pytest.mark.browser
def test_a_press_at_a_bare_point_is_judged_by_the_control_there_and_one_in_another_sites_frame_asks(controls, site):
    p = controls
    at = json.loads(p.page("JSON.stringify(del.getBoundingClientRect())"))
    got = p.steps({"do": "click", "x": at["x"] + 12, "y": at["y"] + 10})
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "delete", got["lines"]
    frame = json.loads(p.page("JSON.stringify(away.getBoundingClientRect())"))
    got = p.steps({"do": "click", "x": frame["x"] + 90, "y": frame["y"] + 40})
    # The card names a press nothing reads "press".
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "press", got["lines"]
    # A drag that goes down in the frame asks as its press would.
    got = p.steps({"do": "drag", "x": frame["x"] + 90, "y": frame["y"] + 40, "to_x": frame["x"] + 20,
                   "to_y": frame["y"] + 20})
    assert got["status"] == "declined", got["lines"]
    time.sleep(0.5)
    assert hits(site) == []


@pytest.mark.browser
def test_parts_of_a_clickable_keep_what_it_is_and_drawn_parts_are_judged_by_their_names(controls, site):
    p = controls
    state = p.look()
    # A bar of two worded parts is split; each part still carries the bar's destructive class.
    got = p.steps({"do": "click", "ref": p.ref(r'clickable "全部"')})
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "delete", got["lines"]
    # An icon beside its label is one control, not two.
    assert re.search(r'clickable "整理"', state) and not re.search(r"clickable \{", state.split("整理")[0][-80:])
    got = p.steps({"do": "click", "ref": p.ref(r'clickable "整理"')})
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "delete", got["lines"]
    # Colour boxes that are buttons by their role and name keep their own lines.
    assert 'button "Delete photo"' in state and 'button "Delete album"' in state, state
    got = p.steps({"do": "click", "ref": p.ref(r'button "Delete photo"')})
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "delete", got["lines"]
    # A shape is judged by its own label, not by the shape and colour words the look gives it.
    got = p.steps({"do": "click", "ref": p.ref(r"circle .*#777777")})
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "delete", got["lines"]
    # A nameless colour box that answers a press asks as a press nothing reads.
    got = p.steps({"do": "click", "ref": p.ref(r"box blue")})
    assert got["status"] == "declined" and p.cards[-1]["kind"] == "press", got["lines"]
    # An svg icon's own title names it.
    assert re.search(r"clickable \{Account settings", state), state
    time.sleep(0.5)
    assert hits(site) == []


@pytest.mark.browser
def test_a_text_area_that_holds_a_code_is_hidden_in_the_look_and_in_a_read(on, site):
    site.put("/codes", '<!doctype html><meta charset="utf-8"><title>c</title>'
                       '<textarea aria-label="Verification code">482913</textarea>'
                       '<textarea autocomplete="one-time-code">771234</textarea>'
                       '<textarea id="note">plain words here</textarea><p>Codes</p>')
    p = on("/codes")
    state = p.look()
    got = p.steps({"do": "read", "question": "what is on the page"})
    read = got["texts"][0]["text"]
    assert "plain words here" in state and "plain words here" in read
    assert not re.search(r"482913|771234", state + read), (state, read)


@pytest.mark.browser
def test_a_hover_by_ref_alone_waits_for_its_target_to_show(on, site):
    site.put("/menu", '<!doctype html><meta charset="utf-8"><title>m</title><p>Top</p>'
                      '<button id="item" style="margin:60px" onmouseover="fetch(\'/hit?over\')">More</button>')
    p = on("/menu")
    p.look()
    p.page("item.style.display = 'none'; setTimeout(() => { item.style.display = ''; }, 500)")
    got = p.steps({"do": "hover", "ref": p.ref(r'button "More"')})
    time.sleep(0.3)
    assert got["status"] == "ok" and hits(site) == ["over"], got["lines"]


def test_keys_are_taken_by_playwright_names_and_by_the_short_ones():
    assert pageops.chord("Left")[0] == "ArrowLeft" and pageops.chord("shift+Down")[0] == "Shift+ArrowDown"
    assert [pageops.chord(k)[0] for k in ("Esc", "PgDn", "KeyA", "Digit1", "F5", "Backquote")] == \
        ["Escape", "PageDown", "a", "1", "F5", "`"]
    assert pageops.chord("ControlOrMeta+a")[1] in (2, 4)
    with pytest.raises(ValueError):
        pageops.chord("Sideways")
