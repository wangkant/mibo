"""Stand-in sites on 127.0.0.1: tools/opsite (the operating benchmark's pages, its /api/state, /__check?task=,
/__reset and POST log) and tests/roam_standin.py's self-describing pages, walls, paywall, download, script-drawn
list, search and redirects, served together by one server, plus pages a test writes itself. Every request is
logged with its method and, for a POST, its body. A second Site on another port serves cross-site and frame
cases; roam_standin.Recorder stands for an internal address under the name localhost.

The app's fetches refuse loopback, as they must. `reachable(monkeypatch, *sites)` lets these sites' own
addresses through and nothing else, so every other internal address is still refused."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import roam_standin
from mibo import ingestion

OPSITE = Path(__file__).resolve().parents[2] / "tools" / "opsite"


def _opsite():
    """tools/opsite/serve.py as a module, loaded once; its log file is set per site."""
    if "opsite_serve" not in sys.modules:
        spec = importlib.util.spec_from_file_location("opsite_serve", OPSITE / "serve.py")
        module = importlib.util.module_from_spec(spec)
        argv, sys.argv = sys.argv, [str(OPSITE / "serve.py")]
        try:
            spec.loader.exec_module(module)
        finally:
            sys.argv = argv
        sys.modules["opsite_serve"] = module
    return sys.modules["opsite_serve"]


class Site(roam_standin.Site):
    """`url`, `log` (["GET /og", "POST /api/send {...}"]), `state()` (opsite's; GET /__check?task=T01 judges a
    task on it), `put(path, html)` to serve a page of the test's own, and `reset()` between tests."""

    def __init__(self, folder: Path) -> None:
        self.serve = _opsite()
        self.serve.LOG = folder / "opsite.log"
        self.log: list[str] = []
        self.written: dict[str, str] = {}
        super().__init__()

    def reset(self) -> None:
        self.log.clear()
        self.written.clear()
        self.loads.clear()
        self.serve.STATE = self.serve.fresh()

    def state(self) -> dict:
        return json.loads(json.dumps(self.serve.STATE))

    def put(self, path: str, html: str) -> str:
        """Serve `html` at `path`; its full address."""
        self.written[path] = html
        return self.url + path

    def _handler(self):
        site = self

        class Handler(site.serve.Handler):
            def log_message(self, format, *args) -> None:
                if self.command == "GET":
                    site.log.append(f"GET {self.path}")

            def do_GET(self) -> None:
                url = urlsplit(self.path)
                if url.path in site.written:
                    site.loads.append(url.path)
                    return self._send(200, "text/html; charset=utf-8", site.written[url.path].encode("utf-8"))
                if url.path == "/cover.png":
                    site.loads.append(url.path)
                    return self._send(200, "image/png", site.cover)
                if url.path == "/api/hot":
                    rows = [{"id": ident, "title": title} for ident, title in site.videos.items()]
                    return self._send(200, "application/json", json.dumps({"rows": rows}).encode())
                status, kind, body, headers = site.page(url.path, parse_qs(url.query))
                if status != 404:
                    site.loads.append(url.path)
                    return self._send(status, kind, body.encode("utf-8"), headers)
                super().do_GET()

            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                site.log.append(f"POST {self.path} {raw.decode('utf-8', 'replace')}".rstrip())
                # opsite reads the body again.
                self.rfile = io.BytesIO(raw)
                super().do_POST()

            def _send(self, status: int, kind: str, body: bytes, headers: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

        return Handler


def reachable(monkeypatch, *sites: Site) -> None:
    """The app's fetches may reach these sites (their exact host and port); every other internal address is
    still refused by the app's own check."""
    real = ingestion._resolve_public_target
    allowed = {urlsplit(site.url).netloc for site in sites}

    async def resolve(url: str):
        parts = urlsplit(url)
        if parts.netloc in allowed:
            return parts.hostname, "127.0.0.1", parts.port
        return await real(url)

    monkeypatch.setattr(ingestion, "_resolve_public_target", resolve)
