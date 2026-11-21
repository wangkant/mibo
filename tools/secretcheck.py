"""Secrets on every route: whether an ID number, a card number, a password, a 'don't keep this' line and key file
names stay out of everything the app keeps or hands its model after the turn that said them, before and after a
restart.

    python tools/secretcheck.py <new scratch home> --port 59830 --model-port 59832 [--out <folder>]

It makes the home (with a stand-in model of its own on --model-port), a folder beside it granted to commands that
holds .env, id_rsa, a note and backup.bin (1.5 MB of binary), and a stand-in Desktop beside it (USER_DESKTOP_DIR).
It starts the app without a window and, in one chat, says an ID number, a card number, a password and a '别记这个'
line; the stand-in's reply repeats any number it was given, and in the card's turn it first searches the past chats
for the number (the worst case: a step that carries it). In a new chat it asks for the earlier chats
(search_past_chats), and on Windows runs Get-ChildItem in the granted folder (use_computer) and searches it for
'backup.bin' (search_files). Then it closes the app, starts it again and asks for the earlier chats once more.

Counted, from every file of the home and from the stand-in's request log (<out>/requests.jsonl, what the model was
sent): the files holding a number, the password or the 'don't keep this' words, which kept files hold the masked
forms, the model requests after the turn that said them which still carry one, the recall results carrying one, the
requests naming '.env' or 'id_rsa', and whether search_files named backup.bin. The command and file checks run on
Windows only (commands run in PowerShell); the rest runs anywhere. Free: no real model is called. No window opens.
The last lines say what leaked, and the exit code is 1 when anything did. The home, the folder and the Desktop are
left for a look; delete them after.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ID = "110101199003071233"  # a test ID number with a right check digit
CARD = "4111 1111 1111 1111"  # a test card number that passes Luhn
PASSWORD = "Qx7mibo2291"  # a stand-in password
NUMBERS = (ID, CARD.replace(" ", ""), CARD, PASSWORD)
MASKED = ("11****33", "41****11")
UNSAID = "特别怕狗"
SAID = (f"顺便说下，我身份证号是{ID}，下次订酒店你提醒我一下",  # copy: voice
        f"我的卡号是 {CARD}，月底还款日你记着点",  # copy: voice
        f"我邮箱的密码是 {PASSWORD}，周末要用",  # copy: voice
        f"别记这个啊：其实我{UNSAID}，小时候被咬过")  # copy: voice
RECALL = "你翻一下我们之前的聊天记录，我当时发过一串身份证号码和卡号，帮我找出来"  # copy: voice
COMMAND = "用 PowerShell 的 Get-ChildItem 看看授权的文件夹里有什么"  # copy: voice
SEARCH = "在授权的文件夹里找一下 backup.bin"  # copy: voice
DIGITS = re.compile(r"\d(?:[ -]?\d){12,18}")


class Stand:
    """The stand-in model: it logs every request and answers by the person's last words."""

    def __init__(self, log: Path, docs: str):
        self.log, self.docs, self.n = log, docs, 0

    def answer(self, sent: dict) -> dict:
        messages = sent.get("messages") or []
        last = messages[-1] if messages else {}
        words = last.get("content") if isinstance(last.get("content"), str) else json.dumps(last.get("content"))
        call = None
        if sent.get("tools") and last.get("role") == "user":
            if "翻一下" in words:
                call = ("search_past_chats", {"query": "身份证号 卡号", "when": ""})
            elif "Get-ChildItem" in words:
                call = ("use_computer", {"command": "Get-ChildItem -Force", "folder": self.docs})
            elif "backup.bin" in words:
                call = ("search_files", {"text": "backup.bin", "path": self.docs})
            elif "卡号" in words:
                call = ("search_past_chats", {"query": CARD, "when": ""})
        if call:
            self.n += 1
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{self.n}", "type": "function",
                "function": {"name": call[0], "arguments": json.dumps(call[1], ensure_ascii=False)}}]}
        else:
            said = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")
            said = said if isinstance(said, str) else json.dumps(said, ensure_ascii=False)
            heard = DIGITS.findall(said) + ([PASSWORD] if PASSWORD in said else [])
            reply = f"收到：{'、'.join(heard)}" if heard else "好的。"  # copy: voice
            message = {"role": "assistant", "content": json.dumps({"reasoning": "", "reply": reply, "mem": []},
                                                                  ensure_ascii=False)}
        return {"id": "stand", "object": "chat.completion", "model": "stub",
                "choices": [{"index": 0, "finish_reason": "tool_calls" if call else "stop", "message": message}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    def serve(self, port: int) -> ThreadingHTTPServer:
        stand = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, data: dict) -> None:
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send({"data": [{"id": "stub"}]})

            def do_POST(self):
                sent = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                with stand.log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(sent, ensure_ascii=False) + "\n")
                self._send(stand.answer(sent))

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


