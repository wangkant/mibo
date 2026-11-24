"""Whether a newer mibo is out, and the update to it.

The check is asked at most once a day, in the background, and its request carries only the version number.

The update (`start`) runs only on a press on the app's own page (panels/runtime.py), never from a tool or the
model, and only to the version the app's own check found: nothing about it comes from the page. What it does
depends on how this copy runs (`way`, read from the copy itself):
- "installer", the Windows installer's copy (its uninstaller beside the program): the release's setup.exe is
  downloaded into the home's runtime/updates, checked, and run with the person's own rights, silently, over this
  copy's own folder (`installer_command`). The app closes for it and the installer opens it again on the same
  home (packaging/windows/mibo.iss); the next start says which version it is (`settle`, `outcome`).
- "macos", the app bundle: the release's disk image is downloaded and checked the same way and opened, and the
  person drags the app to Applications as on the first install. Replacing a running bundle from inside it
  is not clean, and the drag is the step the person already knows.
- "zip", "pip", "checkout", "other": the page says how (a new zip, the pip command, git pull, the release page);
  the app does not rewrite its own folder or Python environment.

What a download must pass before it runs (`_reach`, `_fetch`, `_download`): https only; the listing from
api.github.com and the file from the project's own release download, whose redirects may go only to GitHub's
asset hosts; every hop to a public address (ingestion's guard, the address pinned); no more than the size the
listing states, within DOWNLOAD_WITHIN_S; then that exact size, and the SHA-256 on the file's own line of the
release's SHA256SUMS.txt (and the listing's digest, where it gives one); a release whose tag is the version
asked for, newer than this one. The file is written under a temporary name and named only once it passes, and
it is held shut against writers from its last check until it has started.

What the checksum proves: SHA256SUMS.txt comes from the same origin over TLS, so it catches a damaged,
truncated or swapped download, not someone who controls the repository's releases. Against that, a release may
carry SHA256SUMS.txt.sig, an Ed25519 signature made in the release workflow with a key whose public half is
SIGNING_KEY: a build that carries the key installs only a release whose signature verifies, before anything runs.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from . import __version__, ed25519
from .config_env import env_bool
from .storage import atomic_write_text

# The newest release on the release page, through GitHub's API.
API = "https://api.github.com/repos/wangkant/mibo"
LATEST_URL = API + "/releases/latest"
RELEASE_URL = "https://github.com/wangkant/mibo/releases/tag/v{version}"
DOWNLOAD = "https://github.com/wangkant/mibo/releases/download"
# Where GitHub sends a release file's download on to: release-assets now (curl -I on a v0.1.0 file), objects before.
ASSET_HOSTS = frozenset({"release-assets.githubusercontent.com", "objects.githubusercontent.com"})
CHECK_EVERY_S = 24 * 3600
RETRY_AFTER_S = 3600
# Generous: through some proxies the TLS handshake alone takes seconds.
TIMEOUT_S = 15.0

SUMS = "SHA256SUMS.txt"
SIGNATURE = SUMS + ".sig"
# The Ed25519 public key (base64 of its 32 bytes) whose private half signs SHA256SUMS.txt in the release
# workflow; every build carries it.
SIGNING_KEY = "xTkW93YMokIm6FR3kqHgF2sPspkT/CdeK+2RiKV0uMw="
LISTING_MAX = 1_000_000
SUMS_MAX = 65_536
FILE_MAX = 1_000_000_000
DOWNLOAD_WITHIN_S = 1800.0
READ_WITHIN_S = 30.0
HOPS = 5
# Long enough for the page to show that it is installing before the app closes.
LEAVE_AFTER_S = 2.0
TIDY_TRIES, TIDY_EVERY_S = 30, 2.0
# Windows refusing to start a program for a protection: antivirus (225, 226, or the file taken away: 2), policy
# (1260), Smart App Control or WDAC (4551), and access denied (5).
BLOCKED = frozenset({2, 5, 225, 226, 1260, 4551})
BUSY = frozenset({"downloading", "verifying", "installing"})

_lock = threading.Lock()
_running: set[Path] = set()
# When each home last started a check, so an unwritable cache cannot turn
# the page's polling into a request every few seconds.
_attempted: dict[Path, float] = {}
_enabled: dict[tuple, bool] = {}
# The update under way for each home: its state, version, bytes done and total, and the error it ended on.
_jobs: dict[Path, dict] = {}


def _release(version: str) -> tuple[int, ...] | None:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(int(n) for n in match.groups()) if match else None


def newer(latest: str, current: str = __version__) -> bool:
    """Only a plain X.Y.Z release counts, so a pre-release is never offered."""
    mine = _release(current)
    if mine is None or not re.fullmatch(r"\d+\.\d+\.\d+", latest or ""):
        return False
    return _release(latest) > mine


def enabled(home: Path) -> bool:
    from . import settingsfile

    try:
        stamp = settingsfile.path(home).stat().st_mtime_ns
    except OSError:
        stamp = None
    # Remembered per version of the settings, so a bad value warns once, not every poll.
    key = (str(home), stamp, os.environ.get("UPDATE_CHECK_ENABLED"))
    if key not in _enabled:
        values = settingsfile.values(home, keys=False) if stamp is not None else {}
        values.update(os.environ)  # the environment wins over the settings, as everywhere else
        _enabled[key] = env_bool("UPDATE_CHECK_ENABLED", True, env=values)
    return _enabled[key]


def _cache(home: Path) -> Path:
    return home / "runtime" / "desktop" / "update.json"


def _read(home: Path) -> dict:
    try:
        return json.loads(_cache(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stale(home: Path) -> bool:
    """The last answer is a day old, or an hour old after a failed attempt."""
    last = _read(home)
    checked, wait = last.get("checked"), RETRY_AFTER_S if last.get("failed") else CHECK_EVERY_S
    return checked is None or not 0 <= time.time() - checked < wait


def check(home: Path, timeout: float = TIMEOUT_S) -> str:
    """Ask the release page now and remember the answer; a failure keeps the last one."""
    import httpx

    latest = ""
    try:
        response = httpx.get(LATEST_URL, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": f"mibo/{__version__}"})
        response.raise_for_status()
        latest = str(response.json()["tag_name"]).removeprefix("v")
    except Exception:  # offline, blocked, or an answer of another shape
        pass
    failed = not latest
    latest = latest or str(_read(home).get("latest") or "")
    if home.is_dir():
        with contextlib.suppress(OSError):
            atomic_write_text(_cache(home), json.dumps(
                {"checked": time.time(), "latest": latest, "failed": failed}), fsync=False)
    return latest


def refresh_soon(home: Path) -> None:
    """Ask in the background when the last answer is stale."""
    if not enabled(home) or not stale(home):
        return
    key = home.resolve()
    with _lock:
        now = time.time()
        if key in _running or 0 <= now - _attempted.get(key, 0) < RETRY_AFTER_S:
            return
        _running.add(key)
        _attempted[key] = now

    def run() -> None:
        try:
            check(home)
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=run, name="mibo-update-check", daemon=True).start()


def notice(home: Path, latest: str | None = None, *, always: bool = False) -> dict | None:
    """The newer release the last check found, and its release page.
    `always`: also with the daily check turned off, for someone who asked."""
    if not (always or enabled(home)):
        return None
    latest = str(_read(home).get("latest") or "") if latest is None else latest
    if not newer(latest):
        return None
    return {"version": latest, "url": RELEASE_URL.format(version=latest)}


# ------------------------------------------------------------------------------------------- how this copy runs

def way() -> str:
    """How this copy runs, read from the copy itself: "installer", "zip", "macos", "pip", "checkout" or "other"."""
    from . import home as homes
    program = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        return "checkout" if homes.is_checkout() else "pip"
    if sys.platform == "win32":
        # Inno Setup leaves its uninstaller and its record beside the program it installed; the zip has neither.
        return "installer" if all((program.parent / name).is_file() for name in ("unins000.exe", "unins000.dat")) \
            else "zip"
    if sys.platform == "darwin" and program.parent.name == "MacOS" and program.parents[2].suffix == ".app":
        return "macos"
    return "other"


def command(how: str) -> str:
    """What updates a copy the app does not update itself: pip in this Python, git in the checkout."""
    from . import home as homes
    if how == "pip":
        python = f'"{sys.executable}"' if " " in sys.executable else sys.executable
        return f"{python} -m pip install -U mibo"
    if how == "checkout":
        return f'git -C "{homes.CHECKOUT}" pull'
    return ""


def asset(version: str, how: str) -> str:
    """The release file this way of running installs from."""
    return {"installer": f"mibo-{version}-setup.exe", "macos": f"mibo-{version}-macos-arm64.dmg"}[how]


# ------------------------------------------------------------------------------------------------- the record

def _folder(home: Path) -> Path:
    """Inside the home, so it has the home's protections (setup_wizard.secure_home)."""
    return home / "runtime" / "updates"


