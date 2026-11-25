"""The browser already installed on this computer (Edge, Chrome or Chromium),
started as an ordinary process with a profile of its own and driven over a pipe
to it (never a debugging port). visitor.Visitor reads the open web through it,
never signed in. Nothing is done to look less like a program: no changed
fingerprint, no solved verification.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger("mibo.installed_browser")

#: Set to a browser's path to use that one.
BROWSER_ENV = "PERSONA_BROWSER_PATH"
#: 1: no window at all (a server); 0: a window even where none was expected.
HEADLESS_ENV = "PERSONA_BROWSER_HEADLESS"

START_S = 30.0
CLOSE_S = 8.0
STEP_MS = 15_000
# Why no walk can start: the codes the page explains.
NO_BROWSER, NO_DRIVER, NO_START = "browser_missing", "browser_support_missing", "browser_start_failed"

_WINDOWS_PLACES = (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe")
_WINDOWS_NAMES = ("msedge.exe", "chrome.exe")
_MAC_PLACES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "/Applications/Chromium.app/Contents/MacOS/Chromium")
_LINUX_NAMES = ("google-chrome", "google-chrome-stable", "microsoft-edge", "microsoft-edge-stable",
                "chromium", "chromium-browser")


def find_browser() -> Path | None:
    """The installed browser to use, or None."""
    chosen = os.environ.get(BROWSER_ENV, "").strip()
    if chosen:
        return Path(chosen) if Path(chosen).is_file() else None
    if os.name == "nt":
        roots = [os.environ.get(name, "") for name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for place in _WINDOWS_PLACES:
            for root in roots:
                if root and (Path(root) / place).is_file():
                    return Path(root) / place
        names: Sequence[str] = _WINDOWS_NAMES
    elif sys.platform == "darwin":
        for place in _MAC_PLACES:
            if Path(place).is_file():
                return Path(place)
        names = ()
    else:
        names = _LINUX_NAMES
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def visitor_profile(home: Path) -> Path:
    """The profile the walks read with, never signed in to anything."""
    return home / "runtime" / "visitor"


def headless_wanted() -> bool:
    raw = os.environ.get(HEADLESS_ENV, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    # Linux with no display has nowhere to put a window.
    return sys.platform.startswith("linux") and not any(os.environ.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY"))


def end_profile(profile: Path, process: subprocess.Popen | None = None) -> None:
    """End every browser process that has `profile` open. A browser leaves
    helper processes behind when only its first one is ended."""
    if process is not None and process.poll() is None:
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=3)
    if os.name == "nt":
        # The first process hands over to another and ends, so they are found by
        # the profile each was started with (quoted in some, bare in others).
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
                  "$_.CommandLine.Contains('--user-data-dir') -and "
                  "$_.CommandLine.Contains($env:MIBO_PROFILE) -and $_.ProcessId -ne $PID } | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        try:
            subprocess.run(["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                           env={**os.environ, "MIBO_PROFILE": str(profile)},
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("browser: leftover processes of a profile were not ended")
        return
    if process is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(["pkill", "-9", "-f", f"user-data-dir={profile}"], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=10)


class Browser:
    """One browser process on one profile, and the connection to it."""

    def __init__(self, profile: Path, *, executable: Path | None = None, headless: bool | None = None):
        self.profile = profile
        self.executable = executable
        self.headless = headless_wanted() if headless is None else headless
        self._driver: Any = None
        self._browser: Any = None
        self.context: Any = None

    async def start(self) -> Any:
        """Start the browser and return its one context."""
        try:
            from playwright.async_api import Error as DriverError
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(NO_DRIVER) from None
        program = self.executable or find_browser()
        if program is None:
            raise RuntimeError(NO_BROWSER)
        self.profile.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(end_profile, self.profile)
        # Driven over a pipe, not a debugging port: a port on 127.0.0.1 answers any
        # other program or user on this computer.
        # Only these flags, none of Playwright's own (they move where a profile keeps its keys).
        arguments = [f"--user-data-dir={self.profile}", "--remote-debugging-pipe",
                     "--no-first-run", "--no-default-browser-check", "--window-size=1280,900",
                     # A window nobody looks at must keep drawing, or a click waits for a frame that never comes.
                     "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                     "--disable-background-timer-throttling"]
        arguments.append("--headless=new" if self.headless else "--start-minimized")
        try:
            starting = asyncio.ensure_future(async_playwright().start())
            try:
                self._driver = await asyncio.shield(starting)
            except asyncio.CancelledError:
                # A start cut off while the driver's process is being made never ends on Windows (Python 3.12
                # and later), and neither does the loop that closes on it, so the app would not exit: the driver
                # is waited for, and stopped below.
                await asyncio.wait({starting})
                self._driver = None if starting.exception() else starting.result()
                raise
            try:
                self.context = await self._driver.chromium.launch_persistent_context(
                    str(self.profile), executable_path=str(program), headless=self.headless, no_viewport=True,
                    ignore_default_args=True, args=[*arguments, "about:blank"], timeout=START_S * 1000)
            except DriverError:
                raise ConnectionError(NO_START) from None
            self._browser = self.context.browser
            self.context.set_default_timeout(STEP_MS)
        except BaseException:
            await self.stop()
            raise
        return self.context

    async def stop(self) -> None:
        """Close the browser the way its window's close button does, then end what is left."""
        browser, driver = self._browser, self._driver
        self._browser = self._driver = self.context = None
        if browser is not None:
            gone = asyncio.Event()
            browser.on("disconnected", lambda *_: gone.set())
            with contextlib.suppress(Exception):
                session = await browser.new_browser_cdp_session()
                await asyncio.wait_for(session.send("Browser.close"), 3)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(gone.wait(), CLOSE_S)
                # The connection drops a moment before the profile is written out.
                await asyncio.sleep(1.0)
        if driver is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(driver.stop(), 5)
        await asyncio.to_thread(end_profile, self.profile)
