"""Node.js and uv for the MCP servers people start with npx or uvx, fetched on the person's press into the home.

As Cherry Studio does it: the installer carries neither. A press on a server's row in Settings fetches the vendor's
own release archive for this computer (nodejs.org; astral-sh/uv's GitHub releases) through the guarded fetch,
checks it against the sha256 the vendor published for that release (written below), and unpacks it under
home/runtime/bin/<name>. Local servers start with those folders first on PATH, and what the runtimes fetch in turn
(npm packages, uv's cache and the Python it may fetch for uvx) is kept beside them, so nothing lands elsewhere on
the computer and removing the home removes all of it.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import platform
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

# name -> what the page calls it, the release, and per (system, machine) its archive, sha256 and size in bytes.
RELEASES = {
    "node": {"title": "Node.js", "version": "26.13.1", "source": "nodejs.org", "builds": {
        ("windows", "x64"): ("https://nodejs.org/dist/v26.13.1/node-v26.13.1-win-x64.zip",
                             "e2edda75bfb089654705cf65a13b58933bfd5f57148e8ebda916f58a2474f1f7", 41166246),
        ("windows", "arm64"): ("https://nodejs.org/dist/v26.13.1/node-v26.13.1-win-arm64.zip",
                               "181ebe431b90787113a9e4fc80d38ce86d37888a353a0386de44d2872e48cb97", 37036542),
        ("darwin", "arm64"): ("https://nodejs.org/dist/v26.13.1/node-v26.13.1-darwin-arm64.tar.xz",
                              "af6202f5370a3a5209e85dc543758dfd9f44c8726626a236730cd603a67a8559", 30638176),
        ("darwin", "x64"): ("https://nodejs.org/dist/v26.13.1/node-v26.13.1-darwin-x64.tar.xz",
                            "2693310b2820f9350d29524f21344e1c623875bab773457d55b2aceb9670716f", 32743416),
        ("linux", "x64"): ("https://nodejs.org/dist/v26.13.1/node-v26.13.1-linux-x64.tar.xz",
                           "5c063e46bab0fbc1c17cc445d7ff129cbdcd0471be6ed83b6ab864f8143bc864", 34093052),
        ("linux", "arm64"): ("https://nodejs.org/dist/v26.13.1/node-v26.13.1-linux-arm64.tar.xz",
                             "89e1853138db51e8b82d3e98ba9c0d3f2956a28e5e55ea1b7e12d25aae92d5dd", 33053848),
    }},
    "uv": {"title": "uv", "version": "0.13.9", "source": "github.com/astral-sh/uv", "builds": {
        ("windows", "x64"): ("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-pc-windows-msvc.zip",
                             "edd61f7f5728a56cc62455386661860bdfc7bab65872f39b0c25bdcc1d8e1beb", 15567875),
        ("windows", "arm64"): ("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-aarch64-pc-windows-msvc.zip",
                               "72eed595983a4d7d22d79f21065b0f4479cc7e5c7a89104bb410c8f47559a878", 15747415),
        ("darwin", "arm64"): ("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-aarch64-apple-darwin.tar.gz",
                              "5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca", 14554974),
        ("darwin", "x64"): ("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-apple-darwin.tar.gz",
                            "617a3211261b0fc739562f0071aa34e9739797c510208ede8e2977c30903d041", 17362924),
        ("linux", "x64"): ("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-unknown-linux-gnu.tar.gz",
                           "a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5", 17068176),
        ("linux", "arm64"): ("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-aarch64-unknown-linux-gnu.tar.gz",
                             "0797542018e541a9288855df555c8077eed06f7a47d206362030480e8ecc9f3d", 16120245),
    }},
}
# The commands that need each runtime.
COMMANDS = {"npx": "node", "npm": "node", "node": "node", "uvx": "uv", "uv": "uv"}
# The program whose presence says a runtime is unpacked.
_MAIN = {"node": "node", "uv": "uv"}


def _build(name: str):
    system = {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    machine = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("amd64", "x86_64") else machine
    return RELEASES[name]["builds"].get((system, machine))


def folder(home: Path, name: str) -> Path:
    return Path(home) / "runtime" / "bin" / name


def _path_dir(home: Path, name: str) -> Path:
    """The folder of a runtime that goes on PATH: Node's own programs are in bin/ outside Windows."""
    base = folder(home, name)
    return base / "bin" if name == "node" and os.name != "nt" else base


def ready(home: Path, name: str) -> bool:
    return bool(shutil.which(_MAIN[name], path=str(_path_dir(home, name))))


def needed(command: str) -> str:
    """The runtime a bare command such as npx or uvx comes with, or ""."""
    path = Path(command)
    if path.parent.name:
        return ""
    return COMMANDS.get(path.stem.lower() if path.suffix.lower() in (".cmd", ".exe", "") else "", "")


def offer(name: str) -> dict | None:
    """What the page says before a download: the release, its size and where it comes from; None when there is
    no build for this computer."""
    build = _build(name)
    if build is None:
        return None
    release = RELEASES[name]
    return {"title": release["title"], "version": release["version"], "source": release["source"],
            "size": build[2]}


def env(home: Path, own: dict | None) -> dict:
    """A local server's own `env` with the runtimes Mibo fetched first on PATH and their downloads kept in the
    home; unchanged when there are none."""
    out = dict(own or {})
    have = [name for name in RELEASES if ready(home, name)]
    if not have:
        return out
    out["PATH"] = os.pathsep.join([str(_path_dir(home, name)) for name in have] + [out.get("PATH") or os.environ["PATH"]])
    cache = Path(home) / "runtime" / "cache"
    if "uv" in have:
        out.setdefault("UV_CACHE_DIR", str(cache / "uv"))
        out.setdefault("UV_TOOL_DIR", str(cache / "uv-tools"))
        out.setdefault("UV_PYTHON_INSTALL_DIR", str(cache / "python"))
    if "node" in have:
        out.setdefault("npm_config_cache", str(cache / "npm"))
    return out


def _unpack(data: bytes, url: str, into: Path) -> None:
    """The archive into `into`, without its one top folder when it has one."""
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(into)
    else:
        # The archive is the one whose sha256 is written above, so its own paths are taken as they are.
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(into)
    inside = list(into.iterdir())
    if len(inside) == 1 and inside[0].is_dir():
        top = inside[0]
        for item in list(top.iterdir()):
            item.rename(into / item.name)
        top.rmdir()


async def install(home: Path, name: str) -> None:
    """Fetches, checks and unpacks one runtime; ValueError with the page's code when it could not."""
    from .ingestion import safe_fetch_url
    url, sha256, size = _build(name)
    got = await safe_fetch_url(url, timeout=60, max_wire_bytes=size + 1024, max_decoded_bytes=size + 1024,
                               headers={"User-Agent": "Mibo", "Accept-Encoding": "identity"}, max_redirects=5)
    if got is None:
        raise ValueError("runtime_fetch_failed")
    if hashlib.sha256(got.content).hexdigest() != sha256:
        raise ValueError("runtime_hash_mismatch")
    target = folder(home, name)
    part = target.with_name(f".{name}-part")

    def write() -> None:
        shutil.rmtree(part, ignore_errors=True)
        part.mkdir(parents=True)
        _unpack(got.content, url, part)
        shutil.rmtree(target, ignore_errors=True)
        part.rename(target)

    try:
        await asyncio.to_thread(write)
    except OSError:
        raise ValueError("runtime_write_failed") from None
