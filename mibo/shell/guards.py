"""Guards: entries the app places on folders, files and registry keys outside its home, which only its commands'
tokens are refused by (confine.sids), so a command misread or misled cannot read the person's secrets or plant
something that runs later, whatever path it takes there.

Each guard is one explicit deny entry for one of the app's SIDs, at the head of the place's access list and inherited
by everything in it. The person's own programs never carry those SIDs, so the browser reading its profile, ssh its
keys and Explorer the Startup folder are exactly as before: their tokens, plain, at low integrity or in an
AppContainer, pass the entry by. What is guarded (`places`):
- "app": the home (everything; its skills' folder read and run), the app's package and its Python (writes);
- "secrets", GUARD_SID: browser profiles, password managers, wallets and chat sessions, never touched by a command
  that is not a program's run;
- "keys", OFFLINE_SID: network tools' credentials (.ssh, .aws, .azure, .kube, .docker, gcloud, gh, .claude,
  .codex, .git-credentials, .netrc, .pypirc), which only a command read as using the network reaches, so that a
  push the person asked for still signs in;
- "later", GUARD_SID: places that make code run later, written only by a program's run: the Startup folder and
  the folders above it, PowerShell's profile folders, the shell's rc files, and the keys Windows starts things from
  (Run, RunOnce, Environment, the user's classes, the shell folders, Command Processor, Winlogon, Policies).

Kept (`Keeper`): placed at start in a thread of its own, every place recorded in the home (desktop/guards.json)
before its entry is written and marked done when Windows has carried it down, so a start cut short is finished by
the next; looked at again before each command (a guard's place made since is guarded then, and a small one is
walked, so a file moved in with its old access list is given the entry); files whose inheritance is off get an
entry of their own. Removed from Settings, on reset and on uninstall (`remove`): the app's entries are taken out,
by their SID, and Windows carries the removal down; nothing else in an access list changes.
"""
from __future__ import annotations

import contextlib
import ctypes
import functools
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from ..storage import atomic_write_text
from . import confine
from .acts import CODE_SIGNS
from .confine import COMMANDS_SID, DWORD, GUARD_SID, LPWSTR, OFFLINE_SID, Unconfined, _api, _done, _ok

RECORD = ("runtime", "desktop", "guards.json")
# A stand-in for every place found here (tests and the measuring scripts): a folder laid out as a profile
# (profile/AppData/Roaming, profile/AppData/Local, documents, python, package) and a key under HKCU\Software in
# place of HKCU. Empty: no place at all, only the home.
PLACES_ENV = "MIBO_GUARD_PLACES"
KEYS_ENV = "MIBO_GUARD_KEYS"
# A place with fewer entries than this is walked before each command, for files moved in since.
SMALL = 400

SE_FILE_OBJECT, SE_REGISTRY_KEY = 1, 4
DACL_INFO = 0x4
PROTECTED_DACL, UNPROTECTED_DACL = 0x80000000, 0x20000000
SE_DACL_PROTECTED, SE_DACL_AUTO_INHERITED, SE_DACL_AUTO_INHERIT_REQ = 0x1000, 0x400, 0x100
SDDL_REVISION_1 = 1
HKEY_CURRENT_USER = 0x80000001
READ_CONTROL, WRITE_DAC = 0x20000, 0x40000
READ_CONTROL_WRITE_DAC = READ_CONTROL | WRITE_DAC
ACCESS_ALLOWED, ACCESS_DENIED, INHERITED = 0, 1, 0x10
# What is denied: everything, or every way to change (data, attributes, the entry list, the owner, deleting it or
# what is in it, and for a key its values and subkeys).
FILE_ALL, KEY_ALL = 0x1F01FF, 0xF003F
FILE_WRITES = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000
KEY_WRITES = 0x2 | 0x4 | 0x20 | 0x10000 | 0x40000 | 0x80000
DELETE = 0x10000
# A folder kept where it is: not deleted or renamed by its own list, and nothing in it by the folder's right over
# what it holds (FILE_DELETE_CHILD), which Windows honours whatever the held thing's own list refuses.
STAYS = DELETE | 0x40
FILE_READ_EXECUTE = 0x1200A9
OURS = (COMMANDS_SID, GUARD_SID, OFFLINE_SID)

