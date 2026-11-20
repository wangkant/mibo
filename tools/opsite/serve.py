"""A small local site to try Mibo's browser operating on. Nothing leaves this computer.

    python tools/opsite/serve.py 59630 requests.log

The first pages (a messenger, a search page, a profile form that asks for the current password, a page carrying
an instruction, a checkout) are the four tasks the operating was first proved on. The pages under t/ are the
benchmark (tasks.py): each behaves like a real site of its kind, and each task is checked here, on what the
site itself received, never on what the model says.

Every request is logged, one line each with the body of a POST, so a run can be checked for what was (and
was not) sent. GET /api/state shows what the site holds; POST /__reset forgets it; GET /__check?task=T01
says whether that task was done (tasks.py)."""
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import tasks  # noqa: E402

LOG = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "requests.log"
LOCK = threading.Lock()


def fresh() -> dict:
    # What the site keeps while it runs: the first pages' messages, profile, orders, and every POST and page read.
    return {"sent": [], "profile": {"nickname": "小乐", "bio": ""}, "orders": [], "deleted": False,
            "posts": [], "reads": [], "cart": {"scratcher": 1, "mug": 1},
            "bag": [{"item": "sock", "color": "", "size": ""}]}


STATE = fresh()
# Resets so far: T14's value changes with it.
ROUND = 0


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def log_message(self, format, *args):
        with LOG.open("a", encoding="utf-8") as out:
            out.write(f"{self.log_date_time_string()} {self.command} {self.path}\n")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _answer(self, body, status: int = 200) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if parts.path == "/api/state":
            return self._answer(STATE)
        if parts.path == "/__check":
            with LOCK:
                return self._answer(tasks.check(query.get("task", ""), STATE))
        if parts.path == "/api/track":
            with LOCK:
                STATE["reads"].append(self.path)
            # A slow lookup, as a busy courier's site is.
            time.sleep(5)
            return self._answer(tasks.TRACKING.get(query.get("no", "").strip().upper(), {"status": "查无此单"}))
        if parts.path.endswith(".html"):
            with LOCK:
                STATE["reads"].append(parts.path + ("?" + parts.query if parts.query else ""))
            if parts.path == "/t/t19-track.html":
                # The page itself is slow to come.
                time.sleep(3)
        return super().do_GET()

    def do_POST(self):
        global STATE, ROUND
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
        kind = self.headers.get("Content-Type", "")
        try:
            sent = json.loads(raw) if "json" in kind or raw[:1] in (b"{", b"[") else {
                k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
        except ValueError:
            sent = {"raw": raw.decode("utf-8", "replace")}
        with LOG.open("a", encoding="utf-8") as out:
            out.write(f"  body {json.dumps(sent, ensure_ascii=False)}\n")
        path = urlsplit(self.path).path
        if path == "/__reset":
            with LOCK:
                ROUND += 1
                STATE = {**fresh(), "round": ROUND}
            return self._answer({"ok": True})
        with LOCK:
            STATE["posts"].append({"path": path, "body": sent, "at": round(time.time(), 2)})
            if path == "/api/send":
                STATE["sent"].append(sent)
            elif path == "/api/profile":
                STATE["profile"].update({k: sent[k] for k in ("nickname", "bio") if k in sent})
            elif path == "/api/order":
                STATE["orders"].append(sent)
            elif path == "/api/delete":
                STATE["deleted"] = True
            elif path == "/api/cart":
                STATE["cart"][str(sent.get("item"))] = int(sent.get("qty") or 0)
                return self._answer({"ok": True, "cart": STATE["cart"]})
            elif path == "/api/bag":
                STATE["bag"].append(sent)
            elif path == "/api/beacon":
                return self._answer({"ok": True})
            elif not path.startswith("/api/"):
                return self._answer({"ok": False}, 404)
        return self._answer({"ok": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