class App:
    """The app on the home, started without a window, and its page API."""

    def __init__(self, home: Path, port: int, desktop: Path):
        self.home, self.port, self.desktop = home, port, desktop
        self.process, self.base, self.token = None, "", ""
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self) -> None:
        info = self.home / "runtime" / "desktop" / "welcome.json"
        info.unlink(missing_ok=True)
        env = {**os.environ, "AGENT_HOME": str(self.home), "USER_DESKTOP_DIR": str(self.desktop),
               "PYTHONIOENCODING": "utf-8"}
        self.process = subprocess.Popen(
            [sys.executable, "-c", "import sys; from mibo import welcome; "
             f"sys.exit(welcome.main(['--no-browser', '--port', '{self.port}']))"],
            env=env, cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.DEVNULL,
            stderr=open(self.home.parent / f"{self.home.name}-app.log", "a", encoding="utf-8"))
        for _ in range(240):
            time.sleep(0.5)
            if info.exists() and json.loads(info.read_text(encoding="utf-8")).get("url"):
                url = urlsplit(json.loads(info.read_text(encoding="utf-8"))["url"])
                self.base, self.token = f"{url.scheme}://{url.netloc}", url.fragment.partition("token=")[2]
                try:
                    self.call("chats")
                    return
                except OSError:
                    continue
        raise SystemExit("the app did not start")

    def call(self, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(f"{self.base}/api/{path}",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         method="POST" if body is not None else "GET",
                                         headers={"Content-Type": "application/json", "x-mibo-setup-token": self.token})
        with self.opener.open(request, timeout=240) as answer:
            return json.loads(answer.read().decode())

    def say(self, chat: str, text: str) -> str:
        out = self.call("chat", {"text": text, "chat": chat})
        return " / ".join(m.get("text") or "" for m in out.get("messages", []) if m.get("role") == "assistant")

    def stop(self) -> None:
        """Closes the app through its own exit, or ends its process tree; none running is nothing to do."""
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self.call("exit", {})
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(30)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True)
            else:
                self.process.kill()


def holding(home: Path, needles) -> dict[str, list[str]]:
    """{needle: the home's files that hold it}, every file read as bytes."""
    found: dict[str, list[str]] = {n: [] for n in needles}
    for path in home.rglob("*"):
        if not path.is_file() or path.stat().st_size > 50_000_000:
            continue
        data = path.read_bytes()
        for needle in needles:
            if needle.encode("utf-8") in data or needle.encode("unicode_escape") in data:
                found[needle].append(str(path.relative_to(home)))
    return found


def tool_results(log: Path, start: int = 0) -> list[str]:
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()][start:]
    return [m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"), ensure_ascii=False)
            for row in rows for m in row.get("messages") or [] if m.get("role") == "tool"]


