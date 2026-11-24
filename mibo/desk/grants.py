"""Which programs the character may operate, decided here in code.

Whether it operates programs at all is the one acting mode (acting.py). Any
program that is not on the never list below is used for a task the person asked
for in chat with no card to grant it, and what it does there goes through the
gate (gate.py) and the reviewer. A grant kept here (from earlier, listed in
Settings, revocable) only sets a program's tier. A grant names the program by
what cannot be faked by a window title or a look-alike name: for an app from a
package, its package family (name and publisher hash, under WindowsApps, which
only the system writes) and executable name; otherwise the executable's full
path, the name on its signature when it is signed, and for an unsigned program
outside the folders only an administrator can write, the file's hash.

Some programs are never operated, whatever was granted: password managers and
credential dialogs, security and system settings, installers and elevation,
the registry, shells and terminals, other agents and this app itself, banking
and payment programs, anything running as administrator, and the taskbar,
desktop, Start and Run box that share File Explorer's process; and any whose
name holds a word the person added to their own list (`blocked`).

A granted program has a tier, as Claude's computer use gives one: full; click
(it presses but types nothing: an IDE, whose terminal pane runs what is typed);
or view (it only looks: a web browser, whose pages go through the app's own
browser and its gate instead). The person can change it per program.

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
TIERS = ("full", "click", "view")
# The tier a program gets until the person changes it: web browsers look only, IDEs and editors with a terminal
# pane press only.
VIEW_EXE = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "iexplore.exe",
            "360se.exe", "360chrome.exe", "qqbrowser.exe", "sogouexplorer.exe", "2345explorer.exe", "arc.exe",
            "chromium.exe", "maxthon.exe", "liebao.exe", "ucbrowser.exe", "quark.exe", "thorium.exe", "waterfox.exe"}
CLICK_EXE = {"code.exe", "code - insiders.exe", "vscodium.exe", "devenv.exe", "idea64.exe", "pycharm64.exe",
             "webstorm64.exe", "goland64.exe", "clion64.exe", "rider64.exe", "phpstorm64.exe", "rubymine64.exe",
             "datagrip64.exe", "studio64.exe", "sublime_text.exe", "zed.exe", "fleet.exe", "eclipse.exe",
             "spyder.exe", "rstudio.exe", "hbuilderx.exe"}
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


def default_tier(exe: str) -> str:
    base = Path(exe).name.lower()
    return "view" if base in VIEW_EXE else "click" if base in CLICK_EXE else "full"


def key_of(program: dict) -> str:
    """How a stored grant names a program."""
    if program.get("package"):
        return f"{program['package']}!{Path(program['exe']).name.lower()}"
    return os.path.normcase(os.path.abspath(program["exe"]))


class Grants:
    """The kept grants (a program's tier), the person's never list and the log, in the desktop folder."""

    def __init__(self, desktop: Path):
        self.desktop = Path(desktop)
        self.path = self.desktop / DESK_FILE
        self.log_path = self.desktop / LOG_FILE
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"grants": []}
        return data if isinstance(data, dict) else {"grants": []}

    def _write(self, data: dict) -> None:
        from ..storage import atomic_write_text
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

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

    def tier(self, program: dict) -> str:
        """The tier of a running program: its stored grant's, else the default for its executable."""
        found = self.find(program)
        return found.get("tier") if found and found.get("tier") in TIERS else default_tier(program.get("exe", ""))

    def set_tier(self, key: str, tier: str) -> None:
        with self.lock:
            data = self._read()
            data["grants"] = [{**g, "tier": tier} if g["key"] == key else g for g in self.all()]
            self._write(data)
        self.log({"do": "tier", "line": f"{key}: {tier}"})

    def blocked(self) -> list[str]:
        return [w for w in self._read().get("block") or [] if isinstance(w, str) and w.strip()]

    def block(self, word: str, on: bool) -> list[str]:
        """The person's own never list: a word that, in a program's name or file name, keeps it from being
        operated."""
        word = " ".join(word.split())[:60]
        with self.lock:
            data = self._read()
            data["block"] = [w for w in self.blocked() if w.lower() != word.lower()] + ([word] if on and word else [])
            self._write(data)
        self.log({"do": "block" if on else "unblock", "line": word})
        return data["block"]

    def blocked_by(self, program: dict) -> str:
        """The word of the person's own list this program's name or file name holds, or ""."""
        said = " ".join(str(program.get(k) or "") for k in ("name", "product")) + " " + Path(program.get("exe", "")).name
        return next((w for w in self.blocked() if w.lower() in said.lower()), "")

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
