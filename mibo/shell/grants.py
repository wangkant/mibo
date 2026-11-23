"""The person's permissions for commands: the granted folders, the never list, the log.

All of it lives in the desktop folder of the app's home, which no command may
read or change (`blocked` names the home as the app's own). Whether commands
run at all is the one acting mode (acting.py). A fresh home may read the person's
own folders (Desktop, Documents, Downloads, Pictures, Music, Videos); other
folders are granted from a card in the chat or in Settings, and any is taken
back in Settings.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from ..storage import atomic_write_text

SETTINGS_FILE = "shell.json"
LOG_FILE = "shell-log.jsonl"
# The log file keeps this many commands; Settings shows the newest.
LOG_KEPT = 500

# File names that hold keys or passwords wherever they are.
SECRET_NAMES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "wallet.dat", "credentials", ".git-credentials",
                ".netrc", "_netrc", ".npmrc", ".pypirc", "login data", "cookies", "key3.db", "key4.db", "logins.json")
SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".ppk", ".kdbx", ".kdb", ".keychain", ".gpg", ".asc", ".jks",
                   ".keystore", ".ovpn", ".rdp")

# What is never run, as Settings and the card say it.
NEVER = (
    ("以管理员身份运行任何程序或命令", "Anything run as administrator"),
    ("更改安全设置、防火墙、杀毒软件或脚本执行策略", "Changes to security, the firewall, antivirus or the script policy"),
    ("更改系统服务、计划任务、开机启动项、注册表、启动或磁盘设置",
     "Changes to services, scheduled tasks, startup entries, the registry, boot or disk settings"),
    ("读取保存的密码、浏览器资料、密钥文件、其他程序的数据，以及 Mibo 的模型密钥和权限",
     ("Reading saved passwords, browser profiles, key files, other programs' data, or Mibo's own model key and "
      "permissions")),
    ("经过隐藏或编码的命令，以及下载后运行的命令", "Hidden or encoded commands, and downloading something to run it"),
    ("关机、重启或注销", "Shutting down, restarting or signing out"),
)

# The person's own folders, by Windows' own ids for them. They are theirs to work in: reading, listing and making
# or changing a file there needs no grant and no question (deleting, and replacing a file outside what the turn's
# checkpoint can put back, still asks), as a product asks nobody before saving the document they asked for in
# Documents or on the Desktop.
KNOWN = (
    ("downloads", "{374DE290-123F-4565-9164-39C4925E467B}", "下载", "Downloads"),
    ("documents", "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "文档", "Documents"),
    ("desktop", "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "桌面", "Desktop"),
    ("pictures", "{33E28130-4E1E-4676-835A-98395C3BC3BB}", "图片", "Pictures"),
    ("music", "{4BD8D571-6D19-48D3-BE97-422220080E43}", "音乐", "Music"),
    ("videos", "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "视频", "Videos"),
)


def norm(path: str | Path) -> str:
    """A path as compared: absolute, links and junctions followed, `..` gone, case folded."""
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def under(path: str, root: str) -> bool:
    """`path` is `root` or inside it; both already `norm`ed."""
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


# "desktop;documents;downloads;pictures;music;videos" in place of the person's own folders, for tests and the
# measuring scripts' scratch homes: one switch for every known folder the app reads (grants, Settings, backups).
DIRS_ENV = "MIBO_USER_DIRS"
DIRS = ("desktop", "documents", "downloads", "pictures", "music", "videos")


def stand_in(key: str) -> str | None:
    """The folder DIRS_ENV gives in place of the known folder `key` ("" when it gives none), or None when unset."""
    given = os.environ.get(DIRS_ENV, "").strip()
    return dict(zip(DIRS, given.split(os.pathsep))).get(key, "") if given else None


def known_folder(guid: str) -> str:
    """A known folder's real place (Downloads may be moved, Documents may be in OneDrive), or its stand-in from
    DIRS_ENV; "" when none."""
    key = next((row[0] for row in KNOWN if row[1] == guid), "")
    given = stand_in(key) if key else None
    if given is not None:
        return given
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    parts = guid.strip("{}").split("-")
    tail = bytes.fromhex(parts[3] + parts[4])
    folder = GUID(int(parts[0], 16), int(parts[1], 16), int(parts[2], 16), (ctypes.c_ubyte * 8)(*tail))
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(out)) != 0:
        return ""
    try:
        return out.value or ""
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


# The Public Desktop, which File Explorer shows as part of the person's own Desktop.
PUBLIC_DESKTOP = "{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}"


def own_folders() -> list[str]:
    """The person's own folders (KNOWN), and the Public Desktop beside their real Desktop (not beside a stand-in)."""
    mine = [row["path"] for row in known_folders()]
    public = known_folder(PUBLIC_DESKTOP) if stand_in("desktop") is None else ""
    return mine + ([public] if public and os.path.isdir(public) else [])


