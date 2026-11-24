"""The Windows app updating itself, end to end, with real installers: for the release workflow's Windows runner.

    python tools/update_e2e.py lower <copy of the checkout>
    python tools/update_e2e.py run --old <lower setup.exe> --new dist/mibo-X.Y.Z-setup.exe --version X.Y.Z

`lower` changes a copy of the checkout in two ways before it is built: its version becomes 0.0.0, and its release
source (mibo/updates.py API, DOWNLOAD and _reach) becomes a stand-in at http://127.0.0.1:PORT. Nothing else in it
differs from the release. `run` installs that build into a scratch folder, serves a stand-in release offering the
new setup.exe with its real size and SHA-256 (the file reached through a redirect, as GitHub's is), starts the
installed app, presses its update as the page does (POST /api/runtime/check, then /api/runtime/update), and waits
for the installer to replace it and open it again: the copy in the same folder must then say the new version, on
the same home, with the start after the update reporting it. The rules on the download itself (https, GitHub's
hosts, public addresses) are held by tests/floors/boundary/test_update_supply.py, not here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from package_smoke import _env

PORT = 47811
STANDIN = f"http://127.0.0.1:{PORT}"


def _swap(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def lower(copy: Path) -> None:
    version = re.search(r'^version = "(.+)"$', (copy / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    _swap(copy / "pyproject.toml", f'version = "{version}"', 'version = "0.0.0"')
    _swap(copy / "mibo" / "__init__.py", f'__version__ = "{version}"', '__version__ = "0.0.0"')
    updates = copy / "mibo" / "updates.py"
    _swap(updates, 'API = "https://api.github.com/repos/wangkant/mibo"', f'API = "{STANDIN}/repos/wangkant/mibo"')
    _swap(updates, 'DOWNLOAD = "https://github.com/wangkant/mibo/releases/download"',
          f'DOWNLOAD = "{STANDIN}/wangkant/mibo/releases/download"')
    _swap(updates, "    from . import ingestion\n    parts = urlsplit(url)\n",
          f'    if url.startswith("{STANDIN}/"):\n        return "127.0.0.1", "127.0.0.1", {PORT}\n'
          "    from . import ingestion\n    parts = urlsplit(url)\n")
    # The stand-in cannot sign as the project does, so this copy holds its release to the checksum.
    text = updates.read_text(encoding="utf-8")
    updates.write_text(re.sub(r'^SIGNING_KEY = ".*"$', 'SIGNING_KEY = ""', text, count=1, flags=re.M), encoding="utf-8")
    print(f"lowered {version} -> 0.0.0, releases from {STANDIN}")


def _release(setup: Path, version: str) -> ThreadingHTTPServer:
    """The stand-in GitHub: the listing, SHA256SUMS.txt, and the installer behind a redirect."""
    name = f"mibo-{version}-setup.exe"
    data = setup.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    sums = f"{digest}  {name}\n".encode()
    listing = json.dumps({"tag_name": f"v{version}", "draft": False, "prerelease": False, "assets": [
        {"name": name, "size": len(data), "digest": f"sha256:{digest}"},
        {"name": "SHA256SUMS.txt", "size": len(sums)}]}).encode()
    files = {"/repos/wangkant/mibo/releases/latest": listing,
             f"/repos/wangkant/mibo/releases/tags/v{version}": listing,
             f"/wangkant/mibo/releases/download/v{version}/SHA256SUMS.txt": sums,
             "/release-asset/setup": data}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args) -> None:
            print("  stand-in:", format % args, flush=True)

        def do_GET(self) -> None:
            if self.path == f"/wangkant/mibo/releases/download/v{version}/{name}":
                self.send_response(302)
                self.send_header("Location", f"{STANDIN}/release-asset/setup")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _page(url: str):
    parsed = urlsplit(url)
    base, token = f"{parsed.scheme}://{parsed.netloc}", parse_qs(parsed.fragment)["token"][0]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "X-Mibo-Setup-Token": token})
        with opener.open(request, timeout=60) as answer:
            return json.loads(answer.read())
    return call


def _said(program: Path) -> str:
    return subprocess.run([str(program), "--version"], capture_output=True, text=True, timeout=120,
                          env=_env()).stdout.strip()


def _until(what: str, check, within: float):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            found = check()
        except OSError:
            found = None
        if found:
            return found
        time.sleep(1)
    raise SystemExit(f"FAILED: {what} within {within:.0f} s")


def run(old: Path, new: Path, version: str) -> int:
    work = Path(tempfile.mkdtemp(prefix="mibo-update-"))
    folder, home = work / "app", work / "home"
    program = folder / "mibo.exe"
    env = {**_env(), "AGENT_HOME": str(home)}
    installed = subprocess.run([str(old), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={folder}",
                                f"/LOG={work / 'old-setup.log'}"], env=env, timeout=900)
    if installed.returncode or _said(program) != "mibo 0.0.0" or not (folder / "unins000.exe").is_file():
        raise SystemExit("FAILED: the lower build did not install as 0.0.0 with its uninstaller")
    server = _release(new, version)
    said = work / "old-app.log"
    with said.open("w", encoding="utf-8") as out:
        started = subprocess.Popen([str(program), "--home", str(home), "start", "--no-browser"], env=env,
                                   stdout=out, stderr=subprocess.STDOUT)
    info = home / "runtime" / "desktop" / "welcome.json"
    try:
        first = _until("the old app's page", lambda: json.loads(info.read_text(encoding="utf-8")).get("url"), 60)
        page = _page(first)
        _until("the old app answering", lambda: page("/api/runtime"), 30)
        seen = page("/api/runtime/check", {})
        if seen["how"] != "installer" or (seen["update"] or {}).get("version") != version:
            raise SystemExit(f"FAILED: the old app did not find {version} as the installer's copy: {seen}")
        job = page("/api/runtime/update", {})["job"]
        print("update started:", job, flush=True)
        job = _until("the download and its check", lambda: (lambda j: j if j["state"] in ("installing", "failed")
                                                            else None)(page("/api/runtime")["job"]), 300)
        if job["state"] != "installing":
            raise SystemExit(f"FAILED: the update stopped: {job}")
        if started.wait(timeout=60) != 0:
            raise SystemExit("FAILED: the old app did not close for the installer")
        print("old app closed; installer running", flush=True)
        again = _until("the app opened again by the installer", lambda: (lambda u: u if u and u != first else None)(
            json.loads(info.read_text(encoding="utf-8")).get("url")), 600)
        page = _page(again)
        seen = _until("the new app answering", lambda: page("/api/runtime"), 60)
        if seen["version"] != version or not (seen["updated"] or {}).get("ok"):
            raise SystemExit(f"FAILED: the app came back as {seen['version']}: {seen['updated']}")
        # The installer and its log go once the installer has ended (updates.settle).
        _until("the installer's files gone", lambda: sorted(
            path.name for path in (home / "runtime" / "updates").iterdir()) == ["state.json"], 120)
        page("/api/exit", {})
        _until("the new app closing", lambda: not info.exists(), 60)
        if _said(program) != f"mibo {version}":
            raise SystemExit("FAILED: the installed program does not say the new version")
        print(f"PASS: 0.0.0 installed -> its own update -> {version} in the same folder, opened again on the same home")
        return 0
    finally:
        if started.poll() is None:
            started.kill()
        server.shutdown()
        for log in (said, home / "runtime" / "updates" / "setup.log"):
            if log.is_file():
                print(f"--- {log.name}")
                print(log.read_text(encoding="utf-8", errors="replace")[-4000:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("lower").add_argument("copy", type=Path)
    running = steps.add_parser("run")
    running.add_argument("--old", type=Path, required=True)
    running.add_argument("--new", type=Path, required=True)
    running.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    if args.step == "lower":
        lower(args.copy)
        return 0
    return run(args.old.resolve(), args.new.resolve(), args.version)


if __name__ == "__main__":
    sys.exit(main())
