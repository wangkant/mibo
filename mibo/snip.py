"""A screenshot the person takes for the chat's "+" (panels/compose.py runs this as its own process).

The screen is pictured once, frozen and dimmed over every monitor; the person drags out an area, or clicks a
window to take the whole of it (the one under the pointer is lit up). Esc or a right click cancels. Nothing is
kept but the PNG written to the path given, and only after their drag or click.

Run as: python -m mibo.snip <out.png> <x> <y> <width> <height> <lang>, the box being the screen
area to cover in physical pixels (the virtual screen). Exit 0 with the file written, 2 when cancelled.
Run with --wait instead, it starts up ahead of time and takes the same arguments, tab-separated, on stdin.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import sys
import threading

# Moved less than this between press and release, it is a click: the window under it.
CLICK_PX = 4
WORDS = {"zh": "拖动选择区域，或单击选择窗口 · Esc 取消",
         "en": "Drag to select an area, or click a window · Esc to cancel"}
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
# Started ahead and not picked within this long, it leaves.
WAIT_S = 120


def windows() -> list[tuple[int, int, int, int]]:
    """The visible titled top-level windows, front first, as (left, top, right, bottom)."""
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    found: list[int] = []
    enum = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user32.EnumWindows(enum(lambda h, _: found.append(h) or True), 0)
    boxes = []
    for hwnd in found:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or not user32.GetWindowTextLengthW(hwnd):
            continue
        cloaked = w.DWORD()
        dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), 4)
        if cloaked.value:
            continue
        r = w.RECT()
        if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)):
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left > 8 and r.bottom - r.top > 8:
            boxes.append((r.left, r.top, r.right, r.bottom))
    return boxes


def scale_at(px: int, py: int) -> float:
    """Device px per px of the monitor at the screen point (px, py): Tk sizes its fonts by the main one's."""
    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    # MONITOR_DEFAULTTONEAREST; MDT_EFFECTIVE_DPI.
    monitor = user32.MonitorFromPoint(w.POINT(px, py), 2)
    dpi = w.UINT()
    ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(monitor), 0, ctypes.byref(dpi), ctypes.byref(dpi))
    return dpi.value / 96