def known_folders() -> list[dict]:
    rows = []
    for key, guid, zh, en in KNOWN:
        path = known_folder(guid)
        if path and os.path.isdir(path):
            rows.append({"key": key, "path": path, "zh": zh, "en": en})
    return rows


class Places:
    """The protected places of this computer and this app, worked out once."""

    def __init__(self, home: Path):
        env = os.environ
        profile = env.get("USERPROFILE") or str(Path.home())
        temp = env.get("TEMP") or env.get("TMP") or ""
        system_root = env.get("SystemRoot") or r"C:\Windows"
        self.home = norm(home)
        self.package = norm(Path(__file__).resolve().parents[1])
        self.python = norm(sys.prefix)
        self.profile = norm(profile)
        self.appdata = norm(os.path.join(profile, "AppData"))
        self.temp = norm(temp) if temp else ""
        self.windows = norm(system_root)
        self.programs = [norm(p) for p in {env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("ProgramW6432"),
                                           env.get("ProgramData")} if p]
        # PowerShell's own profile and module folders: what is written there runs in the person's PowerShell.
        documents = known_folder(KNOWN[1][1]) or os.path.join(profile, "Documents")
        self.startup = [norm(os.path.join(documents, d)) for d in ("WindowsPowerShell", "PowerShell")]
        self.drive = norm((env.get("SystemDrive") or "C:") + "\\")
        # Skills' folders, the person's and the built-in ones: read and run from (asking, as outside any granted
        # folder), never written (skills/).
        self.skills = [norm(Path(home) / "skills"), norm(Path(self.package) / "skills" / "builtin")]

    def blocked(self, path: str, write: bool) -> str:
        """Why a command may never touch this `norm`ed path ("app", "secrets", "system"), or ""."""
        if not write and any(under(path, own) and path != own for own in self.skills):
            return ""
        if any(under(path, own) for own in (self.home, self.package, self.python)):
            return "app"
        if under(path, self.appdata) and not (self.temp and under(path, self.temp)):
            return "secrets"
        rest = path[len(self.profile):].lstrip("\\/") if under(path, self.profile) else ""
        if rest.startswith("."):
            return "secrets"
        # Windows drops trailing dots and spaces, and reads "name::$DATA" as the file itself.
        name = os.path.basename(path).split(":")[0].rstrip(". ")
        if write and any(under(path, p) for p in self.startup):
            return "system"
        if (name in SECRET_NAMES or name.startswith((".env", "id_rsa", "id_ed25519", "id_ecdsa"))
                or name.endswith(SECRET_SUFFIXES)):
            return "secrets"
        if under(path, os.path.join(self.windows, "system32", "config")):
            return "secrets"
        if write and (under(path, self.windows) or any(under(path, p) for p in self.programs)
                      or os.path.dirname(path) == self.drive.rstrip("\\") or path == self.drive):
            return "system"
        return ""

    def grantable(self, path: str) -> str:
        """Why this `norm`ed folder cannot be granted ("missing", "root", "app", "secrets", "system", "wide"), or ""."""
        if not os.path.isdir(path):
            return "missing"
        if os.path.dirname(path.rstrip("\\/")) == path.rstrip("\\/") or len(path.rstrip("\\/")) <= 3:
            return "root"
        why = self.blocked(path, True)
        if why:
            return why
        # A folder that holds the places above would hand them over with it.
        protected = [self.home, self.appdata, self.windows, *self.programs, self.package, self.python]
        if any(under(p, path) for p in protected) or under(self.profile, path):
            return "wide"
        return ""