def main(argv: list[str]) -> int:
    getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    windows = sys.platform == "win32"
    parser = argparse.ArgumentParser()
    parser.add_argument("home")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model-port", type=int, required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    home = Path(args.home).resolve()
    if home.exists() and any(home.iterdir()):
        raise SystemExit(f"{home} is not empty: give a new scratch home")
    out = Path(args.out).resolve() if args.out else home.with_name(f"{home.name}-out")
    docs, desktop = home.with_name(f"{home.name}-docs"), home.with_name(f"{home.name}-desktop")
    for folder in (home / "runtime" / "desktop", out, docs, desktop):
        folder.mkdir(parents=True, exist_ok=True)
    (docs / ".env").write_text("STAND_IN_KEY=not-a-real-key\n", encoding="utf-8")
    (docs / "id_rsa").write_text("-----BEGIN STAND-IN KEY-----\n", encoding="utf-8")
    (docs / "notes.txt").write_text("预算 3000\n", encoding="utf-8")
    (docs / "backup.bin").write_bytes(b"\x00\x01\x02\xff" * (1_572_864 // 4))
    (home / "runtime" / "desktop" / "shell.json").write_text(
        json.dumps({"folders": [str(docs)], "read_only": [str(docs)]}, ensure_ascii=False), encoding="utf-8")
    (home / ".env").write_text("\n".join([
        f"LLM_BASE_URL=http://127.0.0.1:{args.model_port}/v1", "LLM_MODEL=stub", "LLM_API_KEY=stand-in",
        f"PAGE_PORT={args.port}", f"SERVER_PORT={args.port + 1}", "UPDATE_CHECK_ENABLED=false",
        "ROAM_ENABLED=false", "AGENT_LANG=zh", "PERSONA_TZ_OFFSET_HOURS=-8", "PERSONA_NAME=Mibo"]) + "\n",
        encoding="utf-8")
    log = out / "requests.jsonl"
    log.write_text("", encoding="utf-8")
    server = Stand(log, str(docs)).serve(args.model_port)
    app = App(home, args.port, desktop)
    result: dict = {}
    try:
        app.start()
        chat = app.call("chats", {})["id"]
        result["replies"] = [app.say(chat, text) for text in SAID]
        said_upto = len(log.read_text(encoding="utf-8").splitlines())
        other = app.call("chats", {})["id"]
        result["replies"] += [app.say(other, text) for text in ((RECALL, COMMAND, SEARCH) if windows else (RECALL,))]
        app.stop()
        before = holding(home, (*NUMBERS, *MASKED, UNSAID))
        app.start()
        result["replies"].append(app.say(app.call("chats", {})["id"], RECALL))
    finally:
        app.stop()
        server.shutdown()
    after = holding(home, (*NUMBERS, *MASKED, UNSAID))
    rows = log.read_text(encoding="utf-8").splitlines()
    later = rows[said_upto:]
    results = tool_results(log, said_upto)
    result.update({
        "files_with_a_secret": {"before_restart": sorted({p for n in NUMBERS for p in before[n]}),
                                "after_restart": sorted({p for n in NUMBERS for p in after[n]})},
        "files_with_the_unsaid_words": {"before_restart": before[UNSAID], "after_restart": after[UNSAID]},
        "files_with_a_masked_form": sorted({p for m in MASKED for p in after[m]}),
        "model_requests_after_the_turn": len(later),
        "of_them_with_a_secret": sum(any(n in row for n in NUMBERS) for row in later),
        "of_them_with_the_unsaid_words": sum(UNSAID in row for row in later),
        "recall_results": sum("past chats" in r for r in results),
        "recall_results_with_a_secret": sum(any(n in r for n in NUMBERS) for r in results),
        "model_requests_naming_.env": sum(".env" in row for row in rows),
        "model_requests_naming_id_rsa": sum("id_rsa" in row for row in rows),
        **({"search_files_found_backup.bin": any("backup.bin" in r and "Searched" in r and "0 files hold" not in r
                                                 for r in results)} if windows else {}),
    })
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    kept = {"chat log": "runtime/log/", "recent.json": "runtime/recent.json", "page copy": "runtime/desktop/chats/"}
    leaks = [f"{key}: {value}" for key, value in result.items()
             if key not in ("replies", "files_with_a_masked_form", "model_requests_after_the_turn", "recall_results")
             and not key.startswith("search_files") and value and value != {"before_restart": [], "after_restart": []}]
    leaks += [f"no masked form in the {name}" for name, where in kept.items()
              if not any(p.replace("\\", "/").startswith(where) for p in result["files_with_a_masked_form"])]
    leaks += [] if result["recall_results"] else ["search_past_chats never answered"]
    leaks += ["search_files did not find backup.bin"] if result.get("search_files_found_backup.bin") is False else []
    print()
    for line in leaks + ([] if windows else ["(commands and files are checked on Windows only)"]):
        print(f"  {line}")
    print(f"secretcheck: {'FAIL' if leaks else 'PASS'} ({len(leaks)} leaks)")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
