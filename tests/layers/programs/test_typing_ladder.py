"""Writing into another program's text field climbs the ladder UI automation tools climb (mibo/desk/uia.py): its
value, then the focus and real keys, then a real click and keys, then a click and a paste, the person's clipboard
put back; after every rung the field is read back, and that alone decides. Enter and the send button go the same
way. (2026-11-22: in an Electron chat program the value left the box showing its placeholder, focusing it failed
with "Target element cannot receive focus", and the errand gave up after repeating the same write.)"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

if sys.platform != "win32":
    pytest.skip("the app operates other programs on Windows only", allow_module_level=True)

from mibo.desk import hands, uia, win32
from mibo.desk.view import View

PLACEHOLDER = "Message or run a task, / commands, @ files or sessions"
WANT = "帮我打开桌面上的网易云音乐"  # copy: voice
CTRL, V, A_KEY, END = win32.VK["Ctrl"], ord("V"), ord("A"), win32.VK["End"]


# --- the ladder itself

def rung(log: list, name: str, does=None):
    def act():
        log.append(name)
        if isinstance(does, Exception):
            raise does
        if does:
            does()
    return name, act


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(uia, "SETTLE_S", 0)


@pytest.mark.parametrize("lands", range(4))
def test_each_rung_failing_in_turn_the_first_whose_read_back_holds_the_text_is_taken(lands):
    box, ran = {"text": PLACEHOLDER}, []
    names = [uia.BY_VALUE, uia.BY_KEYS, uia.BY_CLICK, uia.BY_PASTE]

    def write():
        box["text"] = WANT
    # Before the one that lands, each rung either raises (it took no focus) or runs and leaves the box as it was.
    rungs = [rung(ran, name, write if i == lands else
                  uia.Missed("Target element cannot receive focus.") if i % 2 else None)
             for i, name in enumerate(names)]
    took, holds, tried = uia.climb(rungs, lambda: box["text"], lambda h: h == WANT, again=False)
    assert took == names[lands] and holds == WANT
    assert ran == names[:lands + 1], "no rung runs after the one that took"
    assert len(tried) == lands and all(t.startswith(n) for t, n in zip(tried, names))
    assert all("cannot receive focus" in t for t in tried[1::2])


def test_a_rung_that_reports_success_but_reads_back_the_placeholder_has_not_taken():
    ran = []
    took, holds, tried = uia.climb([rung(ran, uia.BY_VALUE), rung(ran, uia.BY_KEYS)], lambda: PLACEHOLDER,
                                   lambda h: h == WANT, again=False)
    assert took == "" and holds == PLACEHOLDER and tried == [uia.BY_VALUE, uia.BY_KEYS]


def test_a_rung_that_changed_the_field_without_landing_ends_the_climb_so_nothing_goes_in_twice():
    box, ran = {"text": ""}, []

    def half():
        box["text"] += WANT[:3]
    rungs = [rung(ran, uia.BY_KEYS, half), rung(ran, uia.BY_CLICK, half), rung(ran, uia.BY_PASTE, half)]
    took, holds, _tried = uia.climb(rungs, lambda: box["text"], lambda h: WANT in h, again=False)
    assert took == "" and ran == [uia.BY_KEYS] and holds == WANT[:3]
    # A write of the whole text over what is there may go on: it only replaces itself.
    box["text"], ran[:] = "", []

    def whole_on_the_third():
        box["text"] = WANT if len(ran) == 3 else WANT[:3]
    rungs = [rung(ran, n, whole_on_the_third) for n in (uia.BY_VALUE, uia.BY_KEYS, uia.BY_CLICK)]
    took, _holds, _tried = uia.climb(rungs, lambda: box["text"], lambda h: h == WANT, again=True)
    assert took == uia.BY_CLICK


def test_a_field_with_nothing_to_read_takes_the_first_rung_that_runs_unproven():
    ran = []
    took, holds, tried = uia.climb([rung(ran, uia.BY_KEYS, uia.Missed("no focus")), rung(ran, uia.BY_CLICK)],
                                   None, lambda h: True, again=False)
    assert took == uia.BY_CLICK and holds == "" and len(tried) == 1


def test_a_refusal_on_a_rung_ends_the_write_at_once():
    ran = []
    with pytest.raises(uia.Refused):
        uia.climb([rung(ran, uia.BY_CLICK, uia.Refused("[refused] something else shows at the point")),
                   rung(ran, uia.BY_PASTE)], lambda: "", lambda h: False, again=False)
    assert ran == [uia.BY_CLICK]


def test_a_no_break_space_chromium_keeps_reads_as_the_space_typed():
    assert uia.same_text("hello\xa0world\n", "hello world")


# --- the view's writes over a stand-in Electron message box

class Box:
    """An Electron message box as UI Automation sees it: empty, it reads as its placeholder; what each way of
    writing does to it is set per case."""

    def __init__(self, value=False, focus=False, click=True, keys=True, paste=True, half=False):
        self.takes = {"value": value, "focus": focus, "click": click, "keys": keys, "paste": paste}
        self.half, self.text, self.focused, self.selected = half, "", False, False
        self.clipboard, self.chords = [("theirs", b"x")], []

    def read(self) -> str:
        return self.text or PLACEHOLDER

    def put(self, text: str) -> None:
        if self.selected:
            self.text, self.selected = "", False
        self.text += text[:len(text) // 2] if self.half else text

    def chord(self, vks: list[int]) -> None:
        self.chords.append(vks)
        if vks == [CTRL, A_KEY]:
            self.selected = True
        elif vks == [CTRL, V] and self.focused and self.takes["paste"]:
            self.put(dict(self.clipboard)["text"])

    def type(self, text: str) -> None:
        if self.focused and self.takes["keys"]:
            self.put(text)


class Element:
    def __init__(self, box: Box):
        self.box = box

    def GetCurrentPattern(self, pattern):
        box = self.box

        def set_value(text):
            if box.takes["value"]:
                box.text = text
        return SimpleNamespace(SetValue=set_value, Invoke=lambda: None)


@pytest.fixture
def electron(monkeypatch):
    """(a View over one message box [46], the box): every window call faked, nothing sent to this computer."""
    def make(role="textbox", **takes):
        box = Box(**takes)
        v = View.__new__(View)
        v.nodes = {46: uia.Node(el=Element(box), role=role, name=PLACEHOLDER, auto="", cls="", pid=1, enabled=True,
                                focused=False, secret=False, rect=(0, 0, 300, 40), hwnd=0, patterns=["value"],
                                readonly=False, top=7, parent=None, cells=[])}
        v.grid, v.forwarded, v.clicks = {}, False, []
        v.live = lambda i: i
        v.text_of = lambda i: box.read()
        v.forward = lambda: setattr(v, "forwarded", True)
        v._focused_ok = lambda typing: None
        v._type = box.type
        v._act = lambda op, ident, body, wait=0: f"[ok] {op} {v.describe(ident)}{body()}"

        def focus_on(node, click):
            if click and node.role not in uia.FIELDS:
                raise uia.Missed(f"it is a {node.role}, not a text field, so it is not clicked into")
            if not box.takes["click" if click else "focus"]:
                raise uia.Missed("it takes no focus from UI Automation: Target element cannot receive focus.")
            if click:
                v.clicks.append(46)
            box.focused = True
        v._focus_on = focus_on
        monkeypatch.setattr(win32, "chord", box.chord)
        monkeypatch.setattr(win32, "clipboard_save", lambda: list(box.clipboard))
        monkeypatch.setattr(win32, "clipboard_text", lambda text: [("text", text)])
        monkeypatch.setattr(win32, "clipboard_put", lambda items: setattr(box, "clipboard", list(items)))
        return v, box
    monkeypatch.setattr(win32, "in_combo", lambda hwnd: False)
    monkeypatch.setattr(win32, "edit_box", lambda hwnd: False)
    monkeypatch.setattr(win32, "multiline", lambda hwnd: False)
    monkeypatch.setattr(uia, "automation", lambda: SimpleNamespace(ValuePattern=SimpleNamespace(Pattern="value"),
                                                                    InvokePattern=SimpleNamespace(Pattern="invoke")))
    return make


def test_the_electron_box_of_the_errand_is_set_by_a_click_and_typed_keys_and_read_back(electron):
    view, box = electron()
    line = view.set_value(46, WANT)
    assert box.text == WANT and view.clicks == [46]
    assert "typed after a click on it" in line and "read back" in line
    assert "its value" in line and "cannot receive focus" in line, "the line says which rungs did not take"
    assert any(word in line for word in hands.PROVED), "the hands count it as read back"


def test_where_typed_keys_do_not_land_the_text_is_pasted_and_the_persons_clipboard_put_back(electron):
    view, box = electron(keys=False)
    line = view.set_value(46, WANT)
    assert box.text == WANT and "pasted after a click on it" in line
    assert box.clipboard == [("theirs", b"x")]


def test_a_box_that_takes_nothing_fails_once_with_every_rung_and_what_to_do_instead(electron):
    view, box = electron(click=False, paste=False)
    with pytest.raises(uia.Refused) as no:
        view.set_value(46, WANT)
    line = str(no.value)
    assert box.text == ""
    for name in (uia.BY_VALUE, uia.BY_KEYS, uia.BY_CLICK, uia.BY_PASTE):
        assert name in line
    assert "placeholder" in line and "will not take either" in line and "ask_person" in line


def test_typing_that_lands_half_is_not_typed_again(electron):
    view, box = electron(focus=True, half=True)
    with pytest.raises(uia.Refused) as no:
        view.type(46, WANT)
    assert box.text == WANT[:len(WANT) // 2] and "nothing goes in twice" in str(no.value)


def test_type_and_paste_climb_from_the_focus_to_a_click(electron):
    view, box = electron()
    assert "read back and it is there" in view.type(46, WANT) and box.text == WANT
    view, box = electron()
    line = view.paste(46, WANT)
    assert box.text == WANT and uia.BY_FOCUS_PASTE in line and box.clipboard == [("theirs", b"x")]


def test_appending_to_an_empty_box_does_not_take_its_placeholder_for_text(electron):
    view, box = electron()
    view.set_value(46, WANT, append=True)
    assert box.text == WANT and box.chords[0] == [CTRL, END]


# --- Enter and the send button go the same way

def test_enter_named_for_the_box_clicks_into_it_when_it_takes_no_focus(electron):
    view, box = electron()
    line = view.key("Enter", 46)
    assert box.chords[-1] == [win32.VK["Enter"]] and view.clicks == [46] and "after a click on it" in line


def test_a_key_for_a_button_that_takes_no_focus_clicks_nothing(electron):
    view, box = electron(role="button")
    with pytest.raises(uia.Refused) as no:
        view.key("Enter", 46)
    assert view.clicks == [] and box.chords == [] and "would not go into" in str(no.value)


def press_view(electron, monkeypatch, changes):
    view, _box = electron(role="button")
    node = view.nodes[46]
    node.patterns = ["invoke"]

    def broken(pattern):
        return SimpleNamespace(Invoke=lambda: (_ for _ in ()).throw(RuntimeError("Operation is not valid")))
    node.el.GetCurrentPattern = broken
    view.snapshot = dict
    view.changes = lambda before, after: changes
    view._point = lambda n: (150, 20)
    clicked = []
    monkeypatch.setattr(win32, "click_at", lambda x, y, double=False, right=False: clicked.append((x, y)))
    return view, clicked


def test_a_send_button_whose_own_action_fails_is_clicked_at_its_point(electron, monkeypatch):
    view, clicked = press_view(electron, monkeypatch, [])
    line = view.invoke(46)
    assert clicked == [(150, 20)] and "once its own action failed" in line


def test_a_send_button_that_answered_an_error_but_changed_the_window_is_not_clicked_again(electron, monkeypatch):
    view, clicked = press_view(electron, monkeypatch, ["the field is empty"])
    line = view.invoke(46)
    assert clicked == [] and "pressed once" in line


def test_the_hands_send_a_key_into_the_field_it_names(tmp_path, monkeypatch):
    sent = []

    class View:
        hwnd, seen, serial, menus, unnamed, words = 7, (), 1, {}, [], {}

        def __init__(self):
            self.nodes = {46: uia.Node(role="textbox", name="Message", cls="", parent=None, top=7, patterns=("value",),
                                       enabled=True, cells=(), auto="", el=None, secret=False, rect=(0, 0, 9, 9),
                                       readonly=False)}

        def describe(self, i):
            return f"[{i}] textbox"

        def live(self, i):
            return i

        def node(self, i):
            return self.nodes[i]

        def texts(self, top):
            return ""

        def forward(self):
            pass

        def key(self, keys, ident=None):
            sent.append((keys, ident))
            return f"[ok] key {keys}"
    monkeypatch.setattr(win32, "title_of", lambda hwnd: "Lumen")
    hand = hands.Hands(tmp_path, ask=lambda card: {"yes": False})
    hand.task, hand.view, hand.program = "在消息框里按 End", View(), {"name": "Lumen", "exe": "C:\\Apps\\Lumen.exe"}  # copy: voice
    monkeypatch.setattr(hand, "_access_key", lambda keys, focused, top: None)
    done = hand.act({"do": "key", "key": "End", "name": "Message"})
    assert done["status"] == "ok" and sent == [("End", 46)]
