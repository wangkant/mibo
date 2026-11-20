"""A picture of the pane's page or of one granted window, and nothing else.

The pane: DevTools' own Page.captureScreenshot of the viewport (the tab shape
of web/tabs.py, so the person's pane and the headless visitor are the same).
A window: the window drawn by itself (win32.capture, PrintWindow), with the
same program's menus and dialogs that lie over it pasted on top, never what is
behind or beside it, and nothing at all while another program covers it,
while it is minimised or hidden, or when it asked Windows to keep it out of
captures (SetWindowDisplayAffinity, which PrintWindow would ignore).

DPI: the app is not per-monitor aware, so on a 150% monitor Windows would hand
it scaled rectangles. Every Win32 and UI Automation call here runs on a thread
switched to per-monitor-aware v2 for the duration (`aware()`), so the window's
rect, its picture, UI Automation's boxes, the hit test and SendInput all speak
physical pixels on every monitor; the picture is then scaled by one factor `k`
and points come back as origin + p / k.

Password fields the structure knows of (UI Automation's IsPassword, an edit
named like a password or a code; the page's password, card and one-time-code
inputs) are painted over before the picture leaves this module. That is best
effort: a password drawn on a canvas is not known to any structure.
"""
from __future__ import annotations

import base64
import contextlib
import ctypes
import io
import os

from PIL import Image

from ..desk import win32
from ..web.pageops import SECRET_LABEL, SECRET_SELECTOR
from .frame import LONG_EDGE, Frame, fit, paint_over

user32 = win32.user32
user32.GetDpiForWindow.argtypes = [win32.HWND]
user32.GetDpiForWindow.restype = ctypes.c_uint
user32.GetWindowDisplayAffinity.argtypes = [win32.HWND, ctypes.POINTER(win32.DWORD)]
GW_HWNDPREV = 3
# Never counted as covering: drop shadows, the input method's windows, click-through overlays (below).
NOT_COVERING = {"SysShadow", "IME", "MSCTFIME UI", "tooltips_class32", "Progman", "WorkerW"}
WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
# Another program over more than this share of the window, and no picture is taken.
COVERED_SHARE = 0.005


class Refused(Exception):
    """No picture: the text says why, as a line for the loop."""


@contextlib.contextmanager
def aware():
    """Physical pixels on this thread for the duration, whatever the process is."""
    old = user32.SetThreadDpiAwarenessContext(win32.PER_MONITOR_V2)
    try:
        yield
    finally:
        user32.SetThreadDpiAwarenessContext(old)


# --- the pane

SECRETS_JS = """(sel) => {
  const label = new RegExp(%s, 'i');
  const out = [];
  for (const e of document.querySelectorAll('input,textarea')) {
    const words = [e.name, e.id, e.placeholder, e.getAttribute('aria-label'), e.title].filter(Boolean).join(' ');
    if (!(e.matches(sel) || label.test(words))) continue;
    const r = e.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) out.push([r.x, r.y, r.width, r.height]);
  }
  return out;
}""" % repr(SECRET_LABEL.pattern)


async def pane(tab, long_edge: int = LONG_EDGE) -> Frame:
    """The viewport of a tab (web/tabs.Tab: the person's pane or the headless visitor) as the person sees it,
    in CSS pixels of the viewport."""
    metrics = await tab.cdp("Page.getLayoutMetrics", {})
    view = metrics.get("cssVisualViewport") or metrics.get("visualViewport") or {}
    wide, high = float(view.get("clientWidth") or 1280), float(view.get("clientHeight") or 800)
    secrets = await tab.evaluate(SECRETS_JS, SECRET_SELECTOR) or []
    shot = await tab.cdp("Page.captureScreenshot", {"format": "png", "clip": {
        "x": float(view.get("pageX") or 0), "y": float(view.get("pageY") or 0), "width": wide, "height": high,
        "scale": 1}})
    image = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
    # The device's pixels per CSS pixel, measured on the picture rather than assumed.
    ratio = image.size[0] / wide
    paint_over(image, secrets, (0, 0), ratio)
    image, k = fit(image, long_edge)
    url = await tab.evaluate("() => location.href")
    return Frame(image, "pane", (0.0, 0.0), ratio * k, (round(wide), round(high)), url=str(url or ""),
                 secrets=[tuple(b) for b in secrets])


# --- a window

def _overlap(a: tuple, b: tuple) -> int:
    wide = min(a[2], b[2]) - max(a[0], b[0])
    high = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, wide) * max(0, high)