def _state_file(home: Path) -> Path:
    return _folder(home) / "state.json"


def _state(home: Path) -> dict:
    try:
        value = json.loads(_state_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save(home: Path, **changes) -> None:
    state = {**_state(home), **changes}
    atomic_write_text(_state_file(home), json.dumps({k: v for k, v in state.items() if v is not None}))


def settle(home: Path) -> None:
    """At start: what became of the update the last run began, and nothing left of its download."""
    state = _state(home)
    pending = state.get("pending")
    if isinstance(pending, dict):
        ok = pending.get("version") == __version__
        # A signed release installed: from here on an unsigned one is refused in this home (`_signed`).
        _save(home, pending=None, signed=True if ok and pending.get("signed") else state.get("signed"),
              outcome={"version": str(pending.get("version") or ""), "from": str(pending.get("from") or ""), "ok": ok})
    elif state.get("outcome"):
        # Said during the start after the update, not again.
        _save(home, outcome=None)
    failed = not (_state(home).get("outcome") or {}).get("ok", True)
    # The installer's log stays while the page says the update failed.
    keep = {"state.json", "setup.log"} if failed else {"state.json"}
    threading.Thread(target=_tidy, args=(_folder(home), keep), name="mibo-update-tidy", daemon=True).start()


def _tidy(folder: Path, keep: set[str]) -> None:
    """Delete what a download left; the installer that opened this start may still be finishing, holding its
    own file and its log, so what is in use is tried again for a minute."""
    for _ in range(TIDY_TRIES):
        left = [path for path in folder.iterdir() if path.name not in keep] if folder.is_dir() else []
        for path in left:
            with contextlib.suppress(OSError):
                path.unlink()
        if not any(path.exists() for path in left):
            return
        time.sleep(TIDY_EVERY_S)


def outcome(home: Path) -> dict | None:
    """The update the run before began, as this start settled it: {version, from, ok, url}; until it is read
    (`dismiss`) or the app starts again."""
    found = _state(home).get("outcome")
    if not isinstance(found, dict) or not found.get("version"):
        return None
    return {**found, "url": RELEASE_URL.format(version=found["version"])}


def dismiss(home: Path) -> None:
    if outcome(home) is not None:
        _save(home, outcome=None)


# ----------------------------------------------------------------------------------------------- the update

class Refused(Exception):
    """An update stopped before anything ran; its code is the page's sentence (setup_about.errors)."""


def job(home: Path) -> dict | None:
    with _lock:
        found = _jobs.get(home.resolve())
        return dict(found) if found else None


def _set(key: Path, **changes) -> None:
    with _lock:
        _jobs[key].update(changes)


def start(home: Path, leave: Callable[[], None]) -> dict:
    """Update to the version the app's own last check found, as this copy runs; `leave` closes the app for the
    installer. Refused when this copy is not updated from inside, when no newer version was found, or while an
    update runs."""
    how = way()
    if how not in ("installer", "macos"):
        raise Refused("update_unsupported")
    found = notice(home, always=True)
    if found is None:
        raise Refused("update_gone")
    key = home.resolve()
    with _lock:
        if (_jobs.get(key) or {}).get("state") in BUSY:
            raise Refused("update_running")
        _jobs[key] = {"state": "downloading", "version": found["version"], "done": 0, "total": 0, "error": ""}
    threading.Thread(target=_run, args=(home, key, found["version"], how, leave), name="mibo-update",
                     daemon=True).start()
    return job(home)


def _run(home: Path, key: Path, version: str, how: str, leave: Callable[[], None]) -> None:
    try:
        path, digest, signed = asyncio.run(asyncio.wait_for(_download(home, key, version, how), DOWNLOAD_WITHIN_S))
    except Refused as refused:
        _set(key, state="failed", error=str(refused))
        return
    except Exception:  # offline, cut off, out of time, or an answer of another shape
        _set(key, state="failed", error="update_unreachable")
        return
    try:
        if how == "installer":
            _save(home, pending={"version": version, "from": __version__, "signed": signed, "at": time.time()})
            launch(path, digest, installer_command(path, home))
            _set(key, state="installing")
            threading.Timer(LEAVE_AFTER_S, leave).start()
        else:
            launch(path, digest, ["/usr/bin/open", str(path)])
            # The person installs it by dragging: from here on, as installed.
            if signed:
                _save(home, signed=True)
            _set(key, state="opened")
    except Refused as refused:
        _undo(home, path)
        _set(key, state="failed", error=str(refused))
    except OSError as error:
        _undo(home, path)
        _set(key, state="failed", error="update_blocked" if getattr(error, "winerror", None) in BLOCKED
             or isinstance(error, FileNotFoundError) else "update_failed")


def _undo(home: Path, path: Path) -> None:
    """Nothing ran: no pending update, and no file."""
    _save(home, pending=None)
    with contextlib.suppress(OSError):
        path.unlink()


async def _reach(url: str, hosts: frozenset[str]) -> tuple[str, str, int] | None:
    """Where one hop may connect, or None: https on its usual port to a host of `hosts`, the project's own
    release downloads on github.com, and every address of the name public (ingestion's guard, which pins one)."""
    from . import ingestion
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or host not in hosts or parts.port not in (None, 443) or parts.username
            or parts.password):
        return None
    if host == "github.com" and not url.startswith(DOWNLOAD + "/"):
        return None
    return await ingestion._resolve_public_target(url)


