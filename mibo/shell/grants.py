"""The person's permissions for commands: the granted folders, the never list, the log.

All of it lives in the desktop folder of the app's home, which no command may
read or change (`blocked` names the home as the app's own, which holds the model
keys' file, the settings and the browser pane's profile). Whether commands run
at all is the one acting mode (acting.py). A fresh home is granted the person's
own folders (Desktop, Documents, Downloads, Pictures, Music, Videos), and the
rest of the profile and the other drives are open too (`open`), less the
protected places, and so are the files of tool results the app keeps whole
(spill.py), to reads; folders elsewhere on the system drive are granted from a
question in the chat or in Settings. Any is set to read only or taken back in
Settings, the person's own folders too, and that holds until they grant it again.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from .. import spill
from ..storage import atomic_write_text
from .pstables import OPEN_RISKY

# What runs when it is opened (and a .pth, which every start of its Python loads): a file of these replaced is a
# program changed.
RUNS_LATER = (*OPEN_RISKY, ".pth")

SETTINGS_FILE = "shell.json"
LOG_FILE = "shell-log.jsonl"
# The log file keeps this many commands; Settings shows the newest.
LOG_KEPT = 500

# File names that hold keys or passwords wherever they are.
SECRET_NAMES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "wallet.dat", "credentials", ".git-credentials",
                ".netrc", "_netrc", ".npmrc", ".pypirc", "login data", "cookies", "key3.db", "key4.db", "logins.json",
                "local state", "web data", "state.vscdb", ".credentials.json", "credentials.json", ".vault-token",
                "cert9.db", "places.sqlite")
SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".ppk", ".kdbx", ".kdb", ".keychain", ".gpg", ".asc", ".jks",
                   ".keystore", ".ovpn", ".rdp", ".1pux", ".opvault", ".psafe3")
# Folders that hold keys, tokens and sign-ins wherever they are: under any root and at any depth (a backup of a
# profile, another drive, a WSL export, another user's profile), by their parts as `norm` folds them.
SECRET_DIRS = ((".ssh",), (".aws",), (".gnupg",), (".kube",), (".docker",), (".azure",), (".claude",), (".codex",),
               (".gcloud",), (".password-store",), (".terraform.d",), (".pki",), (".mozilla",), (".thunderbird",),
               (".config", "gcloud"), (".config", "gh"), (".local", "share", "keyrings"), ("user data",),
               ("appdata",))
# A user's folder in a profile tree ("Users\me", "home/me"): its dot children are its settings and keys.
PROFILE_TOPS = ("users", "home", "documents and settings")
# Program places by their parts, where Start's search finds programs: listed and looked at (a name, a size, dates)
# like any open place on any root; what is in their files is judged as any read. AppData's own folders are
# looked at two levels down (AppData\Local\Kingsoft\WPS Office: whether a program is there), no further.
FINDABLE = (("program files",), ("program files (x86)",), ("appdata", "roaming", "microsoft", "windows", "start menu"),
            ("programdata", "microsoft", "windows", "start menu"), ("appdata", "local", "programs"))
APPDATA_LOOK = 4
# What runs, or is loaded, by itself once written, without the person starting it: a write there is asked every
# time as a costly system step (cardwait.COSTLY), whatever folder it is in. By parts of the path: a package
# manager's or a program's own tree (TREES: what is taken out of one changes a program too), Git's hooks and
# settings, shell start-up folders, Startup, scheduled tasks.
TREES = (("site-packages",), ("dist-packages",), ("node_modules",), ("program files",), ("program files (x86)",),
         ("programdata",))
RUNS_PLACES = (*TREES, ("profile.d",), (".git", "hooks"), (".git", "config"), (".git", "info", "attributes"),
               ("start menu", "programs", "startup"), ("system32", "tasks"), ("windowspowershell",), (".vscode",))
# Files that run when a shell, PowerShell or a drive starts.
RUNS_NAMES = (".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zprofile", ".zshenv", ".zlogin",
              ".cshrc", ".tcshrc", ".kshrc", ".inputrc", "profile.ps1", "microsoft.powershell_profile.ps1",
              "microsoft.vscode_powershell_profile.ps1", "autorun.inf", "desktop.ini", "sitecustomize.py",
              "usercustomize.py", ".gitattributes", ".gitmodules", "pip.ini", "pip.conf", ".envrc", ".npmrc")
# A virtual environment's activation scripts (in its Scripts or bin folder), run each time it is activated.
ACTIVATE = ("activate", "activate.bat", "activate.ps1", "activate.fish", "activate.csh", "activate.nu",
            "activate_this.py")
# A project's own tool files, run by the tools that build and test it (npm, make, pip, pytest, pre-commit), and a
# new shortcut: never costly and never written by rule, they go to the reviewer on the person's words each time,
# and are asked after the turn read outside material (shell/panel.py).
PROJECT_FILES = ("package.json", "makefile", "gnumakefile", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
                 "noxfile.py", "conftest.py", ".pre-commit-config.yaml")

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

# The person's own folders, by Windows' own ids for them. They are granted from the start: reading, listing and
# making or changing a file there needs no grant (what the asking rule asks, it still asks), as a product asks
# nobody before saving the document they asked for in Documents or on the Desktop. Settings may set one to read only
# or take it back.
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


def parts_of(path: str) -> list[str]:
    """A `norm`ed path's folder and file names, lower case, with what Windows drops (trailing dots and spaces, a
    ::$DATA stream) dropped too."""
    return [p.split(":")[0].rstrip(". ") if i else p for i, p in enumerate(re.split(r"[\\/]+", path.lower())) if p]


def link_names(path: str) -> list[str]:
    """Every other name of a file that has more than one (hard links), `norm`ed, as Windows lists them
    (FindFirstFileNameW): a secret reached by a second name is still the secret. [] for a file with one name."""
    try:
        if sys.platform != "win32" or os.stat(path).st_nlink < 2:
            return []
    except OSError:
        return []
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.FindFirstFileNameW.restype = wintypes.HANDLE
    k32.FindFirstFileNameW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                       wintypes.LPWSTR]
    k32.FindNextFileNameW.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR]
    k32.FindClose.argtypes = [wintypes.HANDLE]
    drive, names = os.path.splitdrive(path)[0], []
    size = wintypes.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    handle = k32.FindFirstFileNameW(path, 0, ctypes.byref(size), buf)
    if handle in (None, wintypes.HANDLE(-1).value):
        return []
    try:
        while True:
            names.append(norm(drive + buf.value))
            size = wintypes.DWORD(32768)
            if not k32.FindNextFileNameW(handle, ctypes.byref(size), buf):
                break
    finally:
        k32.FindClose(handle)
    return [n for n in names if n != path]


def holds(parts: list[str], run: tuple) -> int:
    """Where `run` (a few names in a row) begins among `parts`, or -1."""
    return next((i for i in range(len(parts) - len(run) + 1) if tuple(parts[i:i + len(run)]) == run), -1)


def _program_folder(folder: str) -> bool:
    """A folder a program runs from: it holds a program or a library already."""
    try:
        return any(e.name.lower().endswith((".exe", ".dll")) for e in os.scandir(folder) if e.is_file())
    except OSError:
        return False


def git_credentials(path: str) -> bool:
    """A Git repository's settings that hold a sign-in: a password or token in a remote's address, or an
    Authorization header Git sends."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(65536)
    except OSError:
        return False
    return bool(re.search(r"://[^/\s@:]+:[^/\s@]+@|extraheader\s*=.*authorization|\b(?:token|password)\s*=", text,
                          re.I))


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
        # Where programs and their shortcuts are, as Start's search reads them: Program Files, the Start menu's
        # folders for the person and for everyone, and per-user installs. They hold no secrets: read and listed
        # like any open place, never written.
        menu = os.path.join("Microsoft", "Windows", "Start Menu")
        self.findable = [norm(p) for p in {env.get("ProgramFiles"), env.get("ProgramFiles(x86)"),
                                           env.get("ProgramW6432")} if p] + [
            norm(os.path.join(self.appdata, "Roaming", menu)),
            norm(os.path.join(env.get("ProgramData") or r"C:\ProgramData", menu)),
            norm(os.path.join(self.appdata, "Local", "Programs"))]
        # PowerShell's own profile and module folders: what is written there runs in the person's PowerShell.
        documents = known_folder(KNOWN[1][1]) or os.path.join(profile, "Documents")
        self.startup = [norm(os.path.join(documents, d)) for d in ("WindowsPowerShell", "PowerShell")]
        self.drive = norm((env.get("SystemDrive") or "C:") + "\\")
        # Skills' folders, the person's and the built-in ones: read and run from (asking, as outside any granted
        # folder), never written (skills/).
        self.skills = [norm(Path(home) / "skills"), norm(Path(self.package) / "skills" / "builtin")]
        # Tool results kept whole for the model to read back (spill.py): its files are read, never written.
        self.spill = norm(spill.folder(home))
        # The folders programs are looked up in: what is written there runs in place of a program of the same name.
        self.path_dirs = {norm(p) for p in env.get("PATH", "").split(os.pathsep) if p.strip()}

    def blocked(self, path: str, write: bool, names: str = "", receives: bool = True) -> str:
        """Why a command may not touch this `norm`ed path: "app" (this app's own) and "secrets" (keys, sign-ins,
        other programs' data) are never touched; "system" (Windows', a program's or a drive's own files) is changed
        only on the person's yes each time (read.judge). "" when it is none of them. Names, sizes and dates (`names`:
        "look" at one place, "shallow" or "deep" for a listing of a folder or of all below it) are free in the program
        places Start reads (FINDABLE); a look, two levels into AppData (whether a program is installed there), at
        anything but a file. Nothing of a secret's place is free, not even whether it is there."""
        if not write and any(under(path, own) and path != own for own in (*self.skills, self.spill)):
            return ""
        if any(under(path, own) for own in (self.home, self.package, self.python)):
            return "app"
        parts = parts_of(path)
        # A file's other names, wherever this one is: a second name never makes a secret readable.
        if any(self.secret(other, parts_of(other)) or under(other, self.home) for other in link_names(path)):
            return "secrets"
        # The temporary folder is inside AppData and is no program's data: a place in it is judged by what follows it.
        if self.temp and under(path, self.temp):
            parts = parts[len(parts_of(self.temp)):]
        if not write and names and not self.secret(path, parts, SECRET_DIRS[:-1]):
            if any(holds(parts, run) >= 0 for run in FINDABLE):
                return ""
            top = holds(parts, ("appdata",))
            if names == "look" and top >= 0 and len(parts) - top <= APPDATA_LOOK and not os.path.isfile(path):
                return ""
        if write and holds(parts, ("appdata",)) >= 0 and not any(holds(parts, d) >= 0 for d in SECRET_DIRS[:-1]):
            return "system"
        if self.secret(path, parts):
            return "secrets"
        if write and self.runs_later(path, receives):
            return "system"
        return ""

    def secret(self, path: str, parts: list[str], dirs: tuple = SECRET_DIRS) -> bool:
        """A place that holds keys, tokens, sign-ins or other programs' data, on any root and at any depth."""
        name = parts[-1] if parts else ""
        if any(holds(parts, d) >= 0 for d in dirs) or under(path, os.path.join(self.windows, "system32", "config")):
            return True
        if under(path, self.profile) and path[len(self.profile):].lstrip("\\/").startswith("."):
            return True
        if any(parts[i] in PROFILE_TOPS and parts[i + 2].startswith(".") for i in range(len(parts) - 2)):
            return True
        if name in SECRET_NAMES or name.startswith((".env", "id_rsa", "id_ed25519", "id_ecdsa")) or name.endswith(
                SECRET_SUFFIXES):
            return True
        return len(parts) >= 2 and parts[-2:] == [".git", "config"] and git_credentials(path)

    def runs_later(self, path: str, receives: bool = True) -> str:
        """Why a file written at this `norm`ed path would run, or be loaded, without the person starting it: a
        program's or a package manager's own tree, a folder on PATH, Git's hooks, a shell's or PowerShell's start-up
        file, Startup, a scheduled task, a drive's root; or a runnable file that is there already and would be
        replaced. A file taken away (deleted, moved out: not `receives`) starts nothing: only a program's tree,
        Windows' folder and PATH count then. "" for anywhere else."""
        parts = parts_of(path)
        unc = path.startswith("\\\\")
        if not receives:
            tree = next((run for run in TREES if holds(parts[:-1], run) >= 0), None)
            if tree or (not unc and len(parts) > 2 and parts[1] == "windows") or os.path.dirname(path) in self.path_dirs:
                return "it changes a program's or Windows' own files"
            return ""
        hit = next((run for run in RUNS_PLACES if holds(parts[:-1] if len(run) == 1 else parts, run) >= 0), None)
        if hit:
            return f"{os.sep.join(hit)} runs or loads what is written there"
        if parts and parts[-1] in RUNS_NAMES:
            return f"{parts[-1]} runs when a shell, PowerShell, Git, pip or a drive starts"
        if len(parts) > 2 and parts[-1] in ACTIVATE and parts[-2] in ("scripts", "bin"):
            return "a virtual environment runs it each time it is activated"
        if len(parts) <= (3 if unc else 2):
            return "a drive's root runs what is written there when the drive is opened"
        if not unc and parts[1] == "windows":
            return "Windows' own folder runs what is written there"
        if any(under(path, p) for p in self.startup) or os.path.dirname(path) in self.path_dirs:
            return "a folder on PATH or PowerShell's own profile runs what is written there"
        if os.path.isfile(path) and os.path.splitext(path)[1] in RUNS_LATER and parts[-1] not in PROJECT_FILES:
            return "it replaces a file that runs"
        if os.path.splitext(path)[1] in RUNS_LATER and _program_folder(os.path.dirname(path)):
            return "a program's own folder loads what is written beside it"
        return ""

    def grantable(self, path: str) -> str:
        """Why this `norm`ed folder cannot be granted ("missing", "root", "app", "secrets", "system", "wide"), or ""."""
        if not os.path.isdir(path):
            return "missing"
        if os.path.dirname(path.rstrip("\\/")) == path.rstrip("\\/") or len(path.rstrip("\\/")) <= 3:
            return "root"
        why = self.blocked(path, True) or ("system" if any(under(path, p) for p in [self.windows, *self.programs])
                                           else "")
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
        """Granted folders: the ones they chose and the person's own (own_folders) unless they took one back in
        Settings, those still grantable."""
        data = self._read()
        kept = [str(p) for p in data.get("folders") or [] if isinstance(p, str)]
        removed = {norm(p) for p in data.get("removed") or [] if isinstance(p, str)}
        seen, out = set(removed), []
        for place in kept + own_folders():
            if norm(place) not in seen and not self.places.grantable(norm(place)):
                seen.add(norm(place))
                out.append(place)
        return out

    def read_only(self) -> set[str]:
        """The granted folders, `norm`ed, where files may be read but nothing made, moved or changed: the person's
        own among them when they set one so in Settings."""
        return {norm(p) for p in self._read().get("read_only") or [] if isinstance(p, str)}

    def roots(self, write: bool = False) -> list[str]:
        """The granted folders, `norm`ed; with `write`, only those that may be changed."""
        kept = self.read_only() if write else set()
        return [r for r in (norm(p) for p in self.folders()) if r not in kept]

    def held_back(self, path: str, write: bool) -> bool:
        """A `norm`ed place inside a folder the person took back in Settings, or, for a change, one they set to
        read only: it stays as they set it, open places or not."""
        data = self._read()
        back = [norm(p) for p in data.get("removed") or [] if isinstance(p, str)]
        return any(under(path, r) for r in back + (sorted(self.read_only()) if write else []))

    def open(self, path: str, write: bool = False) -> bool:
        """A `norm`ed place the character may use under the mode with no folder granted first: inside a granted
        folder, or anywhere in the person's profile or on a drive other than Windows' own, unless the person took
        it back or set it to read only (`held_back`). What is protected (Places.blocked) is refused before this is
        asked."""
        if any(under(path, r) for r in self.roots(write)):
            return True
        places = self.places
        if not write and under(path, places.spill) and path != places.spill:
            return True
        return (under(path, places.profile) or not under(path, places.drive)) and not self.held_back(path, write)

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
            for key in ("read_only", "removed"):
                data[key] = [p for p in data.get(key) or [] if isinstance(p, str) and norm(p) != norm(real)]
            if read_only:
                data["read_only"].append(real)
            self._write(data)
        return ""

    def remove(self, folder: str) -> None:
        """Takes a folder back; it stays taken back (`removed`) until it is granted again."""
        with self.lock:
            data = self._read()
            for key in ("folders", "read_only", "removed"):
                data[key] = [p for p in data.get(key) or [] if isinstance(p, str) and norm(p) != norm(folder)]
            # Taken back, it stays so (held_back) until it is granted again, whether or not it was one of theirs.
            data["removed"].append(folder)
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
