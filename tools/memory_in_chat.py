"""Measure memory where it acts in the chat, and the 无痕对话, on a running home, through the page's own API, its
files and the page itself (headless Edge).

    python tools/memory_in_chat.py <home> <out folder> [<requests.jsonl of a recording stand-in model>]

The home must be fresh and answer with a stand-in model whose reply names a thing <about_them> lists. The script
adds one item in Settings › 记忆, asks for a drink in a new chat and counts the memories shown under the reply; says
two plain lines there and waits up to 7 minutes for the background fold, then counts the 已记住 line in that chat.
It asks for a 无痕对话 (POST /api/chats {private: true}), talks there with a word found nowhere else, says a 记住
there, and then reads every file of the home for that word: the chat record, recent.json, person.json and
profile.json among them. With the stand-in's request log it also counts the private chat's prompts that carried
<about_them> or <past_chats>. Pictures of the chat at 400, 900 and 1440 pixels go to the out folder, with one JSON
object of the numbers, which it also prints.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

home, out = Path(sys.argv[1]), Path(sys.argv[2])
requests_log = Path(sys.argv[3]) if len(sys.argv) > 3 else None
out.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")
url = json.loads((home / "runtime/desktop/welcome.json").read_text(encoding="utf-8"))["url"]
address = urlsplit(url)
token = address.fragment.partition("token=")[2]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
WORD = "Kestrel42"


def call(path, body=None):
    req = urllib.request.Request(f"{address.scheme}://{address.netloc}/api/{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", "x-mibo-setup-token": token})
    try:
        with opener.open(req, timeout=240) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code}


def history(chat):
    return call(f"chat/history?chat={chat}").get("messages", [])


result = {}
call("person/add", {"text": "我乳糖不耐受"})
plain = call("chats", {})["id"]
call("chat", {"text": "晚上想喝点东西，推荐一杯吧", "chat": plain})
reply = next((m for m in reversed(history(plain)) if m.get("role") == "assistant"), {})
result["reply"] = reply.get("text", "")
result["memories_shown_under_reply"] = len((reply.get("memory") or {}).get("used") or [])
for line in ("我最近在学大提琴", "我每周六上午去上课"):
    call("chat", {"text": line, "chat": plain})

private = call("chats", {"private": True})
result["private_chat_marked"] = bool(private.get("private"))
for line in (f"我最近在学尤克里里，琴叫{WORD}", "推荐一杯喝的吧", f"记住我喜欢{WORD}牌的琴弦"):
    call("chat", {"text": line, "chat": private["id"]})
said = [m.get("text", "") for m in history(private["id"]) if m.get("role") == "assistant"]
result["private_replies"] = said

# The fold runs after 5 minutes of quiet; the memory loop looks each minute.
deadline = time.time() + 7 * 60
while time.time() < deadline:
    if any("大提琴" in f["text"] for f in call("person").get("facts", [])):
        break
    time.sleep(15)
facts = [f["text"] for f in call("person").get("facts", [])]
result["kept_after_fold"] = facts
lines = [m for m in history(plain) if m.get("role") == "memory"]
result["saved_lines_in_chat"] = len(lines)
result["saved_items"] = [s.get("text") for m in lines for s in m.get("saved") or []]
time.sleep(10)
found = []
for path in home.rglob("*"):
    if path.is_file() and path.stat().st_size < 20_000_000:
        try:
            if WORD in path.read_text(encoding="utf-8", errors="ignore"):
                found.append(str(path.relative_to(home)).replace("\\", "/"))
        except OSError:
            continue
result["private_word_in_files"] = sorted(found)
if requests_log and requests_log.is_file():
    rows = [json.loads(line) for line in requests_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    mine = [r for r in rows if not r["fold"] and WORD in r["text"]]
    result["private_prompts"] = len(mine)
    result["private_prompts_with_memory"] = sum(1 for r in mine if r["about_them"] or r["past_chats"])

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if sync_playwright:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        for width in (400, 900, 1440):
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(url)
            page.wait_for_selector("#side-new", timeout=60000)
            time.sleep(2.5)
            for chat, name in ((plain, "plain"), (private["id"], "private")):
                page.evaluate(f"document.querySelector('[data-id=\"{chat}\"] .side-chat-open')?.click()")
                time.sleep(2)
                page.screenshot(path=str(out / f"{name}-{width}.png"))
                if width == 900:
                    result[f"dom_{name}"] = page.evaluate(
                        "({fold: document.querySelectorAll('#chat-view .act-mem').length,"
                        " saved: document.querySelectorAll('#chat-view .act-saved').length,"
                        " mark: document.querySelectorAll('#chat-view .chat-private').length})")
            page.close()
        browser.close()
(out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=1))
