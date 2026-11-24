"""The project's GitHub releases as the app's update meets them (mibo/updates.py), served by the stand-in site:
a release's listing on api.github.com, its SHA256SUMS.txt (and a signature) and its files on github.com, each
file sent on by a redirect to GitHub's asset host. The app's own checks run whole: its https addresses, its hosts,
the public-address guard (the names answer with public addresses, harness.sites.PublicWeb) and the pinned
transport's place in it; only the bytes travel over the site on 127.0.0.1, at the same path. `hops` records every
request the app made, as (host, url); `launched` every program it started, with its command line, and nothing
starts for real."""
from __future__ import annotations

import hashlib
import json
import subprocess
import types

import httpx

from mibo import ingestion, updates

API_HOST, FILE_HOST, ASSET_HOST = "api.github.com", "github.com", "release-assets.githubusercontent.com"
# A host outside the release answers publicly too, so only the update's own rules can keep it out.
ADDRESSES = {API_HOST: "140.82.112.5", FILE_HOST: "140.82.112.3", ASSET_HOST: "185.199.108.133",
             "evil.example": "93.184.216.34"}
INSTALLER = b"MZ stand-in installer " + bytes(range(256)) * 64


class Releases:
    def __init__(self, monkeypatch, site, web) -> None:
        self.site = site
        # A build from before the project had a key, held to its checksum: a test of signatures sets its own key.
        monkeypatch.setattr(updates, "SIGNING_KEY", "")
        self.hops: list[tuple[str, str]] = []
        self.launched: list = []
        for host, address in ADDRESSES.items():
            web.name(host, address)
        releases = self

        class Forward(httpx.AsyncHTTPTransport):
            """The pinned transport's stand-in: the request goes to the site, at the address the app asked for."""

            def __init__(self, hostname: str, pinned_ip: str) -> None:
                super().__init__(trust_env=False)
                self.pinned_ip = pinned_ip

            async def handle_async_request(self, request):
                releases.hops.append((request.url.host, str(request.url)))
                port = int(site.url.rsplit(":", 1)[1])
                request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=port)
                return await super().handle_async_request(request)

        monkeypatch.setattr(ingestion, "_PinnedAsyncHTTPTransport", Forward)
        monkeypatch.setattr(updates, "subprocess", types.SimpleNamespace(
            Popen=lambda command, **named: self.launched.append(command), DEVNULL=subprocess.DEVNULL,
            CREATE_NEW_PROCESS_GROUP=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            DETACHED_PROCESS=getattr(subprocess, "DETACHED_PROCESS", 0)))
        monkeypatch.setattr(updates, "LEAVE_AFTER_S", 0)

    def publish(self, version: str, how: str = "installer", data: bytes = INSTALLER, *, sums: bytes | None = None,
                size: int | None = None, signature: bytes | None = None, served: bytes | None = None,
                redirect: str = "", tag: str = "") -> str:
        """Release `version` with `data` as this way's file: its listing, its SHA256SUMS.txt (`sums` in place of
        the true one) and, given, its signature. `size`: what the listing states; `served`: what the file's
        address sends instead of `data`; `redirect`: where github.com sends the file on to. The file's name."""
        name = updates.asset(version, how)
        sums = sums if sums is not None else f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()
        assets = [{"name": name, "size": len(data) if size is None else size},
                  {"name": updates.SUMS, "size": len(sums)}]
        base = f"/wangkant/mibo/releases/download/v{version}/"
        self.site.put(base + updates.SUMS, sums, "text/plain")
        if signature is not None:
            assets.append({"name": updates.SIGNATURE, "size": len(signature)})
            self.site.put(base + updates.SIGNATURE, signature, "application/octet-stream")
        stored = f"/github-production-release-asset/{version}/{name}"
        self.site.put(base + name, b"", "text/plain", status=302,
                      headers={"Location": redirect or f"https://{ASSET_HOST}{stored}"})
        self.site.put(stored, data if served is None else served, "application/octet-stream")
        self.site.put(f"/repos/wangkant/mibo/releases/tags/v{version}", json.dumps(
            {"tag_name": tag or f"v{version}", "draft": False, "prerelease": False, "assets": assets}),
            "application/json")
        return name

    def found(self, home, version: str) -> None:
        """The app's own last check saw `version` (updates.check's record)."""
        cache = home / "runtime" / "desktop" / "update.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked": 1, "latest": version, "failed": False}), encoding="utf-8")
