"""Asks a running app to look something up, as the chat's "+ 外出浏览" does, and times what follows: the
answer the menu shows, when the walk leaves and comes back, and the line the main chat gets about it.

    python tools/walknow.py --home <home> --words 水豚 [--state back|limit] [--wait 600] [--out run.json]

The app must be running on that home (runtime/desktop/welcome.json). --state sets the walk record first:
"back" as if a walk ended ten minutes ago (the next walk of its own is hours away), "limit" as if today's
walks are all used. Each line printed is one JSON object; nothing of the home's .env is read.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--words", required=True)
    parser.add_argument("--state", choices=("", "back", "limit"), default="")
    parser.add_argument("--walks-a-day", type=int, default=3)
    parser.add_argument("--wait", type=float, default=600)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    home = args.home.resolve()
    address = urlsplit(json.loads((home / "runtime" / "desktop" / "welcome.json").read_text(encoding="utf-8"))["url"])
    token = address.fragment.partition("token=")[2]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(f"{address.scheme}://{address.netloc}/api/{path}",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         method="POST" if body is not None else "GET",
                                         headers={"Content-Type": "application/json",
                                                  "x-personagent-setup-token": token})
        with opener.open(request, timeout=60) as answer:
            return json.loads(answer.read().decode())

    if args.state:
        # The walk record as the library keeps it (library.Outing).
        now = int(time.time())
        path = home / "runtime" / "library" / "outing.json"
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        saved.update(state="home", site="", last_end=now - 600, day=time.strftime("%Y-%m-%d", time.localtime(now)),
                     today=1 if args.state == "back" else args.walks_a_day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    seq = max((m.get("seq", 0) for m in call("chat/history").get("messages", [])), default=0)
    started = time.time()
    answer = call("compose/wonder", {"words": args.words})
    row = {"words": args.words, "state": args.state or "fresh", "answer": answer, "out_after_s": None,
           "back_after_s": None, "report_after_s": None, "report": "", "cards": 0}
    print(json.dumps({"asked": answer}, ensure_ascii=False), flush=True)
    while time.time() - started < args.wait:
        time.sleep(2)
        state = (call("home").get("now") or {}).get("state", "")
        took = round(time.time() - started, 1)
        if state == "out" and row["out_after_s"] is None:
            row["out_after_s"] = took
            print(json.dumps({"out": took}), flush=True)
        if state != "out" and row["out_after_s"] is not None and row["back_after_s"] is None:
            row["back_after_s"] = took
            print(json.dumps({"back": took}), flush=True)
        # The lookup's own line (a remark naming the words) and the cards after it; a find the share step
        # brings meanwhile is not it.
        new = [m for m in call("chat/history").get("messages", []) if m.get("seq", 0) > seq]
        line = next((n for n, m in enumerate(new) if m.get("remark") and answer["words"] in m.get("text", "")), None)
        if line is not None:
            row["report_after_s"] = took
            row["report"] = new[line]["text"]
            row["cards"] = sum(1 for m in new[line + 1:] if m.get("card"))
            print(json.dumps({"report": row["report"], "cards": row["cards"], "after": took}, ensure_ascii=False),
                  flush=True)
            break
    print(json.dumps(row, ensure_ascii=False), flush=True)
    if args.out:
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
