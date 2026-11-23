"""The places a command names: PowerShell's paths made absolute (`Paths`), wildcards matched and folders
walked as PowerShell would, and the files an unzip or a copy would replace."""
from __future__ import annotations

import contextlib
import fnmatch
import ipaddress
import os
import re
import socket
import zipfile

from . import run as running
from .psnodes import _items
from .pstables import LOOPBACK

# More items than this are not listed first: what they are is known only as the command runs.
LIST_MOST = 5000


class Paths:
    """Turns a parsed argument into absolute places, knowing the folder it runs in and the constants assigned."""

    def __init__(self, cwd: str):
        self.cwd = cwd
        self.stack: list[tuple] = []
        self.consts: dict[str, dict] = {}
        # (provider, place) after Set-Location into the registry or another provider; relative paths go there.
        self.where: tuple[str, str] | None = None

    def strings(self, el) -> list[str] | None:
        """The literal strings an argument stands for, or None when it is computed at run time."""
        if not isinstance(el, dict):
            return None
        if el.get("k") in ("s", "n"):
            return [str(el.get("v") or "")]
        if el.get("k") == "a":
            out: list[str] = []
            for item in _items(el.get("items")):
                got = self.strings(item)
                if got is None:
                    return None
                out += got
            return out
        if el.get("k") == "v" and str(el.get("v") or "").lower() in self.consts:
            return self.strings(self.consts[str(el["v"]).lower()])
        return None

    def place(self, raw: str) -> tuple[str, str]:
        """(provider, absolute path) of one path as PowerShell would take it."""
        text = raw.strip().strip('"').strip("'")
        # "Module\Provider::path", as PowerShell takes any provider by its qualified name.
        qualified = re.match(r"^(?:[\w.]+\\)?(\w+)::(.*)$", text, re.DOTALL)
        if qualified:
            kind, text = qualified.group(1).lower(), qualified.group(2)
            if kind == "registry":
                text = "registry::" + text
            elif kind != "filesystem":
                named = {"certificate": "cert", "environment": "env", "variable": "variable", "function": "function",
                         "alias": "alias", "wsman": "wsman"}.get(kind, "provider")
                return named, f"{named}:{text}".lower()
        low = text.lower()
        if self.where and not re.match(r"^(?:[a-zA-Z]:|[\\/~]|\w+::|(?:env|variable|function|alias|cert|wsman|hk\w*):)",
                                       text, re.IGNORECASE):
            # Relative to a location in another provider.
            return self.where[0], self.where[1] + "\\" + low
        if low.startswith(("registry::", "hklm:", "hkcu:", "hkcr:", "hku:", "hkcc:", "hkey_")):
            key = re.sub(r"^registry::", "", low)
            key = re.sub(r"^hkey_local_machine", "hklm", re.sub(r"^hkey_current_user", "hkcu", key))
            return "registry", key.replace(":", "").replace("/", "\\").rstrip("\\")
        provider = re.match(r"^(env|variable|function|alias|cert|wsman):", low)
        if provider:
            return provider.group(1), low
        if low.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
            return "device", text
        if low.startswith(("\\\\", "//")):
            # This computer's own drives through their admin share: the drive itself.
            share = re.match(r"^[\\/]{2}([^\\/]+)[\\/]([a-zA-Z])\$(?:[\\/](.*))?$", text)
            if share and _local_host(share.group(1)):
                return "file", os.path.normpath(share.group(2) + ":\\" + (share.group(3) or ""))
            return "unc", text
        if text.startswith("~"):
            text = os.path.join(os.environ.get("USERPROFILE", ""), text[1:].lstrip("\\/"))
        if re.match(r"^[a-zA-Z]:(?![\\/])", text):
            # "C:name" is relative to that drive's current folder: read as the drive's root, the wider case.
            text = text[:2] + "\\" + text[2:]
        return "file", os.path.normpath(os.path.join(self.cwd, text))


def _base(path: str) -> tuple[str, bool]:
    """The part of a path before its first wildcard, and whether it had one."""
    parts = re.split(r"[\\/]", path)
    for n, part in enumerate(parts):
        if _wild(part):
            base = "\\".join(parts[:n]) or path[:3]
            return (base + "\\" if re.match(r"^[a-zA-Z]:$", base) else base), True
    return path, False