# Under the local and roaming AppData: what a command that is not a program's run never touches.
SECRETS = (
    ("local", r"Google\Chrome\User Data"), ("local", r"Google\Chrome Beta\User Data"),
    ("local", r"Microsoft\Edge\User Data"), ("local", r"BraveSoftware\Brave-Browser\User Data"),
    ("local", r"Vivaldi\User Data"), ("local", r"Chromium\User Data"), ("local", r"Yandex\YandexBrowser\User Data"),
    ("roaming", r"Mozilla\Firefox\Profiles"), ("roaming", r"Opera Software"), ("roaming", r"Waterfox\Profiles"),
    ("local", "1Password"), ("roaming", "Bitwarden"), ("roaming", "KeePassXC"), ("local", "KeePassXC"),
    ("roaming", "Bitcoin"), ("roaming", "Electrum"), ("roaming", "Exodus"), ("roaming", "Ethereum"),
    ("roaming", "atomic"), ("roaming", "Telegram Desktop"), ("roaming", "discord"), ("roaming", "Signal"),
    ("roaming", "Slack"), ("local", r"Packages\5319275A.WhatsAppDesktop_cv1g1gvanyjgm"),
)
# In the profile and the roaming AppData: network tools' sign-ins, read by a command read as using the network.
KEYS = (".ssh", ".aws", ".azure", ".kube", ".docker", r".config\gcloud", ".claude", ".codex", ".git-credentials",
        ".netrc", "_netrc", ".pypirc")
KEYS_ROAMING = ("gh", "GitHub CLI")
# What the person's shells run at their start.
RC_FILES = (".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zprofile")
STARTUP = r"Microsoft\Windows\Start Menu\Programs\Startup"
# Keys under HKCU that Windows starts things from or finds folders by; made, empty, where missing.
LATER_KEYS = (r"Software\Microsoft\Windows\CurrentVersion\Run", r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
              r"Software\Microsoft\Windows\CurrentVersion\Policies",
              r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
              r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
              r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon",
              r"Software\Microsoft\Windows NT\CurrentVersion\Windows", r"Software\Microsoft\Command Processor",
              "Environment", r"Software\Classes")


class Place:
    """One guard: the place (a path, or "HKCU\\..." for a key), its kind, the SID refused, what is refused, whether
    everything in it inherits the entry, why ("app", "secrets", "keys", "later"), and whether it is made when
    missing."""

    def __init__(self, path: str, why: str, sid: str, mask: int, kind: str = "file", inherit: bool = True,
                 make: bool = False, skip: str = ""):
        self.path, self.why, self.sid, self.mask, self.kind = path, why, sid, mask, kind
        # A folder inside that keeps its own list (the home's skills).
        self.inherit, self.make, self.skip = inherit, make, skip

    @property
    def flags(self) -> str:
        if not self.inherit:
            return ""
        return "CI" if self.kind == "key" else ("OICI" if os.path.isdir(self.path) else "")

    @property
    def ace(self) -> str:
        """The entry, as SDDL writes it."""
        return f"(D;{self.flags};0x{self.mask:x};;;{self.sid})"

    def exists(self) -> bool:
        return _key_exists(self.path) if self.kind == "key" else os.path.lexists(self.path)


# ---------------------------------------------------------------- where


def _stand_in() -> str | None:
    return os.environ.get(PLACES_ENV)


def _keys_root() -> str:
    """HKCU, or the stand-in key in its place."""
    given = os.environ.get(KEYS_ENV)
    return f"HKCU\\{given}" if given else "HKCU"


def _up_to(path: str, top: str) -> list[str]:
    """`path` and the folders above it up to `top`; with `path` kept somewhere else, it and its parent."""
    if not (path.lower() + os.sep).startswith(top.lower() + os.sep):
        top = os.path.dirname(path)
    found = [path]
    while len(found[-1]) > len(top):
        found.append(os.path.dirname(found[-1]))
    return found


