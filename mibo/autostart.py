"""Start at sign-in, on by default: the first time the app opens it turns
itself on, and remembers that it did, so turning it off later stays off.
Windows: the Startup shortcut (shortcut.py). macOS: a LaunchAgent that opens
the app behind its icon."""
from __future__ import annotations

import hashlib
import plistlib
import sys
import threading
from pathlib import Path

from . import home as homes
from . import shortcut

MACOS = sys.platform == "darwin"
# The LaunchAgent that opens the app.
LABEL = "com.github.wangkant.mibo.app"
# Saved in runtime/desktop/app.json once the default was applied or the person chose.
CHOSEN = "login_set"


def frozen() -> bool:
    """The installer's build (PyInstaller), not a Python environment."""
    return bool(getattr(sys, "frozen", False))


def supported() -> bool:
    return shortcut.WINDOWS or MACOS


def command(home: Path) -> list[str]:
    """What opens the app for `home` behind its icon."""
    if frozen():
        return [sys.executable, "start", "--home", str(home), "--background"]
    return [sys.executable, "-m", "mibo", "start", "--home", str(home), "--background"]


def _own_suffix(home: Path) -> str:
    """'' for the usual home, a short tag of its path for any other."""
    home = Path(home).resolve()
    usual = homes.CHECKOUT if homes.is_checkout() else homes.default_home()
    if home == Path(usual).resolve():
        return ""
    return "-" + hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:8]


def plist_path(home: Path) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}{_own_suffix(home)}.plist"


def status(home: Path) -> str:
    """"on", "other" (another copy or home) or "off". RuntimeError when Windows cannot be asked."""
    if shortcut.WINDOWS:
        return shortcut.status(home)["startup"]
    path = plist_path(home)
    if not path.is_file():
        return "off"
    try:
        same = plistlib.loads(path.read_bytes()).get("ProgramArguments") == command(home)
    except (OSError, plistlib.InvalidFileException):
        return "other"
    return "on" if same else "other"


def set_login(home: Path, on: bool) -> str:
    """Turn start at sign-in on or off for `home`; what went wrong, or ''."""
    if shortcut.WINDOWS:
        try:
            return shortcut.run(shortcut.script(home, remove=not on, kinds=shortcut.LOGIN))
        except ValueError:
            return "redirected folders"
    path = plist_path(home)
    try:
        if not on:
            path.unlink(missing_ok=True)
            return ""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Loaded by launchd at the next sign-in; loading it now would open a second app.
        path.write_bytes(plistlib.dumps({
            "Label": path.stem, "ProgramArguments": command(home), "WorkingDirectory": str(home),
            "RunAtLoad": True, "ProcessType": "Interactive"}, sort_keys=False))
    except OSError as error:
        return str(error)
    return ""


def remember(home: Path) -> None:
    from .welcome import save_app_settings
    desktop = home / "runtime" / "desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    save_app_settings(desktop, **{CHOSEN: True})


def first_run(home: Path) -> None:
    """Turn start at sign-in on the first time the app opens for the usual home.
    A --home of its own is left alone: Windows keeps one Startup link for all homes."""
    from .welcome import app_settings
    if (not supported() or _own_suffix(home)
            or app_settings(home / "runtime" / "desktop").get(CHOSEN)):
        return
    if MACOS and frozen() and (sys.executable.startswith("/Volumes/") or "/AppTranslocation/" in sys.executable):
        return  # opened from the disk image: the first start from Applications does it
    # The Windows installer asked already, with a checkbox of its own. A link or
    # agent of another copy is kept.
    if not (shortcut.WINDOWS and frozen()) and status(home) == "off" and set_login(home, True):
        return  # tried again at the next start
    remember(home)


def first_run_soon(home: Path) -> None:
    # Beside the start: PowerShell takes a second the window need not wait for.
    threading.Thread(target=first_run, args=(home,), name="mibo-login", daemon=True).start()