async def _fetch(url: str, hosts: frozenset[str], cap: int, out=None, seen: Callable[[int], None] | None = None):
    """GET `url` hop by hop, each hop through `_reach` and redirected only within `hosts`; refused past `cap`
    bytes. The body, or with `out` written there and its length."""
    import httpx

    from . import ingestion
    headers = {"User-Agent": f"mibo/{__version__}", "Accept-Encoding": "identity",
               "Accept": "application/vnd.github+json" if url.startswith(API) else "application/octet-stream"}
    for _ in range(HOPS + 1):
        target = await _reach(url, hosts)
        if target is None:
            raise Refused("update_source")
        hostname, address, _port = target
        transport = ingestion._PinnedAsyncHTTPTransport(hostname, address)
        async with httpx.AsyncClient(transport=transport, timeout=READ_WITHIN_S, follow_redirects=False,
                                     trust_env=False) as client, client.stream("GET", url, headers=headers) as answer:
            if answer.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, answer.headers.get("location", ""))
                continue
            if answer.status_code != 200 or answer.headers.get("content-encoding", "identity") != "identity":
                raise Refused("update_unreachable")
            stated = answer.headers.get("content-length", "")
            if stated.isdigit() and int(stated) > cap:
                raise Refused("update_size")
            body, count = bytearray(), 0
            async for chunk in answer.aiter_raw():
                count += len(chunk)
                if count > cap:
                    raise Refused("update_size")
                if out is None:
                    body += chunk
                else:
                    out.write(chunk)
                    if seen:
                        seen(count)
            return bytes(body) if out is None else count
    raise Refused("update_source")


