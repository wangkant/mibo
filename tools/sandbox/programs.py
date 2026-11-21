"""The programs suite: Mibo operating other programs (mibo/desk) with the runner's real pointer and keys, on
stand-in programs it starts itself (a small test program built here, and File Explorer on a folder of its own),
through tools/desk_manners.py: keys held back while the person is busy, a task paused and resumed, the right-click
menu whose 删除 raises the card and does nothing on no, and double clicks. desk_manners writes numbers; the verdicts
on them are here.

A hosted runner has no UAC: every program started there runs as administrator, and Mibo never operates one
(desk/grants.py). desk_manners runs in this process with its programs started as a standard user of the runner's own
(SANDBOX_PERSON and SANDBOX_PERSON_KEY, made by the workflow for this run alone), as a person's programs run.
File Explorer cannot be had that way: a second user's File Explorer shows no window while the administrator's is the
shell, so its halves of the menu and double-click checks are said not to run here.

    python tools/sandbox/programs.py --out <folder>

Windows only: program control is UI Automation (README: "Program control and the built-in browser are
Windows-only"); on Linux and macOS the suite says so.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

from _suite import Suite, scratch_home, scrub_env, stand_in_model

FEATURES = ("keys wait for a busy person", "pause and resume", "right-click menu behind the card", "double click",
            "in File Explorer")


class NoExplorer(Exception):
    pass


def judge(suite: Suite, result: dict) -> None:
    idle = result.get("idle", {})
    for case in ("mouse 4s", "typing 2s", "typing 14s"):
        row = idle.get(case, {})
        suite.check(FEATURES[0], f"{case}: no key sent while they were busy", row.get("keys_sent_while_busy") == 0, row)
        suite.check(FEATURES[0], f"{case}: the key lands once they stop", row.get("key_landed") is True, row.get("lines"))
    pause = result.get("pause", {})
    suite.check(FEATURES[1], "two presses of 下一步 done across a pause by the person", pause.get("done") is True,
                {k: pause.get(k) for k in ("status", "clicks", "calls", "stopped")})
    menu, double = result.get("menu", {}), result.get("double", {})
    mine = menu.get("test program", {})
    suite.check(FEATURES[2], "删除 raises the card", bool(mine.get("删除", {}).get("card")), mine.get("删除"))
    suite.check(FEATURES[2], "nothing deleted on no", "events" in mine and not any(e.startswith("DELETE") for e in mine["events"]),
                mine.get("events"))
    suite.check(FEATURES[3], "a double click on an item reaches it",
                "DOUBLE 香蕉" in double.get("test program", {}).get("events", []), double.get("test program"))
    if "File Explorer" not in menu and "folder" not in double:
        suite.skipped(FEATURES[4], "not run: a second user's File Explorer shows no window on a runner whose shell is the"
                                   " administrator's, and Mibo does not operate the administrator's")
        return
    theirs = menu.get("File Explorer", {})
    suite.check(FEATURES[4], "delete raises the card", bool(theirs.get("delete", {}).get("card")), theirs.get("delete"))
    suite.check(FEATURES[4], "the file is still there on no", "a.txt" in theirs.get("files after", []), theirs.get("files after"))
    suite.check(FEATURES[4], "opening a file asks first", bool(double.get("file", {}).get("card")), double.get("file"))
    suite.check(FEATURES[4], "a double click on a folder opens it", "归档" in str(double.get("folder", {}).get("title after")),
                double.get("folder"))


class AsPerson:
    """subprocess.Popen for desk_manners' programs: the command started as the runner's standard user, on this desktop."""

    def __init__(self, cmd: list[str], **_) -> None:
        import ctypes
        from ctypes import wintypes

        class StartupInfo(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                        ("lpTitle", wintypes.LPWSTR)] + [(n, wintypes.DWORD) for n in (
                            "dwX", "dwY", "dwXSize", "dwYSize", "dwXCountChars", "dwYCountChars", "dwFillAttribute",
                            "dwFlags")] + [("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                                           ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                                           ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD),
                        ("dwThreadId", wintypes.DWORD)]

        start, made = StartupInfo(), ProcessInfo()
        start.cb = ctypes.sizeof(start)
        # No desktop named: only then does Windows give the user's logon its share of this window station and desktop.
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
        # LOGON_WITH_PROFILE; the folder it starts in is the scratch home's, which the user was given.
        if not ctypes.windll.advapi32.CreateProcessWithLogonW(
                os.environ["SANDBOX_PERSON"], ".", os.environ["SANDBOX_PERSON_KEY"], 1, None, line, 0, None,
                os.environ["SANDBOX_HOME"], ctypes.byref(start), ctypes.byref(made)):
            raise OSError(ctypes.GetLastError(), f"could not start {cmd[0]} as the standard user")
        self.pid = made.dwProcessId
        ctypes.windll.kernel32.CloseHandle(made.hThread)
        ctypes.windll.kernel32.CloseHandle(made.hProcess)


def on_screen(win32) -> list[str]:
    """The visible top windows: class, process and title, the foreground one first."""
    import ctypes
    front = win32.top_of(win32.foreground())
    rows = []
    for h in [front] + [h for h in win32.top_windows() if h != front]:
        if ctypes.windll.user32.IsWindowVisible(h):
            title = ctypes.create_unicode_buffer(200)
            ctypes.windll.user32.GetWindowTextW(h, title, 200)
            pid = win32.pid_of(h)
            rows.append(f"{win32.class_of(h)} pid {pid} {os.path.basename(win32.exe_of(pid) or '?')} '{title.value}'")
    return rows[:12]


def main() -> int:
    suite = Suite("programs", __doc__.split("\n\n")[0])
    if sys.platform != "win32":
        for feature in FEATURES:
            suite.not_built(feature, "program control is Windows-only (UI Automation)")
        return suite.finish()
    scrub_env()
    home = scratch_home(stand_in_model(), lang="zh")
    import desk_manners

    # The standard user reads the test program and writes its log and folder in the scratch home.
    subprocess.run(["icacls", str(home), "/grant", f"{os.environ['SANDBOX_PERSON']}:(OI)(CI)F", "/T", "/Q"], check=True)
    os.environ["SANDBOX_HOME"] = str(home)
    desk_manners.subprocess = SimpleNamespace(**{**vars(subprocess), "Popen": AsPerson})
    # One bench for every check, as one desk_manners run has: the programs it started stay its own.
    made = desk_manners.Bench
    bench = []
    desk_manners.Bench = lambda args: bench[0] if bench else bench.append(made(args)) or bench[0]

    def no_explorer(_bench):
        raise NoExplorer

    desk_manners.explorer = no_explorer
    result = {}
    # One check at a time, so one that stops leaves the others' numbers.
    for name in desk_manners.CHECKS:
        numbers = suite.out / f"desk_manners-{name}.json"
        sys.argv = ["desk_manners.py", "--home", str(home), "--only", name, "--out", str(numbers)]
        try:
            desk_manners.main()
            result.update(json.loads(numbers.read_text(encoding="utf-8")))
        except NoExplorer as error:
            # What the check had from the test program before it came to File Explorer.
            tb = error.__traceback__
            while tb and tb.tb_frame.f_code.co_name != name:
                tb = tb.tb_next
            result[name] = tb.tb_frame.f_locals["out"]
        except BaseException as error:
            suite.check("desk_manners", f"{name} ran to its end", False, repr(error)[:400])
            result[name] = {"stopped": repr(error)[:400]}
        if bench and "stopped" in result.get(name, {}):
            suite.shot(f"stopped-{name}")
            suite.log(f"{name} stopped; windows on the screen, front first: {on_screen(bench[0].win32)}; ours: {sorted(bench[0].ours)}")
    judge(suite, result)
    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
