"""Can Cua Driver see and work other programs here? One run against the
fixture (tools/xplat/cua_fixture.py) or a program the system ships (Notepad,
TextEdit, gedit), through the app's own MCP client (mibo/mcp_client.py), with
each step timed and checked against what the program itself holds:

    tools, permissions, list apps, launch by name, list windows, the tree as
    lines with refs, the chat line read, type text, set text, click a button,
    press a chord, a window picture

On Windows, `--uia` also reads the same Notepad window through mibo/desk/uia.py,
the reader the app uses today, and writes both trees side by side.

    python tools/xplat/cua_check.py --driver <cua-driver> --out <folder> [--toolkit tk|qt | --program NAME] [--uia]

It starts windows and sends input, so it runs only on a runner or a virtual
screen, never on someone's own desktop. The last lines are the findings; the
exit code is 0 when every step the target needs passed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mibo import mcp_client  # noqa: E402

SHIPPED = {"win32": "notepad", "darwin": "TextEdit", "linux": "gedit"}
# What the driver needs from the session besides what mcp_client passes to any server.
SESSION_ENV = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS",
               "CUA_DRIVER_RS_ENABLE_WAYLAND")
TEXTBOX = re.compile(r"text ?field|text ?box|textarea|text area|edit|entry|^text$|axtext|document", re.I)
# A program's main text area, the likeliest kind first (a plain "text" is a label on some systems).
AREAS = (re.compile(r"document|text ?area|axtextarea", re.I), re.compile(r"^edit$|text ?field|entry", re.I),
         re.compile(r"^text$", re.I))
TYPED = "abc"
SET = "你好 Mibo 42"
PROGRAM_TEXT = "Mibo 你好 123"


class Check:
    """One target's steps: each has a name, whether it passed, its time and a short detail."""

    def __init__(self, out: Path, label: str) -> None:
        self.out, self.label = out, label
        self.steps: list[dict] = []
        self.facts: dict = {}
        self.conn: mcp_client.Connection | None = None

    def step(self, name: str, ok: bool, ms: float | None = None, detail: str = "", need: bool = True) -> bool:
        self.steps.append({"step": name, "ok": bool(ok), "ms": None if ms is None else round(ms, 1),
                           "detail": str(detail)[:400], "required": need})
        print(f"[{'pass' if ok else 'FAIL' if need else 'no'}] {name} {'' if ms is None else f'{ms:.0f} ms'} "
              f"{str(detail)[:200]}", flush=True)
        return bool(ok)

    async def open(self, driver: str) -> None:
        env = {name: os.environ[name] for name in SESSION_ENV if name in os.environ}
        # Cua Driver reports usage to PostHog unless told not to.
        env["CUA_DRIVER_RS_TELEMETRY_ENABLED"] = "0"
        spec = {"command": driver, "args": ["mcp", "--direct"], "env": env}
        self.conn = mcp_client.Connection(spec, folder=self.out / f"{self.label}-mcp")
        began = time.perf_counter()
        await self.conn.open(60)
        self.step("connect", True, (time.perf_counter() - began) * 1000, self.conn.server_name)

    async def call(self, name: str, args: dict, timeout: float = 60) -> dict:
        """One tool call: whether it succeeded, its time, its structured content, and the text and pictures
        mcp_client's ToolResult would give the app."""
        began = time.perf_counter()
        try:
            raw = await asyncio.wait_for(self.conn._client().call_tool(name, args), timeout)
        except Exception as e:  # a failing call is a finding, not the end of the run
            return {"ok": False, "ms": (time.perf_counter() - began) * 1000, "data": {}, "text": repr(e)[:400],
                    "pictures": 0}
        ms = (time.perf_counter() - began) * 1000
        dumped = raw.model_dump(by_alias=True, mode="json", exclude_none=True)
        seen = await asyncio.to_thread(mcp_client.result_of, dumped)
        return {"ok": not dumped.get("isError"), "ms": ms, "data": dumped.get("structuredContent") or {},
                "text": seen.text, "pictures": len(seen.pictures)}

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()

    def write(self) -> dict:
        record = {"label": self.label, "system": sys.platform, "steps": self.steps, "facts": self.facts}
        (self.out / f"{self.label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), "utf-8")
        return record


def records(data, key: str) -> list[dict]:
    """Every dict anywhere in `data` that has `key`."""
    found = []
    if isinstance(data, dict):
        if key in data:
            found.append(data)
        for value in data.values():
            found += records(value, key)
    elif isinstance(data, list):
        for value in data:
            found += records(value, key)
    return found


def number(text: str, key: str) -> int:
    match = re.search(rf'"?{key}"?\s*[:=]\s*(\d+)', text)
    return int(match.group(1)) if match else 0


def lines_of(elements: list[dict]) -> str:
    """The driver's elements in the line form pageops and desk/uia.py print: [ref] role "name" = value."""
    out = []
    for e in elements:
        pad = "  " * min(int(e.get("depth") or 0), 12)
        value = f' = "{e["value"]}"' if e.get("value") not in (None, "") else ""
        out.append(f'{pad}[{e.get("element_index")}] {e.get("role", "")} "{e.get("label", "")}"{value}')
    return "\n".join(out)


def find(elements: list[dict], role: re.Pattern | None = None, label: str = "") -> dict | None:
    for e in elements:
        if role is not None and not role.search(str(e.get("role", ""))):
            continue
        if label and label.lower() not in f'{e.get("label", "")} {e.get("value", "")}'.lower():
            continue
        if e.get("element_token"):
            return e
    return None


def holds(elements: list[dict], markdown: str, text: str) -> bool:
    return text in markdown or any(text in f'{e.get("label", "")} {e.get("value", "")}' for e in elements)


async def wait_until(test, seconds: float = 4.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        await asyncio.sleep(0.1)
    return bool(test())


async def window_of(check: Check, pid: int, title: str = "", seconds: float = 20.0) -> dict | None:
    """The first top-level window of `pid` the driver lists, waited for; with `title`, a window of that title
    when none is listed under the pid (a toolkit that does not say which process a window is)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        answer = await check.call("list_windows", {"pid": pid})
        wins = [w for w in records(answer["data"], "window_id") if int(w.get("pid") or pid) == pid]
        shown = [w for w in wins if w.get("is_on_screen", w.get("on_screen", True))]
        if shown or wins:
            return (shown or wins)[0]
        if title:
            answer = await check.call("list_windows", {})
            named = [w for w in records(answer["data"], "window_id") if w.get("title") == title]
            if named:
                check.facts["window_pid"] = named[0].get("pid")
                return named[0]
        await asyncio.sleep(0.5)
    return None


async def look(check: Check, pid: int, wid: int, name: str, need: bool = True) -> tuple[list[dict], str]:
    answer = await check.call("get_window_state", {"pid": pid, "window_id": wid, "include_screenshot": False})
    elements = answer["data"].get("elements") or []
    markdown = answer["data"].get("tree_markdown") or answer["text"]
    check.step(name, answer["ok"] and bool(elements), answer["ms"],
               f"{len(elements)} elements, {len(markdown)} chars" if answer["ok"] else answer["text"], need)
    return elements, markdown


async def picture(check: Check, pid: int, wid: int) -> None:
    # The driver runs in its own folder, so the path is a whole one.
    path = (check.out / f"{check.label}-window.png").resolve()
    answer = await check.call("get_window_state", {"pid": pid, "window_id": wid, "include_accessibility_tree": False,
                                                   "screenshot_out_file": str(path)})
    detail, ok = answer["text"][:200], False
    if path.exists():
        from PIL import Image
        with Image.open(path) as image:
            colours = image.convert("RGB").resize((64, 64)).getcolors(4096) or []
            ok = len(colours) > 4
            detail = f"{image.size[0]}x{image.size[1]}, {len(colours)} colours in a 64x64 sample"
    check.step("window picture", answer["ok"] and ok, answer["ms"], detail)


async def common(check: Check, target: str) -> None:
    """Tools, permissions and app listing, the same for every target."""
    began = time.perf_counter()
    tools = await check.conn.list_tools(60, 500)
    names = sorted(t["name"] for t in tools)
    check.facts["tools"] = names
    (check.out / f"{check.label}-tools.json").write_text(json.dumps(tools, ensure_ascii=False, indent=1), "utf-8")
    check.step("tools listed", bool(names), (time.perf_counter() - began) * 1000, f"{len(names)} tools")
    check.facts["has_list_apps"] = "list_apps" in names
    check.facts["has_launch_app"] = "launch_app" in names
    answer = await check.call("check_permissions", {})
    check.facts["permissions"] = answer["data"] or answer["text"][:600]
    check.step("permissions", answer["ok"], answer["ms"], json.dumps(answer["data"], ensure_ascii=False)[:300]
               if answer["data"] else answer["text"][:300], need=False)
    answer = await check.call("list_apps", {})
    apps = records(answer["data"], "name")
    running = [a for a in apps if a.get("running")]
    listed = any(target.lower() in f'{a.get("name", "")} {a.get("bundle_id", "")} {a.get("launch_path", "")}'.lower()
                 for a in apps)
    check.facts["apps"] = {"count": len(apps), "running": len(running), "target_listed": listed}
    check.step("list apps", answer["ok"] and bool(apps), answer["ms"],
               f"{len(apps)} apps, {len(running)} running, {target} listed: {listed}")


async def fixture(check: Check, python: str, toolkit: str) -> None:
    state_path = check.out / f"{check.label}-state.json"
    state_path.unlink(missing_ok=True)

    def state() -> dict:
        try:
            return json.loads(state_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    await common(check, "python")
    proc = subprocess.Popen([python, str(ROOT / "tools" / "xplat" / "cua_fixture.py"), "--state", str(state_path),
                             "--toolkit", toolkit])
    try:
        if not check.step("fixture started", await wait_until(lambda: state().get("ready"), 30), detail=state()):
            return
        check.facts["toolkit"] = state().get("toolkit")
        win = await window_of(check, proc.pid, "Mibo fixture")
        if not check.step("list windows", win is not None, detail=json.dumps(win, ensure_ascii=False)[:300]):
            return
        check.step("window under its process", int(win.get("pid") or 0) == proc.pid, detail=f"pid {win.get('pid')}",
                   need=False)
        wid = int(win["window_id"])
        elements, markdown = await look(check, proc.pid, wid, "tree as lines with refs")
        (check.out / f"{check.label}-tree.md").write_text(markdown, "utf-8")
        (check.out / f"{check.label}-lines.txt").write_text(lines_of(elements), "utf-8")
        check.facts["roles"] = sorted({str(e.get("role")) for e in elements})
        check.step("chat line read", holds(elements, markdown, "小林"), detail="小林 in the tree")
        box = find(elements, TEXTBOX, "Message")
        button = find(elements, None, "Send")
        check.step("text box and button found", box is not None and button is not None,
                   detail=f"box {box and box.get('role')} {box and box.get('label')!r}, "
                          f"button {button and button.get('role')}")
        if box is not None:
            answer = await check.call("type_text", {"pid": proc.pid, "window_id": wid, "text": TYPED,
                                                    "element_token": box["element_token"]})
            check.step("type text", answer["ok"] and await wait_until(lambda: TYPED in state().get("text", "")),
                       answer["ms"], f"program holds {state().get('text')!r}; {answer['text'][:120]}")
            elements, markdown = await look(check, proc.pid, wid, "look again", need=False)
            box = find(elements, TEXTBOX, "Message") or box
            answer = await check.call("set_value", {"pid": proc.pid, "window_id": wid, "value": SET,
                                                    "element_token": box["element_token"]})
            check.step("set text", answer["ok"] and await wait_until(lambda: state().get("text") == SET),
                       answer["ms"], f"program holds {state().get('text')!r}; {answer['text'][:120]}")
            check.facts["act_ms"] = round(answer["ms"], 1)
        if button is not None:
            elements, markdown = await look(check, proc.pid, wid, "look before click", need=False)
            button = find(elements, None, "Send") or button
            sent = len(state().get("sent", []))
            answer = await check.call("click", {"pid": proc.pid, "window_id": wid,
                                                "element_token": button["element_token"]})
            check.step("click button", answer["ok"] and await wait_until(lambda: len(state().get("sent", [])) > sent),
                       answer["ms"], f"sent {state().get('sent')}; {answer['text'][:120]}")
        # Background input first, as the driver prefers; the app's hands bring the window to the front anyway.
        for mode in ("background", "foreground"):
            answer = await check.call("hotkey", {"pid": proc.pid, "window_id": wid, "keys": ["ctrl", "l"],
                                                 "delivery_mode": mode})
            done = answer["ok"] and await wait_until(lambda: state().get("chord", 0) > 0)
            check.step(f"press chord ({mode})", done, answer["ms"],
                       f"chord count {state().get('chord')}; {answer['text'][:120]}", need=mode == "foreground")
            if done:
                break
        await picture(check, proc.pid, wid)
        timed = await check.call("get_window_state", {"pid": proc.pid, "window_id": wid, "include_screenshot": False})
        check.facts["look_ms"] = round(timed["ms"], 1)
    finally:
        proc.terminate()


async def program(check: Check, name: str, uia: bool) -> None:
    await common(check, name)
    doc = Path(tempfile.gettempdir()) / "mibo-cua-check.txt"
    doc.write_text("", "utf-8")
    args: dict = {"name": name}
    if sys.platform == "darwin":
        args["urls"] = [doc.as_uri()]
    else:
        args["additional_arguments"] = [str(doc)]
    answer = await check.call("launch_app", args)
    pid = int((records(answer["data"], "pid") or [{}])[0].get("pid") or 0) or number(answer["text"], "pid")
    check.step("launch by name", answer["ok"] and pid > 0, answer["ms"], answer["text"][:300])
    if not pid:
        return
    try:
        win = await window_of(check, pid)
        if not check.step("list windows", win is not None, detail=json.dumps(win, ensure_ascii=False)[:300]):
            return
        wid = int(win["window_id"])
        elements, markdown = await look(check, pid, wid, "tree as lines with refs")
        (check.out / f"{check.label}-tree.md").write_text(markdown, "utf-8")
        (check.out / f"{check.label}-lines.txt").write_text(lines_of(elements), "utf-8")
        check.facts["roles"] = sorted({str(e.get("role")) for e in elements})
        box = next((e for kind in AREAS if (e := find(elements, kind))), None)
        if not check.step("text area found", box is not None, detail=box and f"{box.get('role')} {box.get('label')!r}"):
            return
        # Typed in the background, then with the window brought forward, then set through the tree: the first
        # that the program then shows counts.
        written = False
        for how, tool, extra in (("type (background)", "type_text", {"text": PROGRAM_TEXT}),
                                 ("type (foreground)", "type_text", {"text": PROGRAM_TEXT,
                                                                     "delivery_mode": "foreground"}),
                                 ("set", "set_value", {"value": PROGRAM_TEXT})):
            answer = await check.call(tool, {"pid": pid, "window_id": wid, "element_token": box["element_token"],
                                             **extra})
            await asyncio.sleep(0.5)
            elements, markdown = await look(check, pid, wid, f"look after {how}", need=False)
            written = answer["ok"] and holds(elements, markdown, PROGRAM_TEXT)
            check.step(f"{how} and read", written, answer["ms"], answer["text"][:200], need=False)
            box = next((e for kind in AREAS if (e := find(elements, kind))), None) or box
            if written:
                check.facts["act_ms"] = round(answer["ms"], 1)
                break
        check.step("text written and read back", written)
        await picture(check, pid, wid)
        timed = await check.call("get_window_state", {"pid": pid, "window_id": wid, "include_screenshot": False})
        check.facts["look_ms"] = round(timed["ms"], 1)
        if uia:
            beside(check, pid, wid, lines_of(elements))
    finally:
        await check.call("kill_app", {"pid": pid})


def beside(check: Check, pid: int, wid: int, cua_lines: str) -> None:
    """The same window through desk/uia.py, the reader the app uses on Windows today: its look, one act, both
    timed, and the two trees written side by side."""
    from mibo.desk import uia, win32
    hwnd = wid if win32.pid_of(wid) == pid else next(
        (h for h in win32.top_windows() if win32.pid_of(h) == pid and win32.shown(h)), 0)
    view = uia.View(hwnd, pid)
    began = time.perf_counter()
    view.look()
    first_ms = (time.perf_counter() - began) * 1000
    # The second look is the one to compare: the first also loads UI Automation into the process.
    began = time.perf_counter()
    text = view.look()
    look_ms = (time.perf_counter() - began) * 1000
    check.step("uia look", bool(text), look_ms, f"{len(text.splitlines())} lines", need=False)
    match = re.search(r"\[(\d+)\] (?:document|textbox)", text)
    act_ms = None
    if match:
        began = time.perf_counter()
        said = view.set_value(int(match.group(1)), "UIA 你好")
        act_ms = (time.perf_counter() - began) * 1000
        check.step("uia set text", "read back" in said, act_ms, said[:200], need=False)
    check.facts["uia"] = {"first_look_ms": round(first_ms, 1), "look_ms": round(look_ms, 1), "act_ms": act_ms and round(act_ms, 1),
                          "lines": len(text.splitlines())}
    (check.out / f"{check.label}-uia.txt").write_text(text, "utf-8")
    width = 70
    left, right = cua_lines.splitlines(), text.splitlines()
    rows = [f"{'Cua Driver':<{width}} | desk/uia.py"] + [
        f"{(left[i] if i < len(left) else '')[:width]:<{width}} | {right[i] if i < len(right) else ''}"
        for i in range(max(len(left), len(right)))]
    (check.out / f"{check.label}-beside.txt").write_text("\n".join(rows), "utf-8")


def report(folder: Path) -> str:
    """Every result in `folder` as one markdown table: a row per step, a column per target."""
    found = [json.loads(p.read_text("utf-8")) for p in sorted(folder.glob("*.json"))
             if not p.name.endswith(("-tools.json", "-state.json"))]
    names: list[str] = []
    for record in found:
        names += [s["step"] for s in record["steps"] if s["step"] not in names]
    rows = ["| step | " + " | ".join(r["label"] for r in found) + " |", "|---" * (len(found) + 1) + "|"]
    for name in names:
        cells = []
        for record in found:
            step = next((s for s in record["steps"] if s["step"] == name), None)
            cells.append("" if step is None else ("pass" if step["ok"] else "FAIL" if step["required"] else "no") +
                         ("" if step["ms"] is None else f" {step['ms']:.0f} ms"))
        rows.append(f"| {name} | " + " | ".join(cells) + " |")
    rows.extend(f"| {key} | " + " | ".join(str(r["facts"].get(key, "")) for r in found) + " |"
                for key in ("toolkit", "look_ms", "act_ms", "apps", "uia", "window_pid"))
    return "\n".join(rows)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", help="print the results in this folder as a table, and stop")
    parser.add_argument("--driver")
    parser.add_argument("--out")
    parser.add_argument("--toolkit", choices=("tk", "qt"))
    parser.add_argument("--program", help="a program the system ships; default: the fixture")
    parser.add_argument("--uia", action="store_true")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    if args.report:
        print(report(Path(args.report)))
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = args.program or f"fixture-{args.toolkit or 'tk'}"
    check = Check(out, args.label or f"{sys.platform}-{target}")
    try:
        await check.open(args.driver)
        if args.program:
            await program(check, args.program, args.uia)
        else:
            await fixture(check, sys.executable, args.toolkit or "tk")
    except mcp_client.McpError as e:
        check.step("connect", False, detail=f"{e.code}: {e.detail}")
    finally:
        await check.close()
    record = check.write()
    need = [s for s in record["steps"] if s["required"]]
    failed = [s["step"] for s in need if not s["ok"]]
    print(f"cua_check {check.label}: {len(need) - len(failed)}/{len(need)} required steps passed"
          f"{'; failed: ' + ', '.join(failed) if failed else ''}")
    print(f"cua_check {check.label}: look {check.facts.get('look_ms')} ms, act {check.facts.get('act_ms')} ms, "
          f"list_apps {check.facts.get('has_list_apps')}, launch_app {check.facts.get('has_launch_app')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