def _sums_line(text: str, name: str) -> str:
    """The SHA-256 on the one line of SHA256SUMS.txt that names exactly `name`."""
    found = set()
    for line in text.splitlines():
        digest, _, named = line.strip().partition(" ")
        if named.strip().lstrip("*") == name:
            found.add(digest.lower())
    if len(found) != 1 or not re.fullmatch(r"[0-9a-f]{64}", next(iter(found))):
        raise Refused("update_mismatch")
    return found.pop()


def _signed(home: Path, sums: bytes, signature: bytes | None) -> bool:
    """Whether the release's signature verified. A build that carries the key takes only a release that key
    signed; one from before the project had a key holds a release to its checksum, unless a signed release was
    installed in this home before."""
    if SIGNING_KEY:
        if signature is None:
            raise Refused("update_unsigned")
        if not ed25519.verify(base64.b64decode(SIGNING_KEY), sums, signature):
            raise Refused("update_badsig")
        return True
    if _state(home).get("signed"):
        raise Refused("update_unsigned")
    return False


async def _download(home: Path, key: Path, version: str, how: str) -> tuple[Path, str, bool]:
    """The release's file for this copy in the home's update folder, checked: (path, its SHA-256, signed)."""
    listing = json.loads(await _fetch(f"{API}/releases/tags/v{version}", frozenset({"api.github.com"}), LISTING_MAX))
    if (not isinstance(listing, dict) or listing.get("tag_name") != f"v{version}" or listing.get("draft")
            or listing.get("prerelease") or not newer(version)):
        raise Refused("update_gone")
    files = {one.get("name"): one for one in listing.get("assets") or [] if isinstance(one, dict)}
    name = asset(version, how)
    if name not in files or SUMS not in files:
        raise Refused("update_gone")
    size, sums_size = files[name].get("size"), files[SUMS].get("size")
    if not (isinstance(size, int) and 0 < size <= FILE_MAX and isinstance(sums_size, int) and sums_size <= SUMS_MAX):
        raise Refused("update_size")
    hosts = frozenset({"github.com"}) | ASSET_HOSTS
    base = f"{DOWNLOAD}/v{version}/"
    sums = await _fetch(base + SUMS, hosts, sums_size)
    signature = await _fetch(base + SIGNATURE, hosts, 64) if SIGNATURE in files else None
    if len(sums) != sums_size:
        raise Refused("update_size")
    signed = _signed(home, sums, signature)
    digest = _sums_line(sums.decode("utf-8", "replace"), name)
    stated = str(files[name].get("digest") or "")
    if stated.startswith("sha256:") and stated.removeprefix("sha256:").lower() != digest:
        raise Refused("update_mismatch")
    folder = _folder(home)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    part, final = folder / f"{name}.{secrets.token_hex(4)}.part", folder / name
    _set(key, total=size)
    try:
        with part.open("xb") as out:
            count = await _fetch(base + name, hosts, size, out, lambda done: _set(key, done=done))
        _set(key, state="verifying")
        if count != size:
            raise Refused("update_size")
        if _sha256_of(part) != digest:
            raise Refused("update_mismatch")
        os.replace(part, final)
    except BaseException:
        part.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise
    return final, digest, signed


