"""Which programs the character may operate, decided here in code.

The master switch is off until the person turns it on in Settings. A program is
granted on a card the first time it is needed: this once (for the task asked
for in chat, kept in memory by `hands`), always (kept here, listed in Settings,
revocable), or no. One grant covers looking and operating. A grant names the
program by what cannot be faked by a window title or a look-alike name: for an
app from a package, its package family (name and publisher hash, under
WindowsApps, which only the system writes) and executable name; otherwise the
executable's full path, the name on its signature when it is signed, and for
an unsigned program outside the folders only an administrator can write, the
file's hash, so a file swapped in at the same path is asked about again.

Some programs are never operated, whatever was granted: password managers and
credential dialogs, security and system settings, installers and elevation,
the registry, shells and terminals, other agents and this app itself, banking
and payment programs, anything running as administrator, and the taskbar,
desktop, Start and Run box that share File Explorer's process.

Everything done is written to a log the person can read, one line per action.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from . import win32

# The one switch in Settings and the sentence under it.
SWITCH = {
    "zh": {"label": "允许{who}操作电脑上的其他程序",
           "sentence": "开启后，仅当你在对话中提出要求时，{who}才会查看或操作你逐个允许的程序。发送、删除、购买、更改设置等"
                       "操作每次都需要你确认，可随时按 Esc 停止。始终不操作密码管理器、终端、系统设置和付款程序。"},
    "en": {"label": "Let {who} operate other programs on this computer",
           "sentence": "When on, {who} looks at or operates only the programs you allow one by one, and only while "
                       "you ask in chat. Sending, deleting, buying and changing settings ask you every time, and Esc "
                       "stops it. Password managers, terminals, system settings and payment programs are never "
                       "touched."},
}
DESK_FILE = "desk.json"
LOG_FILE = "desk-log.jsonl"
LOG_KEPT = 2000

# Executable names never operated (lower case).
NEVER_EXE = {
    # shells and terminals
    "cmd.exe", "powershell.exe", "powershell_ise.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe",
    "openconsole.exe", "conhost.exe", "bash.exe", "wsl.exe", "wslhost.exe", "mintty.exe", "git-bash.exe",
    "putty.exe", "kitty.exe", "alacritty.exe", "wezterm-gui.exe", "hyper.exe", "conemu64.exe", "conemu.exe",
    "cmder.exe", "tabby.exe", "termius.exe", "mobaxterm.exe", "xshell.exe", "securecrt.exe",
    # system and security settings, the registry, elevation, credential prompts
    "systemsettings.exe", "control.exe", "mmc.exe", "regedit.exe", "regedt32.exe", "sechealthui.exe",
    "securityhealthsystray.exe", "msconfig.exe", "taskmgr.exe", "useraccountcontrolsettings.exe", "consent.exe",
    "credentialuibroker.exe", "logonui.exe", "lockapp.exe", "rundll32.exe", "dllhost.exe", "gpedit.exe",
    "secpol.exe", "wf.exe", "netplwiz.exe", "lusrmgr.exe", "sysdm.cpl", "optionalfeatures.exe", "msinfo32.exe",
    "perfmon.exe", "resmon.exe", "eventvwr.exe", "services.exe", "winver.exe", "bcdedit.exe", "diskmgmt.exe",
    "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "shellexperiencehost.exe",
    "applicationframehost.exe", "textinputhost.exe", "explorer_run.exe", "pickerhost.exe",
    # installers and stores
    "msiexec.exe", "appinstaller.exe", "winstore.app.exe", "setup.exe", "install.exe", "uninstall.exe",
    "unins000.exe", "installer.exe", "update.exe", "wusa.exe", "dism.exe",
    # password managers
    "1password.exe", "keepass.exe", "keepassxc.exe", "bitwarden.exe", "dashlane.exe", "lastpass.exe",
    "enpass.exe", "roboform.exe", "nordpass.exe", "keeper.exe", "keeperpasswordmanager.exe", "proton pass.exe",
    # other agents
    "claude.exe", "chatgpt.exe", "codex.exe", "cursor.exe", "windsurf.exe", "trae.exe", "copilot.exe",
}
# Words in a program's name, description or product that put it on the never list.
NEVER_WORDS = re.compile(
    r"password|passwort|keepass|bitwarden|1password|lastpass|dashlane|credential|authenticator|密码|凭据|"
    r"\bbank|banking|paypal|alipay|payment|wallet|crypto|bitcoin|brokerage|trading|银行|支付|钱包|证券|期货|理财|"
    r"setup|install|uninstall|安装|卸载|update ?assistant|"
    r"registry|注册表|terminal|终端|powershell|command prompt|命令提示符|console host|"
    r"security|defender|firewall|安全中心|防火墙|control panel|控制面板|"
    r"\bagent\b|claude|chatgpt|codex|copilot|智能体", re.I)
# Window classes never read or touched, whatever process draws them.
NEVER_CLASS = {
    "ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow", "mintty", "PuTTY",
    "VirtualConsoleClass", "Credential Dialog Xaml Host", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman",
    "WorkerW", "TaskManagerWindow", "RegEdit_RegEdit", "MMCMainFrame", "NotifyIconOverflowWindow",
    "Windows.UI.Core.CoreWindow:StartMenuExperienceHost", "$$$Secure UAP Dummy Window Class For Interim Dialog",
    "Shell_Flyout", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland",
}
# Processes that draw many unrelated things (File Explorer is also the taskbar and the desktop): only these
# window classes are the program, and what they own.
SHARED = {"explorer.exe": {"CabinetWClass"}}
# Folders only an administrator or the system writes: a program's path there cannot be swapped by others.
PROTECTED = [os.environ.get(k, "") for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")]


def protected(path: str) -> bool:
    low = path.lower()
    return "\\windowsapps\\" in low or any(p and low.startswith(p.lower() + "\\") for p in PROTECTED)


_facts: dict[tuple, dict] = {}


def identify(pid: int) -> dict:
    """A running program as grants name it: exe, name, signer, package, company, hash (unsigned, unprotected)."""
    exe = win32.exe_of(pid)
    if not exe:
        return {"exe": "", "name": "", "pid": pid}
    st = os.stat(exe)
    key = (exe.lower(), st.st_mtime_ns, st.st_size)
    if key not in _facts:
        facts = win32.file_facts(exe)
        signer = win32.signer(exe)
        digest = ""
        if not signer and not protected(exe):
            with open(exe, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        _facts[key] = {"exe": exe, "name": facts.get("FileDescription") or facts.get("ProductName")
                       or Path(exe).stem, "product": facts.get("ProductName", ""),
                       "company": facts.get("CompanyName", ""), "signer": signer,
                       "package": win32.package_of(exe), "hash": digest}
    return {**_facts[key], "pid": pid}


def program_pid(hwnd: int) -> int:
    """The process a top-level window is the program of: for the frame Windows draws round an app from a
    package (ApplicationFrameHost), the process of the app's own window. That window sits inside the frame
    while the app is drawn; while it is minimised, or not drawn yet, it stands apart under the same title."""
    if win32.class_of(hwnd) != "ApplicationFrameWindow":
        return win32.pid_of(hwnd)
    core = "Windows.UI.Core.CoreWindow"
    title = win32.title_of(hwnd)
    own = next((c for c in win32.child_windows(hwnd) if win32.class_of(c) == core), 0) or next(
        (h for h in win32.top_windows() if win32.class_of(h) == core and win32.title_of(h) == title), 0)
    return win32.pid_of(own or hwnd)


def never(program: dict, hwnd: int = 0) -> str:
    """Why this program, or this window of it, is never operated; "" when it may be granted."""
    exe = program.get("exe", "")
    if not exe:
        return "a protected system process"
    if win32.elevated(program["pid"]):
        return "it runs as administrator"
    if program["pid"] in win32.own_tree():
        return "it is this app itself"
    base = Path(exe).name.lower()
    if base in NEVER_EXE:
        return f"{base} is on the never list"
    for field in ("name", "product"):
        m = NEVER_WORDS.search(str(program.get(field) or ""))
        if m:
            return f"its {field} says {m.group()!r}, which is on the never list"
    m = NEVER_WORDS.search(Path(exe).stem)
    if m:
        return f"its file name says {m.group()!r}, which is on the never list"
    return window_never(base, hwnd) if hwnd else ""


def window_never(base: str, hwnd: int) -> str:
    """Why one window of a granted program (`base` its file name) is still never read; cheap, by class."""
    cls = win32.class_of(hwnd)
    if cls in NEVER_CLASS:
        return f"its window ({cls}) is on the never list"
    allowed = SHARED.get(base)
    if allowed is not None and cls not in allowed and win32.class_of(win32.root_owner(hwnd)) not in allowed:
        return f"that window of {base} is the taskbar, the desktop or a launcher, not the program"
    return ""


def key_of(program: dict) -> str:
    """How a stored grant names a program."""
    if program.get("package"):
        return f"{program['package']}!{Path(program['exe']).name.lower()}"
    return os.path.normcase(os.path.abspath(program["exe"]))


class Grants:
    """The switch, the "always" grants and the log, in the desktop folder."""

    def __init__(self, desktop: Path):
        self.desktop = Path(desktop)
        self.path = self.desktop / DESK_FILE
        self.log_path = self.desktop / LOG_FILE
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"on": False, "grants": []}
        return data if isinstance(data, dict) else {"on": False, "grants": []}

    def _write(self, data: dict) -> None:
        from ..storage import atomic_write_text
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

    def on(self) -> bool:
        return self._read().get("on") is True

    def set_on(self, on: bool) -> dict:
        with self.lock:
            data = self._read()
            data["on"] = bool(on)
            self._write(data)
        self.log({"do": "switch", "line": "turned on" if on else "turned off"})
        return data

    def all(self) -> list[dict]:
        return [g for g in self._read().get("grants") or [] if isinstance(g, dict) and g.get("key")]

    def find(self, program: dict) -> dict | None:
        """The stored grant this running program matches, or None; a signature or a hash that no longer
        matches is no grant."""
        key = key_of(program)
        for g in self.all():
            if g["key"] != key:
                continue
            if g.get("signer") and g["signer"] != program.get("signer"):
                return None
            if g.get("hash") and g["hash"] != program.get("hash"):
                return None
            return g
        return None

    def grant(self, program: dict) -> dict:
        entry = {"key": key_of(program), "name": program.get("name", ""), "exe": program["exe"],
                 "signer": program.get("signer", ""), "package": program.get("package", ""),
                 "hash": program.get("hash", ""), "since": time.strftime("%Y-%m-%d %H:%M")}
        with self.lock:
            data = self._read()
            data["grants"] = [g for g in self.all() if g["key"] != entry["key"]] + [entry]
            self._write(data)
        self.log({"do": "grant", "program": entry["name"], "exe": entry["exe"], "line": "always"})
        return entry

    def revoke(self, key: str) -> bool:
        with self.lock:
            data = self._read()
            kept = [g for g in self.all() if g["key"] != key]
            gone = len(kept) != len(data.get("grants") or [])
            data["grants"] = kept
            self._write(data)
        if gone:
            self.log({"do": "revoke", "line": key})
        return gone

    def log(self, entry: dict) -> None:
        """One line of what was done: when, in which program and window, what, and how it went."""
        line = json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}, ensure_ascii=False)
        with self.lock:
            self.desktop.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            if self.log_path.stat().st_size > LOG_KEPT * 600:
                lines = self.log_path.read_text(encoding="utf-8").splitlines()[-LOG_KEPT:]
                from ..storage import atomic_write_text
                atomic_write_text(self.log_path, "\n".join(lines) + "\n")

    def recent(self, n: int = 200) -> list[dict]:
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