class Grants:
    """The granted folders in `desktop`/shell.json, and the log beside it."""

    def __init__(self, desktop: Path, home: Path):
        self.desktop = Path(desktop)
        self.places = Places(home)
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads((self.desktop / SETTINGS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.desktop.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.desktop / SETTINGS_FILE, json.dumps(data, ensure_ascii=False, indent=1))

    def folders(self) -> list[str]:
        """Granted folders: the ones they chose and the person's own (own_folders), those still grantable."""
        kept = [str(p) for p in self._read().get("folders") or [] if isinstance(p, str)]
        seen, out = set(), []
        for place in kept + own_folders():
            if norm(place) not in seen and not self.places.grantable(norm(place)):
                seen.add(norm(place))
                out.append(place)
        return out

    def read_only(self) -> set[str]:
        """The granted folders, `norm`ed, where files may be read but nothing made, moved or changed: never the
        person's own."""
        own = {norm(p) for p in own_folders()}
        return {norm(p) for p in self._read().get("read_only") or [] if isinstance(p, str)} - own

    def roots(self, write: bool = False) -> list[str]:
        """The granted folders, `norm`ed; with `write`, only those that may be changed."""
        kept = self.read_only() if write else set()
        return [r for r in (norm(p) for p in self.folders()) if r not in kept]

    def root_of(self, path: str) -> str:
        """The granted folder a `norm`ed path is in (the innermost), or ""."""
        hits = [r for r in self.roots() if under(path, r)]
        return max(hits, key=len) if hits else ""

    def folder_of(self, root: str) -> str:
        """A `norm`ed granted folder as the person chose it."""
        return next((p for p in self.folders() if norm(p) == root), root)

    def add(self, folder: str, read_only: bool = False) -> str:
        """Grants a folder, to read only or to change too; the reason it cannot be granted, or ""."""
        real = os.path.realpath(os.path.abspath(folder))
        why = self.places.grantable(norm(real))
        if why:
            return why
        with self.lock:
            data = self._read()
            kept = [p for p in data.get("folders") or [] if isinstance(p, str) and norm(p) != norm(real)]
            data["folders"] = [*kept, real]
            data["read_only"] = [p for p in data.get("read_only") or [] if isinstance(p, str) and norm(p) != norm(real)]
            if read_only:
                data["read_only"].append(real)
            self._write(data)
        return ""

    def remove(self, folder: str) -> None:
        with self.lock:
            data = self._read()
            for key in ("folders", "read_only"):
                data[key] = [p for p in data.get(key) or [] if isinstance(p, str) and norm(p) != norm(folder)]
            data["rules"] = [r for r in self._rules(data) if norm(r["folder"]) != norm(folder)]
            self._write(data)

    @staticmethod
    def _rules(data: dict) -> list[dict]:
        return [r for r in data.get("rules") or [] if isinstance(r, dict) and isinstance(r.get("program"), str)
                and isinstance(r.get("folder"), str)]

    def rules(self) -> list[dict]:
        """The person's always-allow rules, a program in a granted folder each ({program, shown, folder, at}), the
        ones whose folder is still granted."""
        roots = {norm(p) for p in self.folders()}
        return [r for r in self._rules(self._read()) if norm(r["folder"]) in roots]

    def allowed(self, program: str, root: str) -> bool:
        """`program` (a `norm`ed file) is always allowed in the `norm`ed granted folder `root`."""
        return any(r["program"] == program and norm(r["folder"]) == root for r in self.rules())

    def allow(self, program: str, shown: str, root: str) -> None:
        """Keeps 对此程序在此文件夹始终允许 as a rule, which Settings lists and can take back."""
        with self.lock:
            data = self._read()
            data["rules"] = [r for r in self._rules(data) if not (r["program"] == program and norm(r["folder"]) == root)]
            data["rules"].append({"program": program, "shown": shown, "folder": self.folder_of(root), "at": time.time()})
            self._write(data)

    def forget(self, program: str, folder: str) -> None:
        with self.lock:
            data = self._read()
            data["rules"] = [r for r in self._rules(data)
                             if not (r["program"] == program and norm(r["folder"]) == norm(folder))]
            self._write(data)

    def log(self, entry: dict) -> None:
        """One command, how it was sorted and decided and what came of it, appended to the log file."""
        path = self.desktop / LOG_FILE
        self.desktop.mkdir(parents=True, exist_ok=True)
        with self.lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.time(), **entry}, ensure_ascii=False) + "\n")
            if path.stat().st_size > 2_000_000:
                lines = path.read_text(encoding="utf-8").splitlines()[-LOG_KEPT:]
                atomic_write_text(path, "\n".join(lines) + "\n")

    def log_rows(self, n: int = 40) -> list[dict]:
        try:
            lines = (self.desktop / LOG_FILE).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in reversed(lines[-n:]):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def clear_log(self) -> None:
        (self.desktop / LOG_FILE).unlink(missing_ok=True)