def places(home: Path) -> list[Place]:
    """Every guard of this computer and this app, the home's first."""
    from .grants import KNOWN, known_folder
    home_path = os.path.realpath(home)
    found = [Place(home_path, "app", COMMANDS_SID, FILE_ALL, skip=os.path.join(home_path, confine.SKILLS))]
    given = _stand_in()
    if given == "":
        return found
    if given is not None:
        profile = os.path.join(given, "profile")
        roaming, local = os.path.join(profile, "AppData", "Roaming"), os.path.join(profile, "AppData", "Local")
        documents = os.path.join(given, "documents")
        package, python = os.path.join(given, "package"), os.path.join(given, "python")
    else:
        if sys.platform != "win32":
            return found
        profile = os.environ.get("USERPROFILE") or str(Path.home())
        roaming = os.environ.get("APPDATA") or os.path.join(profile, "AppData", "Roaming")
        local = os.environ.get("LOCALAPPDATA") or os.path.join(profile, "AppData", "Local")
        documents = known_folder(KNOWN[1][1]) or os.path.join(profile, "Documents")
        package, python = str(Path(__file__).resolve().parents[1]), sys.prefix
    # The app's own code and Python: read and run, never changed (a frozen app's package is inside its Python).
    for path in dict.fromkeys(os.path.realpath(p) for p in (python, package)):
        if not any(path.lower().startswith(f.path.lower() + os.sep) or path.lower() == f.path.lower()
                   for f in found[1:]):
            found.append(Place(path, "app", COMMANDS_SID, FILE_WRITES))
    base = {"local": local, "roaming": roaming}
    found += [Place(os.path.join(base[where], rel), "secrets", GUARD_SID, FILE_ALL) for where, rel in SECRETS]
    found += [Place(os.path.join(profile, rel), "keys", OFFLINE_SID, FILE_ALL) for rel in KEYS]
    found += [Place(os.path.join(roaming, rel), "keys", OFFLINE_SID, FILE_ALL) for rel in KEYS_ROAMING]
    startup = os.path.join(roaming, STARTUP)
    found.append(Place(startup, "later", GUARD_SID, FILE_WRITES, make=True))
    found += [Place(os.path.join(documents, d), "later", GUARD_SID, FILE_WRITES, make=True)
              for d in ("WindowsPowerShell", "PowerShell")]
    # The folders above them, up to the profile: renamed, one would take a guarded folder away from the place
    # Windows looks for it, and a new one could be made there.
    above = dict.fromkeys(_up_to(os.path.dirname(startup), profile) + _up_to(documents, profile))
    found += [Place(p, "later", GUARD_SID, STAYS, inherit=False) for p in above]
    found += [Place(os.path.join(profile, name), "later", GUARD_SID, FILE_WRITES, inherit=False) for name in RC_FILES]
    root = _keys_root()
    found += [Place(f"{root}\\{key}", "later", GUARD_SID, KEY_WRITES, kind="key", make=True) for key in LATER_KEYS]
    return found


# ---------------------------------------------------------------- one entry list
#
# Entries are written object by object with SetFileSecurity and RegSetKeySecurity, which write exactly the list given
# and carry nothing down by themselves, and the app carries its entry down as Windows would: an inherited copy on
# everything inside. So taking it out again leaves every other bit of every list as it was, which SetNamedSecurityInfo,
# marking each list it rewrites as auto-inherited, would not; and a walk cut short is finished by walking again.


def _object(place_path: str, kind: str) -> tuple[str, int]:
    """The name and type GetNamedSecurityInfo takes."""
    if kind == "key":
        return "CURRENT_USER" + place_path[len("HKCU"):], SE_REGISTRY_KEY
    return place_path, SE_FILE_OBJECT