def _local_host(host: str) -> bool:
    """A host name that is this computer: localhost in any spelling, a loopback address, its own name."""
    host = host.strip("[]").rstrip(".").lower()
    if host in LOOPBACK or host.endswith(".localhost") or host in ("", ".", "?", "wsl$", "wsl.localhost") or \
            host == os.environ.get("COMPUTERNAME", "").lower():
        return True
    try:
        address = ipaddress.ip_address(host)
        mapped = getattr(address, "ipv4_mapped", None)
        return address.is_loopback or address.is_unspecified or bool(mapped and mapped.is_loopback)
    except ValueError:
        pass
    try:
        # The old numeric forms a URL may use: 2130706433, 0x7f.1, 127.1.
        return socket.inet_aton(host)[0] in (0, 127)
    except OSError:
        return False


def _wild(path: str) -> bool:
    """A path with a wildcard in it."""
    return any(c in path for c in "*?[")


def _matches(pattern: str, most: int = LIST_MOST) -> list[str]:
    """The places a wildcard path matches now, as PowerShell's wildcards would (dot names included)."""
    parts = re.split(r"[\\/]", pattern)
    found = [parts[0] + "\\"]
    for part in parts[1:]:
        if not part:
            continue
        nxt = []
        for place in found:
            if not _wild(part):
                nxt.append(os.path.join(place, part))
                continue
            with contextlib.suppress(OSError):
                nxt += [e.path for e in os.scandir(place) if fnmatch.fnmatch(e.name, part)]
            if len(nxt) > most:
                return nxt
        found = nxt
    return [p for p in found if os.path.lexists(p)]


def _walk(base: str, most: int = 50000) -> list[str] | None:
    """Everything under `base`, not following links; None when there is more than `most`."""
    out, stack = [], [base]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            out.append(entry.path)
            if len(out) > most:
                return None
            if entry.is_dir(follow_symlinks=False) and not running._junction(entry.path):
                stack.append(entry.path)
    return out


def _listed(globs: list[str], children: bool, recurse: bool, keep) -> list[str] | None:
    """The items a listing hands on, as PowerShell lists them: a folder named to Get-ChildItem (`children`) gives
    what is in it, all under it with -Recurse; a pattern its matches, and with -Recurse also every item under its
    folder named like it and all a matching folder holds. Only those `keep` passes; None past LIST_MOST."""
    found: list[str] = []
    for glob in globs:
        got = _pattern_items(glob, children, recurse) if _wild(glob) else _named_items(glob, children, recurse)
        if got is None:
            return None
        found += got
    found = [p for p in dict.fromkeys(found) if keep(p)]
    return found if len(found) <= LIST_MOST else None


def _named_items(place: str, children: bool, recurse: bool) -> list[str] | None:
    """A place named outright: what the folder holds when Get-ChildItem lists it, else the place itself."""
    if not (children and os.path.isdir(place)):
        return [place] if os.path.lexists(place) else []
    try:
        return _walk(place, LIST_MOST) if recurse else [e.path for e in os.scandir(place)]
    except OSError:
        return []


def _pattern_items(glob: str, children: bool, recurse: bool) -> list[str] | None:
    """What a pattern lists: its matches, and with -Recurse every item named like it under its folder and all a
    matching folder holds."""
    got = _matches(glob)
    if not (children and recurse):
        return got
    every = _walk(_base(glob)[0], LIST_MOST)
    if every is None:
        return None
    leaf = os.path.basename(glob).lower()
    got += [p for p in every if fnmatch.fnmatchcase(os.path.basename(p).lower(), leaf)]
    for hit in [p for p in got if os.path.isdir(p) and not _is_link(p)]:
        inside = _walk(hit, LIST_MOST)
        if inside is None:
            return None
        got += inside
    return got


def _some(paths: list[str]) -> str:
    """Paths for an act's reason, the first five of a long list."""
    return ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")


def _is_link(path: str) -> bool:
    return os.path.islink(path) or (os.path.isdir(path) and running._junction(path))


def _unzip_overwrites(archive: str, dest: str) -> bool:
    """Expand-Archive -Force would replace files already in `dest`."""
    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return True
    return any(os.path.isfile(os.path.join(dest, n)) for n in names)


def _copy_overwrites(src: str, target: str) -> bool:
    """Copy-Item -Recurse of the folder `src` to `target` would replace files already there."""
    found = _walk(src)
    if found is None:
        return True
    return any(os.path.isfile(os.path.join(target, os.path.relpath(p, src))) for p in found if os.path.isfile(p))
