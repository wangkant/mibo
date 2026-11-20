"""Measure how Mibo shares the computer while it operates another program (persona_agent/desk), with no model.

    python tools/desk_manners.py --home DIR [--tree DIR] [--only idle,pause,menu,double] [--out FILE]

Four checks, each over the product's own Hands (and, for the pause, its own loop with fixed model answers):

- idle: real keys while the person is using the computer. Their use is a stand-in for the reading the layer takes
  (win32.idle_s, GetLastInputInfo), driven by this script; their own keyboard and mouse are never touched. Counted:
  keystrokes sent while the stand-in said they were busy, and how long the layer waited.
- pause: the person uses the window in the middle of a task (a stand-in for the strip's watch), then presses 继续
  on the strip (a click message to the strip's own button). Counted: whether the task still gets done.
- menu: the right-click menu of a list item, in a small test program and in File Explorer on a folder of its own;
  whether its 删除 (Delete) and 打开 (Open) items raise the card, and that nothing happens when the card says no.
- double: a double click on a list item of the test program, on a folder and on a file in File Explorer.

It only operates windows it starts itself, on the second monitor when there is one, and closes them. Real input is
sent only while one of its own windows is in front and the person's own keyboard and mouse have been still for a
moment; otherwise the check stops. `--tree` measures another copy of the package (an earlier one, for a before).
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TEST_PROGRAM = r"""
using System; using System.Drawing; using System.IO; using System.Windows.Forms;
class P : Form {
  static string logPath;
  static void Log(string s) { File.AppendAllText(logPath, s + Environment.NewLine); }
  protected override bool ShowWithoutActivation { get { return true; } }
  P(int x, int y) {
    Text = "Desk manners"; StartPosition = FormStartPosition.Manual; Location = new Point(x, y);
    ClientSize = new Size(520, 400); Font = new Font("Microsoft YaHei UI", 9);
    var list = new ListView { Left = 10, Top = 10, Width = 300, Height = 150, View = View.Details, FullRowSelect = true,
                              HideSelection = false, AccessibleName = "文件列表" };
    list.Columns.Add("名称", 120); list.Columns.Add("大小", 80);
    foreach (var n in new[] { "苹果", "香蕉", "樱桃" }) list.Items.Add(new ListViewItem(new[] { n, "1 KB" }));
    list.DoubleClick += (s, e) => { if (list.SelectedItems.Count > 0) Log("DOUBLE " + list.SelectedItems[0].Text); };
    var menu = new ContextMenuStrip();
    menu.Items.Add("复制", null, (s, e) => Log("COPY " + (list.SelectedItems.Count > 0 ? list.SelectedItems[0].Text : "")));
    menu.Items.Add("删除", null, (s, e) => { if (list.SelectedItems.Count > 0) { Log("DELETE " + list.SelectedItems[0].Text);
                                                                              list.SelectedItems[0].Remove(); } });
    list.ContextMenuStrip = menu;
    Controls.Add(list);
    var next = new Button { Left = 10, Top = 170, Width = 100, Height = 30, Text = "下一步" };
    var count = new Label { Left = 120, Top = 176, Width = 120, Text = "已点 0 次" };
    int pressed = 0;
    next.Click += (s, e) => { Log("CLICK 下一步"); pressed++; count.Text = "已点 " + pressed + " 次"; };
    Controls.Add(next); Controls.Add(count);
    var notes = new TextBox { Left = 10, Top = 210, Width = 500, Height = 170, Multiline = true, AccessibleName = "备注" };
    notes.KeyDown += (s, e) => Log("KEY " + e.KeyCode);
    Controls.Add(notes);
    Log("START");
  }
  [STAThread] static void Main(string[] a) {
    logPath = a[0]; Application.EnableVisualStyles(); Application.Run(new P(int.Parse(a[1]), int.Parse(a[2])));
  }
}
"""

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]


class Stop(BaseException):
    """Something not ours has the front, or the person is using the computer: no real input now."""


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def real_idle() -> float:
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    user32.GetLastInputInfo(ctypes.byref(info))
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


class Person:
    """The stand-in for the person's use of the computer: busy until `until` (keys or mouse), as the layer reads
    it. The old layer read only keys, through the strip's `keyed`."""

    def __init__(self):
        self.until = 0.0
        self.keys = False
        self.last = -1e9
        self.strip = None
        threading.Thread(target=self._tick, daemon=True).start()

    def busy(self, seconds: float, keys: bool) -> None:
        self.until, self.keys = time.monotonic() + seconds, keys

    def _tick(self) -> None:
        while True:
            now = time.monotonic()
            if now < self.until:
                self.last = now
                if self.keys and self.strip is not None:
                    self.strip.keyed = now
            time.sleep(0.1)

    def idle_s(self) -> float:
        return time.monotonic() - self.last

    def active(self) -> bool:
        return self.idle_s() < 1.5