@functools.cache
def _api2():
    k32, adv = _api()
    p, d = ctypes.c_void_p, DWORD
    for name, args, res in (
            ("ConvertSecurityDescriptorToStringSecurityDescriptorW", [p, d, d, ctypes.POINTER(LPWSTR),
                                                                      ctypes.POINTER(d)], ctypes.c_int),
            ("SetFileSecurityW", [LPWSTR, d, p], ctypes.c_int),
            ("GetFileSecurityW", [LPWSTR, d, p, d, ctypes.POINTER(d)], ctypes.c_int),
            ("RegGetKeySecurity", [p, d, p, ctypes.POINTER(d)], ctypes.c_long),
            ("SetSecurityDescriptorControl", [p, ctypes.c_uint16, ctypes.c_uint16], ctypes.c_int),
            ("RegOpenKeyExW", [p, LPWSTR, d, d, ctypes.POINTER(p)], ctypes.c_long),
            ("RegSetKeySecurity", [p, d, p], ctypes.c_long),
            ("RegCloseKey", [p], ctypes.c_long)):
        fn = getattr(adv, name)
        fn.argtypes, fn.restype = args, res
    return k32, adv


def sddl(place_path: str, kind: str = "file", what: int = DACL_INFO) -> str:
    """The object's security descriptor as stored, in SDDL (its entry list by default). Read as stored, not through
    GetNamedSecurityInfo, which on a list not marked auto-inherited works out which entries came from the parent
    and shows the rest as protected."""
    k32, adv = _api2()
    size = DWORD()
    if kind == "key":
        key = ctypes.c_void_p()
        _done(adv.RegOpenKeyExW(ctypes.c_void_p(HKEY_CURRENT_USER), place_path[len("HKCU\\"):], 0, READ_CONTROL,
                                ctypes.byref(key)), f"RegOpenKeyEx {place_path}")
        try:
            adv.RegGetKeySecurity(key, what, None, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            _done(adv.RegGetKeySecurity(key, what, buf, ctypes.byref(size)), f"RegGetKeySecurity {place_path}")
        finally:
            adv.RegCloseKey(key)
    else:
        adv.GetFileSecurityW(place_path, what, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        _ok(adv.GetFileSecurityW(place_path, what, buf, size, ctypes.byref(size)), f"GetFileSecurity {place_path}")
    text = LPWSTR()
    _ok(adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(buf, SDDL_REVISION_1, what, ctypes.byref(text),
                                                                None), "ConvertSecurityDescriptorToString")
    try:
        return text.value
    finally:
        k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))




def _write(place_path: str, kind: str, dacl: str) -> None:
    """Writes `dacl` (SDDL, "D:...", its flags included) as the object's entry list, to it alone."""
    k32, adv = _api2()
    descriptor = ctypes.c_void_p()
    _ok(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(dacl, SDDL_REVISION_1, ctypes.byref(descriptor),
                                                                None), "ConvertStringSecurityDescriptor")
    try:
        if "AI" in _split(dacl)[0]:
            # The auto-inherited mark is written only when asked for with it.
            bits = SE_DACL_AUTO_INHERITED | SE_DACL_AUTO_INHERIT_REQ
            _ok(adv.SetSecurityDescriptorControl(descriptor, bits, bits), "SetSecurityDescriptorControl")
        if kind == "key":
            key = ctypes.c_void_p()
            _done(adv.RegOpenKeyExW(ctypes.c_void_p(HKEY_CURRENT_USER), place_path[len("HKCU\\"):], 0,
                                    READ_CONTROL_WRITE_DAC, ctypes.byref(key)), f"RegOpenKeyEx {place_path}")
            try:
                _done(adv.RegSetKeySecurity(key, DACL_INFO, descriptor), f"RegSetKeySecurity {place_path}")
            finally:
                adv.RegCloseKey(key)
        else:
            _ok(adv.SetFileSecurityW(place_path, DACL_INFO, descriptor), f"SetFileSecurity {place_path}")
    finally:
        k32.LocalFree(descriptor)


ACE = re.compile(r"\((?P<type>[A-Z]+);(?P<flags>[A-Z]*);(?P<rights>[^;]*);[^;]*;[^;]*;(?P<sid>[^)]*)\)")


def _split(dacl: str) -> tuple[str, list[re.Match]]:
    """("D:<flags>", its entries)."""
    head = dacl[:dacl.find("(")] if "(" in dacl else dacl
    return head, list(ACE.finditer(dacl))


