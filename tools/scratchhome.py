"""A scratch home for a measuring script, and the environment its app runs with. A run leaves nothing of the
person's behind and reads nothing of the computer it happens on:

* The model's key reaches the app only through its environment. The app's credential store is `Keys` below
  (PYTHON_KEYRING_BACKEND), which reads a key from the environment and holds one the app saves in memory, as the
  test suite's stand-in does: no .env, no key in settings.json, nothing in this computer's credential store.
* settings.json holds the rest, the model's address and name among them (the page reads them there).
* The person's computer is an empty folder beside the home (<home>-pc): its Desktop, Documents, Downloads,
  Pictures, Music and Videos are granted to read in place of the person's own, which a fresh home grants, and every
  known folder the app reads (MIBO_USER_DIRS) and its shortcut folders point into it. It is the app's profile too
  (USERPROFILE, APPDATA, LOCALAPPDATA), so a command's $env:USERPROFILE is the stand-in and the real
  profile is a folder elsewhere on the system drive, asked for before anything reads it. Every drive is taken back
  as a person takes a folder back in Settings, so nothing outside the stand-in's folders is open to the app's
  tools: a place elsewhere is asked for, and the script answers.

    env = {**os.environ, **scratchhome.make(home, key="stub", LLM_BASE_URL=url, LLM_MODEL="stub")}
    python tools/scratchhome.py check <home>      what a run left behind: .env, keys in files or the store, folders
"""
from __future__ import annotations

import json
import os
import shutil
import string
import sys
from pathlib import Path
from typing import ClassVar

from keyring.backend import KeyringBackend

HERE = Path(__file__).resolve().parent
FOLDERS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
DEFAULTS = {"UPDATE_CHECK_ENABLED": "false", "ROAM_ENABLED": "false"}
# The profile's variables, each with its folder in the stand-in computer.
PROFILE = {"USERPROFILE": "", "APPDATA": "AppData/Roaming", "LOCALAPPDATA": "AppData/Local"}


class Keys(KeyringBackend):
    """The app's credential store for a run: a key from the environment, one the app saves held in memory."""
    priority = 1
    held: ClassVar[dict] = {}

    def get_password(self, service, username):
        return self.held.get((service, username), os.environ.get(username))

    def set_password(self, service, username, password):
        self.held[(service, username)] = password

    def delete_password(self, service, username):
        self.held[(service, username)] = None


def keys(path="") -> dict:
    """LLM_API_KEY and LLM_BASE_URL from a file of KEY=value lines, or from this process's environment when no file
    is named; never printed."""
    from dotenv import dotenv_values
    values = dotenv_values(path) if path else os.environ
    return {name: values[name].strip() for name in ("LLM_API_KEY", "LLM_BASE_URL")}


def store() -> dict:
    """The variables that make `Keys` the credential store of an app started with them."""
    path = [*(p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and p != str(HERE)), str(HERE)]
    return {"PYTHON_KEYRING_BACKEND": "scratchhome.Keys", "PYTHONPATH": os.pathsep.join(path)}


def pc_of(home) -> Path:
    return Path(f"{Path(home).resolve()}-pc")


def make(home, *, key: str = "", pc=None, **settings) -> dict:
    """The scratch `home` laid out, with `settings` in its settings.json, and the variables its app's environment
    needs: the key, the credential store, the stand-in folders and `settings` again (the environment wins over the
    file, so a value the caller's shell holds does not override them). This process's store is `Keys` from here on."""
    import keyring

    from mibo import settingsfile
    from mibo.shell import grants
    home = Path(home).resolve()
    pc = Path(pc).resolve() if pc else pc_of(home)
    for name in FOLDERS:
        (pc / name).mkdir(parents=True, exist_ok=True)
    keyring.set_keyring(Keys())
    settingsfile.write(home, {**DEFAULTS, **settings})
    # A fresh home grants the person's own folders to read: this one the stand-in computer's.
    shell = home / "runtime" / "desktop" / grants.SETTINGS_FILE
    if not shell.exists():
        own = [str(pc / name) for name in FOLDERS]
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
        shell.parent.mkdir(parents=True, exist_ok=True)
        shell.write_text(json.dumps({"folders": own, "read_only": own, "removed": drives}), encoding="utf-8")
    from mibo import shortcut
    for part in PROFILE.values():
        (pc / part).mkdir(parents=True, exist_ok=True)
    env = {"AGENT_HOME": str(home), **store(), **{name: str(pc / part) for name, part in PROFILE.items()},
           "HOMEDRIVE": pc.drive, "HOMEPATH": str(pc)[len(pc.drive):],
           grants.DIRS_ENV: os.pathsep.join(str(pc / name.title()) for name in grants.DIRS),
           shortcut.DIRS_ENV: os.pathsep.join(str(pc / kind) for kind in shortcut.SPECIAL.values()),
           **{name: str(value) for name, value in settings.items()}}
    if key:
        env["LLM_API_KEY"] = key
    return env


def clear(home) -> None:
    """The home and its stand-in computer deleted."""
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(pc_of(home), ignore_errors=True)


def left(home) -> dict:
    """What a run left in and about `home`, read with this computer's own credential store."""
    from mibo import secretstore, settingsfile
    from mibo.shell.grants import Grants
    home = Path(home).resolve()
    try:
        saved = json.loads(settingsfile.path(home).read_text(encoding="utf-8"))
    except FileNotFoundError:
        saved = {}
    return {"env_file": (home / settingsfile.OLD).exists(),
            "keys_in_settings": sorted(name for name in saved if settingsfile.SECRET.search(name)),
            "credentials_file": (home / secretstore.FILE).exists(),
            "store": [name for name in settingsfile.KEYS if secretstore.get(home, name)],
            "store_mibo_entries": store_entries(),
            "folders": Grants(home / "runtime" / "desktop", home).folders()}


def store_entries() -> int | None:
    """Entries of any Mibo home in this computer's credential store (Windows'; None elsewhere)."""
    if sys.platform != "win32":
        return None
    from win32ctypes.pywin32 import win32cred
    return sum("Mibo/" in row["TargetName"] for row in win32cred.CredEnumerate(None, 0))


if __name__ == "__main__":
    if sys.argv[1:2] != ["check"] or len(sys.argv) != 3:
        raise SystemExit("python tools/scratchhome.py check <home>")
    sys.path.insert(0, str(HERE.parent))
    print(json.dumps(left(sys.argv[2]), ensure_ascii=False))
