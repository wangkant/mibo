"""A stand-in profile for the guards (shell/guards.py): folders and files where the real ones would be, under the test's
own folder, and a key under HKCU\\Software in place of HKCU. Nothing real is guarded: MIBO_GUARD_PLACES and
MIBO_GUARD_KEYS point the guards here, and the key is taken away again."""
from __future__ import annotations

import contextlib
import os
import subprocess
import uuid
from pathlib import Path

STARTUP = r"profile\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
CHROME = r"profile\AppData\Local\Google\Chrome\User Data"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
SECRET, KEY = "cookie-of-the-person", "PRIVATE KEY of the person"


def lay_out(root: Path, files: int = 60, modern: bool = True) -> dict:
    """The stand-in, with a protected file and one with an entry of its own in the browser profile. `modern`: every
    list marked auto-inherited, as in a real profile (the scratch drive's are not)."""
    profile = root / "profile"
    chrome = root / CHROME / "Default"
    for i in range(files):
        folder = chrome / f"d{i // 50}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"f{i}.txt").write_text(SECRET, encoding="utf-8")
    (profile / ".ssh").mkdir(parents=True)
    (profile / ".ssh" / "id_ed25519").write_text(KEY, encoding="utf-8")
    (profile / ".ssh" / "config").write_text("Host example.invalid\n  User git\n", encoding="utf-8")
    (profile / ".gitconfig").write_text("[user]\n\tname = Stand In\n\temail = stand@in.invalid\n", encoding="utf-8")
    (profile / ".bashrc").write_text("echo hi\n", encoding="utf-8")
    (root / STARTUP).mkdir(parents=True)
    for name in ("documents", "python", "package", "home"):
        (root / name).mkdir()
    (root / "home" / "skills").mkdir()
    if modern:
        subprocess.run(["icacls", str(root), "/reset", "/T", "/C", "/Q"], check=True, capture_output=True)
    protected, own = chrome / "protected.txt", chrome / "own.txt"
    protected.write_text(SECRET, encoding="utf-8")
    own.write_text(SECRET, encoding="utf-8")
    subprocess.run(["icacls", str(protected), "/inheritance:d", "/Q"], check=True, capture_output=True)
    subprocess.run(["icacls", str(own), "/grant", f"{os.environ['USERNAME']}:(R)", "/Q"], check=True,
                   capture_output=True)
    return {"profile": profile, "chrome": chrome, "protected": protected, "own": own, "home": root / "home"}


@contextlib.contextmanager
def keys(monkeypatch, root: Path):
    """MIBO_GUARD_PLACES on `root` and a stand-in key for HKCU, with its Run key; the key is taken away after."""
    import winreg
    stand_in = rf"Software\mibo-test-{uuid.uuid4().hex[:12]}"
    winreg.CloseKey(winreg.CreateKey(winreg.HKEY_CURRENT_USER, stand_in + "\\" + RUN))
    monkeypatch.setenv("MIBO_GUARD_PLACES", str(root))
    monkeypatch.setenv("MIBO_GUARD_KEYS", stand_in)
    try:
        yield stand_in
    finally:
        _delete_tree(winreg.HKEY_CURRENT_USER, stand_in)


def _delete_tree(hive, path: str) -> None:
    import winreg
    with contextlib.suppress(OSError):
        with winreg.OpenKey(hive, path) as key:
            names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        for name in names:
            _delete_tree(hive, path + "\\" + name)
        winreg.DeleteKey(hive, path)


def descriptors(root: Path, stand_in: str | None = None) -> dict:
    """Every object's owner, group and entry list as stored, under `root` and the stand-in key."""
    import winreg

    from mibo.shell import guards
    seen = {}
    for folder, _, names in os.walk(root):
        for path in [folder, *(os.path.join(folder, n) for n in names)]:
            seen[path] = guards.sddl(path, "file", 0x7)
    if stand_in:
        stack = [stand_in]
        while stack:
            sub = stack.pop()
            seen["HKCU\\" + sub] = guards.sddl("HKCU\\" + sub, "key", 0x7)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
                stack += [sub + "\\" + winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    return seen