@functools.cache
def _rights(mask: int) -> str:
    """`mask` as SDDL writes it back ("FA", "DCLCRPDTCRSDWDWO"), to know the app's own entries by."""
    k32, adv = _api2()
    descriptor = ctypes.c_void_p()
    _ok(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(f"D:(D;;0x{mask:x};;;WD)", SDDL_REVISION_1,
                                                                ctypes.byref(descriptor), None), "ConvertString")
    try:
        text = LPWSTR()
        _ok(adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, SDDL_REVISION_1, DACL_INFO,
                                                                    ctypes.byref(text), None), "ConvertSD")
        try:
            return ACE.search(text.value)["rights"]
        finally:
            k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        k32.LocalFree(descriptor)


def _mine(m: re.Match, sid: str, mask: int) -> bool:
    return m["type"] == "D" and m["sid"] == sid and m["rights"] == _rights(mask)


def _add(path: str, kind: str, sid: str, mask: int, container: bool, root: bool) -> str:
    """Gives one object the entry: at the head of its list on the guarded place itself (`root`) and on an object
    whose list is protected or has entries of its own allowing something (which would come before an inherited
    deny), else as an inherited copy before its inherited entries. "own", "copy", or "" when it had it already."""
    dacl = sddl(path, kind)
    head, entries = _split(dacl)
    if any(_mine(m, sid, mask) for m in entries):
        return ""
    own = root or "P" in head[2:] or any(m["type"] == "A" and "ID" not in m["flags"] and m["sid"] not in OURS
                                         for m in entries)
    flags = (("CI" if kind == "key" else "OICI") if container else "") + ("" if own else "ID")
    ace = f"(D;{flags};0x{mask:x};;;{sid})"
    at = 0 if own else next((i for i, m in enumerate(entries) if "ID" in m["flags"]), len(entries))
    texts = [m[0] for m in entries]
    _write(path, kind, head + "".join([*texts[:at], ace, *texts[at:]]))
    return "own" if own and not root else "copy"


def _take(path: str, kind: str, sid: str, mask: int) -> None:
    """Takes the entry, own or inherited, out of one object's list, and nothing else."""
    dacl = sddl(path, kind)
    head, entries = _split(dacl)
    kept = [m[0] for m in entries if not _mine(m, sid, mask)]
    if len(kept) != len(entries):
        _write(path, kind, head + "".join(kept))


def _skills(path: str, row: dict) -> str:
    return os.path.join(path, confine.SKILLS) if row.get("why") == "app" and row.get("mask") == FILE_ALL else ""


def _inside(place_path: str, kind: str, skip: str = ""):
    """Everything inside a guarded place, parents before what is in them: (path, is a container). Links are given
    the entry, not followed; `skip` and what is in it are left out."""
    if kind == "key":
        import winreg
        stack = [place_path[len("HKCU\\"):]]
        while stack:
            sub = stack.pop()
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
                    names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
            except OSError:
                continue
            for name in names:
                yield "HKCU\\" + sub + "\\" + name, True
                stack.append(sub + "\\" + name)
        return
    stack = [place_path]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if skip and os.path.normcase(entry.path) == os.path.normcase(skip):
                continue
            folder = entry.is_dir(follow_symlinks=False)
            yield entry.path, folder
            if folder and not entry.is_symlink() and not _reparse(entry.path):
                stack.append(entry.path)


def _guard(place: Place) -> tuple[int, int, int]:
    """The entry on the place and, when inherited, on everything inside: (how many objects inside, how many of them
    were given an entry of their own, how many could not be given it)."""
    container = place.kind == "key" or os.path.isdir(place.path)
    _add(place.path, place.kind, place.sid, place.mask, container and place.inherit, root=True)
    count = own = missed = 0
    if place.inherit and container:
        for path, folder in _inside(place.path, place.kind, place.skip):
            count += 1
            try:
                own += _add(path, place.kind, place.sid, place.mask, folder, root=False) == "own"
            except Unconfined:
                # Given the entry on the next pass, which walks again while any is missing.
                missed += 1
    return count, own, missed