def _sha256_of(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256(stream)


def _sha256(stream) -> str:
    found = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        found.update(chunk)
    return found.hexdigest()


@contextlib.contextmanager
def _held(path: Path):
    """The file open so that nothing can write, rename or delete it while it is held: on Windows shared for
    reading alone (and running, which reads); elsewhere the update folder is the person's alone."""
    if os.name != "nt":
        with path.open("rb") as stream:
            yield stream
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
    handle = kernel32.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        error = ctypes.get_last_error()
        raise OSError(None, ctypes.FormatError(error), str(path), error)
    with os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb") as stream:
        yield stream


def installer_command(setup: Path, home: Path) -> str:
    """The installer's command line: no window and no question, over this copy's own folder, waiting for this
    app to close (/WAITPID), and opening it again on `home` afterwards (/RESTARTHOME; mibo.iss). The tasks chosen
    at the first install are kept (Inno Setup's UsePreviousTasks)."""
    folder = Path(sys.executable).parent
    return (f'"{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL /CLOSEAPPLICATIONS '
            f'/DIR="{folder}" /LOG="{setup.with_name("setup.log")}" /WAITPID={os.getpid()} /RESTARTHOME="{home}"')


def launch(path: Path, digest: str, command: str | list[str]) -> None:
    """Start the verified file, held shut from its last check until it has started, as the person: a plain
    CreateProcess (or exec) never raises its rights."""
    with _held(path) as held:
        if _sha256(held) != digest:
            raise Refused("update_changed")
        # A frozen app passes PyInstaller's own variables on; the installer and the app it opens start afresh.
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_") and k != "_MEIPASS2"}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
        subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
