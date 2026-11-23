"""One small program for checking how other programs are read and worked on all
three systems: a chat line from 小林, a text box, a send button, a list and a
keyboard shortcut (Ctrl+L). Every change is written to a state file, so a check
reads what the program itself holds, never what the driver says it did.

    python tools/xplat/cua_fixture.py --state <file> [--toolkit tk|qt]

Tk is the design's choice; Qt (PySide6) is the same window in a toolkit that
publishes its controls to UI Automation, AX and AT-SPI, for comparison.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

TITLE = "Mibo fixture"
CHAT = "小林：今晚七点一起吃饭吗？"  # copy: voice
ITEMS = ["Apples", "Bread", "Milk"]


class State:
    """What the window holds, written whole to `path` on every change."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.data = {"pid": os.getpid(), "toolkit": "", "text": "", "sent": [], "chord": 0, "ready": False}

    def set(self, **changes) -> None:
        self.data.update(changes)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)


def run_tk(state: State) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title(TITLE)
    root.geometry("420x320+60+60")
    tk.Label(root, text=CHAT).pack(anchor="w", padx=8, pady=6)
    text = tk.StringVar()
    text.trace_add("write", lambda *_: state.set(text=text.get()))
    entry = tk.Entry(root, textvariable=text, width=40)
    entry.pack(padx=8, fill="x")
    items = tk.Listbox(root, height=6)
    for item in ITEMS:
        items.insert("end", item)

    def send() -> None:
        items.insert("end", text.get())
        state.set(sent=state.data["sent"] + [text.get()])

    tk.Button(root, text="Send", command=send).pack(padx=8, pady=6, anchor="w")
    items.pack(padx=8, fill="both", expand=True)
    root.bind_all("<Control-l>", lambda _e: state.set(chord=state.data["chord"] + 1))
    entry.focus_set()
    state.set(toolkit=f"tk {tk.TkVersion}")
    root.after(300, lambda: state.set(ready=True))
    root.mainloop()


def run_qt(state: State) -> None:
    from PySide6.QtCore import Qt, QTimer, qVersion
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle(TITLE)
    window.setGeometry(60, 60, 420, 320)
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel(CHAT))
    entry = QLineEdit()
    entry.setAccessibleName("Message")
    entry.textChanged.connect(lambda value: state.set(text=value))
    layout.addWidget(entry)
    items = QListWidget()
    items.addItems(ITEMS)

    def send() -> None:
        items.addItem(entry.text())
        state.set(sent=state.data["sent"] + [entry.text()])

    button = QPushButton("Send")
    button.clicked.connect(send)
    layout.addWidget(button)
    layout.addWidget(items)
    # Qt reads Control as Command on macOS; the physical Ctrl key is Meta there.
    ctrl = Qt.KeyboardModifier.MetaModifier if sys.platform == "darwin" else Qt.KeyboardModifier.ControlModifier
    QShortcut(QKeySequence(ctrl | Qt.Key.Key_L), window).activated.connect(
        lambda: state.set(chord=state.data["chord"] + 1))
    window.show()
    entry.setFocus()
    state.set(toolkit=f"qt {qVersion()}")
    QTimer.singleShot(300, lambda: state.set(ready=True))
    app.exec()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--toolkit", choices=("tk", "qt"), default="tk")
    args = parser.parse_args()
    state = State(args.state)
    state.set()
    (run_tk if args.toolkit == "tk" else run_qt)(state)


if __name__ == "__main__":
    main()