def _unguard(place_path: str, kind: str, sid: str, mask: int, inherit: bool, skip: str = "") -> None:
    """The entry out of the place and everything inside, each list otherwise as it was."""
    _take(place_path, kind, sid, mask)
    if inherit:
        for path, _ in _inside(place_path, kind, skip):
            with contextlib.suppress(Unconfined):
                _take(path, kind, sid, mask)


def carries(place_path: str, kind: str, sid: str) -> bool:
    """The object carries a deny entry for `sid`, its own or inherited."""
    return any(m["type"] == "D" and m["sid"] == sid for m in _split(sddl(place_path, kind))[1])


def _key_exists(place_path: str) -> bool:
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, place_path[len("HKCU\\"):]))
        return True
    except OSError:
        return False


def _exists(path: str, kind: str) -> bool:
    return _key_exists(path) if kind == "key" else os.path.lexists(path)


def _make(place: Place) -> str:
    """Makes a missing place, and the folders or keys above it that are missing too: the highest one made."""
    top, up = place.path, os.path.dirname(place.path) if place.kind == "file" else place.path.rpartition("\\")[0]
    while up and not _exists(up, place.kind):
        top = up
        up = os.path.dirname(up) if place.kind == "file" else up.rpartition("\\")[0]
    if place.kind == "key":
        import winreg
        winreg.CloseKey(winreg.CreateKey(winreg.HKEY_CURRENT_USER, place.path[len("HKCU\\"):]))
    else:
        os.makedirs(place.path, exist_ok=True)
    return top


def _unmake(top: str, kind: str) -> bool:
    """What the app made from `top` down, taken away again where nothing was put there since: whether it is gone."""
    import winreg
    try:
        if kind == "key":
            sub = top[len("HKCU\\"):]
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
                subkeys, values, _ = winreg.QueryInfoKey(key)
                names = [winreg.EnumKey(key, i) for i in range(subkeys)]
            # Each child is tried, so that the empty ones go even where another is kept.
            gone = [_unmake(top + "\\" + name, kind) for name in names]
            if values or not all(gone):
                return False
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        else:
            gone = [_unmake(entry.path, kind) for entry in os.scandir(top) if entry.is_dir(follow_symlinks=False)]
            if not all(gone):
                return False
            os.rmdir(top)
    except OSError:
        return False
    return True