def main(argv: list[str]) -> int:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    import tkinter as tk

    from PIL import ImageGrab, ImageTk
    # Python and Tk take seconds to start on some machines: done before the person picks it.
    root = tk.Tk()
    root.withdraw()
    if argv == ["--wait"]:
        got: list[str] = []
        reader = threading.Thread(target=lambda: got.append(sys.stdin.readline()), daemon=True)
        reader.start()
        reader.join(WAIT_S)
        if not got or not got[0].strip():
            return 2
        argv = got[0].rstrip("\r\n").split("\t")
    out, x, y, wide, high, lang = argv[0], *map(int, argv[1:5]), argv[5]
    shot = ImageGrab.grab(bbox=(x, y, x + wide, y + high), all_screens=True)
    tops = [(left - x, top - y, right - x, bottom - y) for left, top, right, bottom in windows()]

    root.overrideredirect(True)
    root.geometry(f"{wide}x{high}+{x}+{y}")
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, width=wide, height=high, highlightthickness=0, cursor="crosshair", bg="black")
    canvas.pack()
    dim = ImageTk.PhotoImage(shot.point(lambda v: v // 2))
    canvas.create_image(0, 0, anchor="nw", image=dim)
    lit = {"photo": None, "box": None}
    lit_image = canvas.create_image(0, 0, anchor="nw")
    frame = canvas.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=2, state="hidden")
    size = canvas.create_text(0, 0, anchor="sw", fill="#ffffff", font=("Segoe UI", 10), state="hidden")
    words = WORDS.get(lang, WORDS["en"])
    tip_box = canvas.create_rectangle(0, 0, 0, 0, fill="#1f1f1f", outline="#3a3a3a")
    tip = canvas.create_text(0, 0, text=words, fill="#f2f2f2", font=("Microsoft YaHei UI", 11))
    press = {"at": None}
    result = {"box": None}

    def show(box):
        """`box` (left, top, right, bottom) shown at full brightness with a frame; None for none."""
        if box == lit["box"]:
            return
        lit["box"] = box
        if box is None:
            canvas.itemconfigure(lit_image, image="")
            canvas.itemconfigure(frame, state="hidden")
            canvas.itemconfigure(size, state="hidden")
            return
        left, top, right, bottom = box
        lit["photo"] = ImageTk.PhotoImage(shot.crop(box))
        canvas.coords(lit_image, left, top)
        canvas.itemconfigure(lit_image, image=lit["photo"])
        canvas.coords(frame, left, top, right, bottom)
        # Drawn at the scale of the monitor the box begins on (10 pt is 4/3 of 10 px).
        k = scale_at(left + x, top + y)
        canvas.itemconfigure(frame, width=round(2 * k))
        canvas.itemconfigure(size, font=("Segoe UI", -round(10 * 4 / 3 * k)))
        canvas.coords(size, left + round(2 * k), top - round(6 * k) if top > round(24 * k) else bottom + round(20 * k))
        canvas.itemconfigure(size, text=f"{right - left} × {bottom - top}")
        canvas.itemconfigure(frame, state="normal")
        canvas.itemconfigure(size, state="normal")

    def under(px, py):
        for left, top, right, bottom in tops:
            if left <= px < right and top <= py < bottom:
                return max(0, left), max(0, top), min(wide, right), min(high, bottom)
        return None

    def place_tip(px):
        # Over the top middle of the monitor under the pointer, at that monitor's scale.
        left, top, right, _ = next((m for m in monitors() if m[0] <= px < m[2]), (0, 0, wide, high))
        k = scale_at(left + x, top + y)
        canvas.itemconfigure(tip, font=("Microsoft YaHei UI", -round(11 * 4 / 3 * k)))
        canvas.coords(tip, (left + right) // 2, top + round(36 * k))
        l, t, r, b = canvas.bbox(tip)
        canvas.coords(tip_box, l - round(16 * k), t - round(8 * k), r + round(16 * k), b + round(8 * k))

    def monitors():
        found = []
        proc = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)
        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, proc(lambda m, d, r, _: found.append((r[0].left - x, r[0].top - y, r[0].right - x,
                                                               r[0].bottom - y)) or True), 0)
        return found

    def moved(event):
        if press["at"] is None:
            show(under(event.x, event.y))
            place_tip(event.x)
            return
        sx, sy = press["at"]
        if abs(event.x - sx) >= CLICK_PX or abs(event.y - sy) >= CLICK_PX:
            show((min(sx, event.x), min(sy, event.y), max(sx, event.x) + 1, max(sy, event.y) + 1))

    def pressed(event):
        press["at"] = (event.x, event.y)
        canvas.itemconfigure(tip, state="hidden")
        canvas.itemconfigure(tip_box, state="hidden")

    def released(event):
        sx, sy = press["at"] or (event.x, event.y)
        press["at"] = None
        dragged = abs(event.x - sx) >= CLICK_PX or abs(event.y - sy) >= CLICK_PX
        box = lit["box"] if dragged else under(event.x, event.y)
        if box and box[2] - box[0] > 2 and box[3] - box[1] > 2:
            result["box"] = box
            root.destroy()

    canvas.bind("<Motion>", moved)
    canvas.bind("<B1-Motion>", moved)
    canvas.bind("<ButtonPress-1>", pressed)
    canvas.bind("<ButtonRelease-1>", released)
    canvas.bind("<ButtonPress-3>", lambda _: root.destroy())
    root.bind("<Escape>", lambda _: root.destroy())
    point = w.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    place_tip(point.x - x)
    show(under(point.x - x, point.y - y))
    root.deiconify()
    root.after(50, lambda: (root.focus_force(), canvas.focus_set()))
    root.mainloop()
    if result["box"] is None:
        return 2
    shot.crop(result["box"]).save(out, "PNG")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