def _above(hwnd: int):
    h = user32.GetWindow(hwnd, GW_HWNDPREV)
    while h:
        yield h
        h = user32.GetWindow(h, GW_HWNDPREV)


def covering(hwnd: int, pids: set[int], own: set[int]) -> tuple[list[int], str]:
    """The program's own windows lying over the target (menus, dialogs), and what covers it otherwise ("" when
    nothing): another program's shown window over more than COVERED_SHARE of it."""
    box = win32.rect(hwnd)
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    mine: list[int] = []
    for h in _above(hwnd):
        if not win32.shown(h) or win32.class_of(h) in NOT_COVERING:
            continue
        ex = user32.GetWindowLongPtrW(h, win32.GWL_EXSTYLE)
        if ex & WS_EX_TRANSPARENT and ex & WS_EX_LAYERED:
            continue
        over = _overlap(box, win32.rect(h))
        if not over:
            continue
        pid = win32.pid_of(h)
        belongs = win32.root_owner(h) == hwnd or win32.owner_of(h) == hwnd or win32.class_of(h) == "#32768" or (
            win32.owner_of(h) == 0 and win32.popup(h))
        if pid in pids and belongs:
            mine.append(h)
        elif pid not in own and over / area > COVERED_SHARE:
            # Another program, or another main window of the same one.
            return mine, os.path.basename(win32.exe_of(pid)) or "a protected program"
    return mine, ""


def _excluded(hwnd: int) -> bool:
    """The window asked to be kept out of pictures (WDA_MONITOR or WDA_EXCLUDEFROMCAPTURE)."""
    value = win32.DWORD()
    return bool(user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(value))) and value.value != 0


def secret_boxes(hwnd: int) -> list[tuple]:
    """Physical boxes of the window's password fields, as UI Automation knows them (call inside aware())."""
    from ..desk import uia
    A = uia.automation()
    el = uia.element(hwnd)
    found = []
    E = A.AutomationElement
    for cond in (A.PropertyCondition(E.IsPasswordProperty, True),
                 A.PropertyCondition(E.ControlTypeProperty, A.ControlType.Edit)):
        for e in el.FindAll(A.TreeScope.Descendants, cond):
            c = e.Current
            if c.IsPassword or SECRET_LABEL.search(f"{c.Name} {c.AutomationId}"):
                r = c.BoundingRectangle
                if r.Width > 0 and r.Height > 0:
                    found.append((r.X, r.Y, r.Width, r.Height))
    return list(dict.fromkeys(found))


def window(hwnd: int, pids: set[int], own: set[int] | None = None, long_edge: int = LONG_EDGE) -> Frame:
    """One granted window (`pids` its program's processes; `own` this app's, whose strip may lie over it), in
    physical screen pixels. Raises Refused when no picture may be taken."""
    own = win32.own_tree() if own is None else own
    with aware():
        if not win32.alive(hwnd):
            raise Refused("[failed] the window is gone")
        if not win32.shown(hwnd):
            raise Refused("[refused] the window is minimised or hidden; nothing was captured")
        if _excluded(hwnd):
            raise Refused("[refused] this window asks Windows to keep it out of pictures; nothing was captured")
        mine, other = covering(hwnd, pids, own)
        if other:
            raise Refused(f"[refused] another program ({other}) covers the window; nothing was captured until "
                          f"the window is in view")
        image, (left, top) = win32.capture(hwnd)
        box = win32.rect(hwnd)
        for h in reversed(mine):
            if _excluded(h):
                raise Refused("[refused] a window of the program over it asks to be kept out of pictures")
            part, (x, y) = win32.capture(h)
            image.paste(part, (x - left, y - top))
        dpi = user32.GetDpiForWindow(hwnd)
        try:
            secrets = secret_boxes(hwnd)
        except Exception:
            # No automation tree to ask: nothing known to paint over (the module's words say so).
            secrets = []
    paint_over(image, secrets, (left, top))
    real = image.size
    image, k = fit(image, long_edge)
    return Frame(image, "window", (float(left), float(top)), k, real, hwnd=hwnd, rect=box, dpi=dpi,
                 secrets=secrets)


def stale(frame: Frame) -> str:
    """Why a window's picture no longer maps to the screen ("" when it still does): moved, resized or on a
    monitor of another DPI since it was taken."""
    if frame.kind != "window":
        return ""
    with aware():
        if not win32.alive(frame.hwnd):
            return "the window is gone"
        if win32.rect(frame.hwnd) != frame.rect:
            return "the window moved or changed size since the picture"
        if user32.GetDpiForWindow(frame.hwnd) != frame.dpi:
            return "the window is on a monitor of another scale since the picture"
    return ""