def _reparse(path: str) -> bool:
    try:
        return bool(os.stat(path, follow_symlinks=False).st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------- the record and its keeper


class Keeper:
    """The guards of one home: placed, recorded, looked at again, removed."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.path = self.home.joinpath(*RECORD)
        self.lock = threading.RLock()
        self.first = threading.Event()
        self.thread: threading.Thread | None = None
        self.error = ""

    # The record: {"on": bool, "places": {path: {...}}}. A place is written there before its entry is, with
    # "done" null until Windows has carried the entry down.
    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("on", True)
        data.setdefault("places", {})
        return data

    def write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

    def start(self) -> None:
        """The first pass, in a thread of its own; commands wait for it (`ready`)."""
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self._first, name="guards", daemon=True)
                self.thread.start()

    def _first(self) -> None:
        try:
            self.keep()
        except Exception as e:  # recorded and shown; the home's own guard is checked again before each command
            self.error = str(e)
        finally:
            self.first.set()

    def ready(self) -> None:
        """Before a command: the first pass finished, the places looked at again (new ones guarded, small ones walked).
        Unconfined when a guard of the app's own places is not there."""
        self.start()
        self.first.wait()
        self.keep()

    def keep(self) -> dict:
        """One pass: each place there guarded, a guard not finished finished, small ones walked."""
        with self.lock:
            data = self.read()
            on = data["on"]
            for place in places(self.home):
                if place.why != "app" and not on:
                    continue
                key = place.path
                row = data["places"].get(key)
                try:
                    self._one(place, row, data)
                except Unconfined as e:
                    if place.why == "app":
                        raise
                    data["places"].setdefault(key, {}).update(failed=f"{e.strerror or e}", at=time.time())
                    self.write(data)
            return data

    def _one(self, place: Place, row: dict | None, data: dict) -> None:
        made = (row or {}).get("made") or ""
        if not place.exists():
            if not place.make:
                if row:
                    del data["places"][place.path]
                    self.write(data)
                return
            made = _make(place)
        if place.kind == "file" and _reparse(place.path):
            data["places"][place.path] = {"why": place.why, "kind": place.kind, "skipped": "link"}
            return
        if row and row.get("mask") not in (None, place.mask):
            # Placed by a version that refused something else there: that entry is taken out and this one written.
            _unguard(place.path, place.kind, row["sid"], row["mask"], row.get("inherit", True),
                     skip=_skills(place.path, row))
            row = None
        done = bool(row and row.get("done") and not row.get("failed"))
        if done and carries(place.path, place.kind, place.sid):
            # Only a small one is walked again, for files moved in since with the list they had: a browser's
            # profile or the app's own folders are written to only by their own programs, which make files there.
            if not place.inherit or place.why == "app" or row.get("count", 0) >= SMALL:
                return
            if not any(not carries(path, place.kind, place.sid) for path, _ in _inside(place.path, place.kind)):
                return
        else:
            # Recorded before the entry is written: a start cut short leaves "done" empty, and the next walks again.
            row = {"why": place.why, "kind": place.kind, "sid": place.sid, "mask": place.mask,
                   "inherit": place.inherit, "ace": place.ace, "made": made,
                   "placed": time.time(), "done": None}
            data["places"][place.path] = row
            self.write(data)
        if place.skip:
            # The skills' folder: read and run by commands, so the home's entry is not carried into it.
            os.makedirs(place.skip, exist_ok=True)
            dacl = sddl(place.skip)
            head, entries = _split(dacl)
            if not any(m["type"] == "A" and m["sid"] == COMMANDS_SID and "ID" not in m["flags"] for m in entries):
                _write(place.skip, "file", head + f"(A;OICI;0x{FILE_READ_EXECUTE:x};;;{COMMANDS_SID})"
                       + "".join(m[0] for m in entries))
        count, own, missed = _guard(place)
        row.update(done=None if missed else row.get("done") or time.time(), count=count,
                   own=row.get("own", 0) + own, missed=missed)
        row.pop("failed", None)
        self.write(data)

    def remove(self, everything: bool = False) -> dict:
        """Takes the guards out: those of other places (Settings, which also turns them off until turned on again),
        or with `everything` the app's own too (reset, uninstall). Each list is left as it was before the entry."""
        with self.lock:
            data = self.read()
            made: list[tuple[str, str]] = []
            for path, row in list(data["places"].items()):
                if row.get("why") == "app" and not everything:
                    continue
                kind = row.get("kind", "file")
                if row.get("skipped") or not _exists(path, kind):
                    del data["places"][path]
                    continue
                try:
                    sid, mask, inherit = row["sid"], row["mask"], row.get("inherit", True)
                    _unguard(path, kind, sid, mask, inherit, skip=_skills(path, row))
                    skills = _skills(path, row)
                    if skills and os.path.isdir(skills):
                        dacl = sddl(skills)
                        head, entries = _split(dacl)
                        _write(skills, "file", head + "".join(
                            m[0] for m in entries
                            if not (m["type"] == "A" and m["sid"] == COMMANDS_SID and "ID" not in m["flags"])))
                    if row.get("made"):
                        made.append((row["made"] if isinstance(row["made"], str) else path, kind))
                    del data["places"][path]
                except (Unconfined, KeyError) as e:
                    row["failed"] = f"{getattr(e, 'strerror', None) or e}"
            # What the app made (folders and keys for the guards to sit on), deepest first, once every guard is out.
            for top, kind in sorted(set(made), key=lambda m: -len(m[0])):
                _unmake(top, kind)
            if not everything:
                data["on"] = False
            self.write(data)
            return data

    def turn_on(self) -> dict:
        with self.lock:
            data = self.read()
            data["on"] = True
            self.write(data)
        return self.keep()

    def view(self) -> dict:
        """What Settings lists: whether the guards are on, and each place with why, when and the entry itself."""
        data = self.read()
        rows = [{"path": path, "why": row.get("why", ""), "kind": row.get("kind", "file"), "ace": row.get("ace", ""),
                 "done": row.get("done"), "failed": row.get("failed", ""), "own": row.get("own", 0)}
                for path, row in data["places"].items() if not row.get("skipped")]
        return {"on": data["on"], "places": rows, "error": self.error}


_KEEPERS: dict[str, Keeper] = {}
_KEEPERS_LOCK = threading.Lock()


def keeper(home: Path) -> Keeper:
    real = os.path.realpath(home)
    with _KEEPERS_LOCK:
        if real not in _KEEPERS:
            _KEEPERS[real] = Keeper(Path(real))
        return _KEEPERS[real]


def guarded(path: str, home: Path) -> Place | None:
    """The guard a path is under, if any (for the line that says why a command was refused)."""
    low = os.path.normcase(os.path.abspath(path))
    for place in places(home):
        root = os.path.normcase(place.path)
        if place.kind == "file" and (low == root or (place.inherit and low.startswith(root.rstrip("\\") + "\\"))):
            return place
    return None


# Windows' own refusal as programs word it, with the path where they give one.
DENIED = re.compile(r"Access to the path '[^']+' is denied|Access is denied|access denied|"
                    r"UnauthorizedAccess|PermissionDenied|Permission denied|"
                    r"Requested registry access is not allowed|unauthorized operation", re.IGNORECASE)
WHY = {
    "app": "it is Mibo's own folder or code, which no command may read or change",
    "secrets": "it holds saved passwords, browser data or sign-ins, which only a program the person had opened may use",
    "keys": ("it holds network sign-ins (keys, tokens), which only a command read as using the network may use; "
             "run the step that needs them (a push, a sign-in) as its own command"),
    "later": ("writing there makes something run later (at sign-in, in every shell, by Windows), which only a program "
              "run the person allowed may do"),
}


QUOTED_PATH = re.compile(r"'([A-Za-z]:\\[^']*)'|\b([A-Za-z]:\\[^\s'\":]+)")
# Kinds of act after which a command may use the network and its sign-ins: one read as reaching it, and one the
# reading could not bound (ssh, a cloud tool), which the person allows each time it runs.
ONLINE_KINDS = ("network", "system", "unknown")


def online(acts: list) -> bool:
    """Whether a command read as `acts` runs with the network and network tools' sign-ins (confine.sids)."""
    return any(a.kind in ONLINE_KINDS and a.what not in CODE_SIGNS for a in acts)


def refused_line(err: str, tier: str, online: bool, home: Path) -> str:
    """One line for the model when Windows' limits stopped a command: which limit and why, and what to do. "" when
    the error is not a refusal, or not one of the app's."""
    if not DENIED.search(err or ""):
        return ""
    for quoted, bare in QUOTED_PATH.findall(err):
        path = quoted or bare
        place = guarded(path, home)
        if place is None:
            continue
        if place.why == "keys" and (online or tier == "program"):
            continue
        if place.why in ("secrets", "later") and tier == "program":
            continue
        return f"Windows refused {path} because {WHY[place.why]}."
    if tier == "read":
        return ("Windows refused the change because this command was read as only reading; run the change as a "
                "command of its own that plainly makes it.")
    return ""


def main(argv: list[str], prog: str) -> int:
    """`mibo guards [show|on|off|remove]`: what is guarded; turn the guards of other places on or off; remove every
    guard, the home's too (the uninstaller runs this)."""
    import argparse

    from .. import home as home_mod
    p = argparse.ArgumentParser(prog=prog)
    p.add_argument("what", nargs="?", choices=("show", "on", "off", "remove"), default="show")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        return 0
    k = keeper(home_mod.find_home())
    if args.what == "on":
        k.turn_on()
    elif args.what in ("off", "remove"):
        k.remove(everything=args.what == "remove")
    print(json.dumps(k.view(), ensure_ascii=False, indent=1))
    return 0