class Bench:
    def __init__(self, args):
        self.home = Path(args.home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        sys.path.insert(0, str(Path(args.tree).resolve() if args.tree else Path(__file__).resolve().parents[1]))
        from persona_agent.desk import grants, hands, operate, panel, strip, uia, win32
        self.g, self.hands_mod, self.operate, self.panel, self.strip_mod, self.uia, self.win32 = (
            grants, hands, operate, panel, strip, uia, win32)
        win32.dpi_aware()
        grants.Grants(self.home / "runtime" / "desktop").set_on(True)
        self.worker = ThreadPoolExecutor(1, thread_name_prefix="desk")
        self.ours: set[int] = set()
        # Windows of a process that is not ours alone (File Explorer is also the taskbar and the person's folders).
        self.windows: set[int] = set()
        self.cards: list[dict] = []
        self.sent: list[dict] = []
        self.person = Person()
        self.new = hasattr(win32, "idle_s")
        if self.new:
            win32.idle_s = self.person.idle_s
        screens = win32.monitors()
        self.screen = next((s for s in screens if not s["primary"]), screens[0])
        self.x, self.y = self.screen["right"] - 640, self.screen["top"] + 200
        send = win32._send

        def guarded(inputs):
            for _ in range(40):
                if real_idle() >= 1.0 or time.monotonic() - getattr(self, "sent_at", 0) < real_idle() + 0.3:
                    break
                time.sleep(0.25)
            else:
                raise Stop("the person is using the keyboard or mouse")
            front = win32.top_of(win32.foreground())
            if not self.is_ours(front):
                raise Stop(f"another window has the front ({win32.class_of(front)})")
            self.sent.append({"at": time.monotonic(), "busy": self.person.active(), "n": len(inputs)})
            out = send(inputs)
            self.sent_at = time.monotonic()
            return out
        win32._send = guarded

    def is_ours(self, hwnd: int) -> bool:
        top = self.win32.top_of(hwnd)
        return (top in self.windows or self.win32.root_owner(top) in self.windows or self.win32.pid_of(top) in self.ours
                or self.g.program_pid(top) in self.ours)

    def card(self, card: dict) -> dict | None:
        kind = card.get("type")
        answer = {"answer": "once"} if kind == "desk_grant" else {"yes": False}
        self.cards.append({"type": kind, "kind": card.get("kind", ""), "target": card.get("target", ""),
                           "files": card.get("files", []), "answer": answer})
        return answer

    def launch(self, cmd: list[str], match, size=(600, 520)) -> int:
        win32 = self.win32
        before = set(win32.top_windows())
        proc = subprocess.Popen(cmd)
        end = time.monotonic() + 20
        while time.monotonic() < end:
            time.sleep(0.05)
            for h in win32.top_windows():
                if h not in before and user32.IsWindowVisible(h) and match(h):
                    if win32.class_of(h) == "CabinetWClass":
                        self.windows.add(h)
                    else:
                        self.ours |= {proc.pid, win32.pid_of(h), self.g.program_pid(h)}
                    # Some programs (File Explorer) put their window back where it was last: placed until it stays.
                    for _ in range(10):
                        win32.place(h, self.x, self.y, *size)
                        time.sleep(0.5)
                        left, top, right, _b = win32.rect(h)
                        if self.screen["left"] <= left and right <= self.screen["right"] and abs(top - self.y) < 40:
                            time.sleep(0.5)
                            return h
                    win32.close(h)
                    raise SystemExit(f"{cmd[0]}'s window would not stay on the second monitor")
        raise SystemExit(f"no window came up for {cmd[0]}")

    def on(self, fn, *a):
        return self.worker.submit(fn, *a).result()

    def hands(self, hwnd: int, task: str):
        def start():
            h = self.hands_mod.Hands(self.home / "runtime" / "desktop", ask=self.card, who="Mibo", lang="zh")
            h.begin(task)
            out = h.use(hwnd)
            assert out["status"] == "ok", out
            h.look()
            return h
        h = self.on(start)
        self.person.strip = h.strip
        return h

    def shot(self, hands, name: str) -> str:
        """The strip as drawn now, from its own window."""
        path = self.home / f"strip-{name}.png"
        time.sleep(0.4)
        if hands.strip is None:
            return ""
        image, _ = self.win32.capture(hands.strip.strip)
        image.save(path)
        return str(path)

    def go(self, hands) -> bool:
        """The person presses 继续 on the strip: a click message to the strip's own button, when it has one."""
        button = getattr(self.strip_mod, "GO_ID", 0)
        if not button:
            return False
        user32.PostMessageW(hands.strip.strip, 0x0111, button, 0)
        return True


def testprog(b: Bench):
    exe, src = b.home / "DeskManners.exe", b.home / "DeskManners.cs"
    if not exe.exists() or not src.exists() or src.read_text(encoding="utf-8") != TEST_PROGRAM:
        src.write_text(TEST_PROGRAM, encoding="utf-8")
        csc = Path(os.environ["SystemRoot"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
        subprocess.run([str(csc), "/nologo", "/target:winexe", f"/out:{exe}", "/r:System.Windows.Forms.dll",
                        "/r:System.Drawing.dll", str(src)], check=True, capture_output=True)
    log = b.home / "manners.log"
    log.write_text("", encoding="utf-8")
    hwnd = b.launch([str(exe), str(log), str(b.x), str(b.y)],
                    lambda h: (b.win32.exe_of(b.win32.pid_of(h)) or "").lower() == str(exe).lower())
    return hwnd, lambda: log.read_text(encoding="utf-8").splitlines()


def explorer(b: Bench):
    folder = b.home / "files"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir()
    for name in ("a.txt", "b.txt"):
        (folder / name).write_text(name, encoding="utf-8")
    (folder / "归档").mkdir()
    time.sleep(0.5)
    hwnd = b.launch(["explorer.exe", str(folder)], lambda h: b.win32.class_of(h) == "CabinetWClass")
    return hwnd, folder


def close(b: Bench, hwnd: int) -> None:
    """Close our window; asked again while it stays (File Explorer can let a close go by just after it moved)."""
    for _ in range(5):
        b.win32.close(hwnd)
        time.sleep(0.5)
        if not b.win32.alive(hwnd):
            return


# --- the checks

def idle(b: Bench) -> dict:
    """Real keys into the test program while the person is busy: moving the mouse for 4 s, typing for 2 s, and
    typing for 14 s (past the layer's longest wait, after which they press 继续 if the strip offers it)."""
    hwnd, events = testprog(b)
    out = {}
    try:
        for name, seconds, keys in (("mouse 4s", 4, False), ("typing 2s", 2, True), ("typing 14s", 14, True)):
            hands = b.hands(hwnd, "在备注里按 End")
            b.sent.clear()
            before = len(events())
            b.person.busy(seconds, keys)
            began = time.monotonic()
            job = b.worker.submit(hands.batch, [{"do": "focus", "name": "备注"}, {"do": "key", "key": "End"}])
            asked = pressed = False
            while not job.done():
                time.sleep(0.1)
                if hands.strip.halted == "paused" and not asked:
                    asked = True
                    out.setdefault("pictures", {})[name] = b.shot(hands, "busy")
                if asked and not pressed and not b.person.active():
                    pressed = b.go(hands)
            results = job.result()["results"]
            if pressed and any(r["line"].startswith("[not done]") for r in results):
                # Resumed: the loop's next reply plans the key again, from the fresh look.
                results += b.on(hands.batch, [{"do": "key", "key": "End"}])["results"]
            out[name] = {"busy_s": seconds, "keys_sent_while_busy": sum(s["busy"] for s in b.sent),
                         "keys_sent": len(b.sent), "first_key_after_s": round(b.sent[0]["at"] - began, 1) if b.sent else None,
                         "asked_on_strip": asked, "pressed_continue": pressed,
                         "key_landed": "KEY End" in events()[before:],
                         "lines": [r["line"][:160] for r in results]}
            b.on(hands.end, "done", "")
            b.person.busy(0, False)
            time.sleep(0.5)
    finally:
        close(b, hwnd)
    return out


def pause(b: Bench) -> dict:
    """A task of two presses of 下一步 through the product's loop; after the first, the person uses the window (the
    strip's watch is told so), and a second later presses 继续 if the strip offers it."""
    hwnd, events = testprog(b)
    try:
        hands = b.hands(hwnd, "在测试程序里点两次“下一步”")
        prompts: list[str] = []

        async def ask_model(system: str, messages: list[dict]) -> str:
            text = messages[-1]["content"]
            prompts.append(text)
            if text.count("] press [") >= 2 or text.count('(pressed once)') >= 2:
                return json.dumps({"actions": [{"do": "done", "success": True, "result": "点了两次"}]})
            if len(prompts) == 2:
                # Between the replies the person clicks in the window.
                hands.strip.stop("paused", "the person used the mouse in the window")
                threading.Timer(1.0, lambda: b.go(hands)).start()
                threading.Timer(0.5, lambda: shots.update(paused=b.shot(hands, "paused"))).start()
            return json.dumps({"note": "点下一步", "actions": [{"do": "press", "name": "下一步"}]})
        shots: dict = {}

        class Local:
            async def begin(self, task, program, sight="", also=()):
                return {"status": "ok", "program": "Desk manners", "line": "[ok] using Desk manners"}

            def __getattr__(self, op):
                async def call(*a):
                    return await asyncio.wrap_future(b.worker.submit(getattr(hands, op), *a))
                return call
        began = time.monotonic()
        outcome = asyncio.run(b.operate.run(ask_model, Local(), "在测试程序里点两次“下一步”", "Desk manners", lang="zh"))
        clicks = [e for e in events() if e == "CLICK 下一步"]
        return {"status": outcome["status"], "clicks": len(clicks), "calls": outcome["calls"],
                "seconds": round(time.monotonic() - began, 1), "done": outcome["status"] == "done" and len(clicks) == 2,
                "steps": [s[:200] for s in outcome["steps"]], "pictures": shots}
    finally:
        b.on(hands.end, "done", "")
        close(b, hwnd)


def _menu_items(hands) -> dict[str, int]:
    """The items of the open menu, by name, with their ids in the latest look."""
    v = hands.view
    return {n.name: i for i, n in v.nodes.items() if n.top in getattr(v, "menus", ()) and n.role == "menuitem"}


def menu(b: Bench) -> dict:
    """The right-click menu of a list item; its delete, open and copy items pressed, every card answered no."""
    out = {}
    hwnd, events = testprog(b)
    try:
        hands = b.hands(hwnd, "在文件列表里右键苹果，看看菜单")
        b.cards.clear()
        r = b.on(hands.batch, [{"do": "menu", "name": "苹果"}])
        items = _menu_items(hands)
        row = {"menu": r["results"][0]["line"][:160], "items": list(items), "picture": b.shot(hands, "menu")}
        for want in ("删除", "复制"):
            if want in items:
                b.cards.clear()
                res = b.on(hands.batch, [{"do": "press", "name": want}])["results"][0]
                row[want] = {"card": [c["kind"] for c in b.cards if c["type"] == "desk_action"], "line": res["line"][:160]}
                if want == "删除":
                    b.on(hands.batch, [{"do": "menu", "name": "苹果"}])
        row["events"] = events()
        out["test program"] = row
        b.on(hands.batch, [{"do": "key", "key": "Escape"}])
        b.on(hands.end, "done", "")
    finally:
        close(b, hwnd)
    hwnd, folder = explorer(b)
    try:
        hands = b.hands(hwnd, "在这个文件夹里右键 a.txt，看看菜单")
        r = b.on(hands.batch, [{"do": "menu", "name": "a.txt"}])
        items = _menu_items(hands)
        row = {"menu": r["results"][0]["line"][:160], "items": list(items), "picture": b.shot(hands, "menu-explorer")}
        for words in (("删除", "delete"), ("打开", "open"), ("复制", "copy")):
            item = next((i for i in items if any(w == i.lower() for w in words)), "")
            if item:
                b.cards.clear()
                res = b.on(hands.batch, [{"do": "press", "name": item, "id": items[item]}])["results"][0]
                row[words[1]] = {"item": item, "card": [c["kind"] for c in b.cards if c["type"] == "desk_action"],
                                 "files": [f for c in b.cards for f in c["files"]], "line": res["line"][:160]}
                b.on(hands.batch, [{"do": "key", "key": "Escape"}])
                b.on(hands.batch, [{"do": "menu", "name": "a.txt"}])
                items = _menu_items(hands)
        b.on(hands.batch, [{"do": "key", "key": "Escape"}])
        row["files after"] = sorted(p.name for p in folder.iterdir())
        out["File Explorer"] = row
        b.on(hands.end, "done", "")
    finally:
        close(b, hwnd)
    return out


def double(b: Bench) -> dict:
    """A double click on a list item of the test program, on a folder and on a file in File Explorer."""
    out = {}
    hwnd, events = testprog(b)
    try:
        hands = b.hands(hwnd, "双击苹果")
        b.cards.clear()
        res = b.on(hands.batch, [{"do": "double", "name": "香蕉"}])["results"][0]
        out["test program"] = {"line": res["line"][:160], "events": events(), "cards": len(b.cards)}
        b.on(hands.end, "done", "")
    finally:
        close(b, hwnd)
    hwnd, _folder = explorer(b)
    try:
        hands = b.hands(hwnd, "双击 a.txt 和 归档")
        tops = set(b.win32.top_windows())
        b.cards.clear()
        res = b.on(hands.batch, [{"do": "double", "name": "a.txt"}])["results"][0]
        time.sleep(1.5)
        opened = [b.win32.title_of(h) for h in set(b.win32.top_windows()) - tops if b.win32.shown(h)]
        out["file"] = {"line": res["line"][:160], "card": [c["kind"] for c in b.cards if c["type"] == "desk_action"],
                       "windows opened": opened}
        res = b.on(hands.batch, [{"do": "double", "name": "归档"}])["results"][0]
        out["folder"] = {"line": res["line"][:160], "title after": b.win32.title_of(hwnd)}
        b.on(hands.end, "done", "")
    finally:
        close(b, hwnd)
    return out


CHECKS = {"idle": idle, "pause": pause, "menu": menu, "double": double}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--tree", default="")
    parser.add_argument("--only", default=",".join(CHECKS))
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    bench = Bench(args)
    result = {"tree": args.tree or "now"}
    for name in args.only.split(","):
        while real_idle() < 2.0:
            time.sleep(0.5)
        try:
            result[name] = CHECKS[name](bench)
        except Stop as e:
            result[name] = {"stopped": str(e)}
        print(name, json.dumps(result[name], ensure_ascii=False, indent=1), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
