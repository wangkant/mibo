"""What the person's next message means after the share step brought a find into the main chat, on the real model:
each case is an exchange (a request and its answer), a find the share step brings, and their message after it. The
request is built with the app's own code (the share step, the quotes their message carries, the prompt builder),
sent once, and the reply judged blind by a second call that sees only the chat as the person saw it.

    python tools/asidecheck.py <scratch home> --keys <file> --out <results.jsonl> [--only 1,4] [--calls 44]
    python tools/asidecheck.py - --keys <file> --out <results.jsonl> --rejudge <results.jsonl>

<file> gives LLM_API_KEY and LLM_BASE_URL (tools/scratchhome.py keys), read and never printed. One call at a time; a
429 waits and tries again. The home is written to: give it a scratch folder."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# An exchange and the find brought after it: (their request, the answer), then the find.
PHONES = ("帮我比较一下 iPhone 16 和 Pixel 9 的续航和价格",  # copy: voice
          "续航：iPhone 16 视频播放约 22 小时，Pixel 9 约 24 小时；日常重度使用两者都能撑一天。\n"  # copy: voice
          "价格：iPhone 16 128GB 起售 5999 元，Pixel 9 128GB 约 799 美元（国内需代购，约 5800 元）。\n"  # copy: voice
          "总的来说续航 Pixel 9 略好，价格接近；看重系统生态选 iPhone，看重拍照和原生安卓选 Pixel。")  # copy: voice
RIDE = {"title": "一个人骑行川藏线 20 天", "site": "bilibili.com", "kind": "video",  # copy: voice
        "line": "刚看到一个骑行川藏线的纪录片，拍得挺好看的，你可能会喜欢。",  # copy: voice
        "excerpt": "从成都出发，经雅安、理塘到拉萨，记录一路的风景和路上遇到的人。"}  # copy: voice
ASYNC = ("Summarize the main differences between Python's asyncio and threading in a few points",
         "- **Concurrency model:** asyncio runs one thread with an event loop and switches at `await`; threading "
         "runs OS threads the scheduler switches at any point.\n- **Best for:** asyncio suits many network waits; "
         "threading suits blocking libraries that have no async API.\n- **Safety:** asyncio needs no locks for "
         "most shared state; threads need locks.\n- **CPU work:** neither runs Python code in parallel under the "
         "GIL; use multiprocessing for that.")
FILM = {"title": "The quiet comeback of film cameras", "site": "theverge.com", "kind": "article",
        "line": "Saw this piece on film cameras making a comeback, thought you'd like it.",
        "excerpt": "Sales of film and secondhand cameras have doubled since 2020, driven by people under 30."}

# (label, exchange or None, find, their message, whether it answers the find's card, what a right reply acts on).
CASES = [
    ("表格", PHONES, RIDE, "把上面的结果整理成表格", False, "answer"),  # copy: voice
    ("再详细", PHONES, RIDE, "上面的结果再详细一点", False, "answer"),  # copy: voice
    ("这个视频", PHONES, RIDE, "这个视频是讲什么的", False, "find"),  # copy: voice
    ("答卡片", PHONES, RIDE, "看起来不错，大概多长？", True, "find"),  # copy: voice
    ("这个不错", PHONES, RIDE, "这个不错", False, "find|ask"),  # copy: voice
    ("save file", ASYNC, FILM, "save that as a file", False, "answer"),
    ("who made it", ASYNC, FILM, "the one you just recommended, who made it", False, "find"),
    ("make shorter", ASYNC, FILM, "that result, make it shorter", False, "answer"),
    ("再来一个", None, RIDE, "再来一个", False, "find"),  # copy: voice
    ("nice one", ASYNC, FILM, "nice one", False, "find|ask"),
]

JUDGE = """You read a chat between a person and an assistant named Mibo, then Mibo's reply to the person's last
message. The chat may hold two things that message could be about:
EARLIER: Mibo's earlier answer to something the person asked for (if the chat has one).
BROUGHT: the thing Mibo brought on its own afterwards, the message with a card.
Which one does the reply act on or talk about? Its tool calls count as what it does.

Write exactly one word and nothing else:
earlier - it works on or talks about the EARLIER answer (reformats, extends, saves or discusses it)
brought - it works on or talks about the BROUGHT thing, or brings another thing like it
asks - it asks the person which one they mean, and acts on neither
other - none of these"""
# The judge's word as the table names it.
ACTED = {"earlier": "answer", "brought": "find", "asks": "ask"}


class Relay:
    """The model's endpoint, one call at a time, at most `most` calls."""

    def __init__(self, keys: dict, most: int) -> None:
        self.url = keys["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
        self.key, self.most, self.used = keys["LLM_API_KEY"], most, 0

    def ask(self, messages: list, tools: list | None = None) -> dict:
        if self.used >= self.most:
            raise SystemExit(f"stopped at {self.used} calls")
        body = {"model": "haiku", "messages": messages, **({"tools": tools} if tools else {})}
        for wait in (0, 60, 120, 240, 480):
            time.sleep(wait)
            self.used += 1
            request = urllib.request.Request(self.url, json.dumps(body).encode(), method="POST", headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(request, timeout=600) as answer:
                    return json.loads(answer.read())["choices"][0]["message"]
            except urllib.error.HTTPError as error:
                if error.code != 429:
                    raise
                print(f"  429, waiting {wait * 2 or 60}s", flush=True)
        raise SystemExit("the relay kept answering 429")


def said(message: dict) -> str:
    """A reply as the judge reads it: its words, then each call it made."""
    calls = [f"[calls {c['function']['name']} with {c['function']['arguments']}]"
             for c in message.get("tool_calls") or []]
    return "\n".join([str(message.get("content") or "").strip(), *calls]).strip()


def seen(row: tuple) -> str:
    """The chat of a case as the person saw it."""
    _, exchange, find, message, answers, _ = row
    lines = [f"Person: {exchange[0]}", f"Mibo: {exchange[1]}"] if exchange else []
    lines.append(f"Mibo: {find['line']}\n  [card: {find['kind']} · {find['title']} · {find['site']} — "
                 f"{find['excerpt']}]")
    lines.append(f"Person: (replying to the card «{find['title']}») {message}" if answers else f"Person: {message}")
    return "\n".join(lines)


def judge(relay: Relay, row: tuple, reply: str) -> tuple[str, str]:
    """What the reply acts on, by a call that sees only the chat and the reply: (answer, find, ask or other, the
    judge's word)."""
    verdict = said(relay.ask([{"role": "system", "content": JUDGE}, {
        "role": "user", "content": f"<chat>\n{seen(row)}\n</chat>\n\n<reply>\n{reply}\n</reply>"}]))
    word = (re.findall(r"[a-z]+", verdict.lower()) or ["other"])[0]
    return ACTED.get(word, "other"), verdict


async def case(ws, agent, relay: Relay, number: int, row: tuple) -> dict:
    from mibo import dm
    from mibo.library import Item, Library
    label, exchange, find, message, answers, right = row
    ws.reset_chat()
    room = ws._main
    pkey = dm.chat_key(room.conversation)[1]
    now = time.time()
    history = []
    if exchange:
        room.append([{"role": "user", "text": exchange[0]}, {"role": "assistant", "text": exchange[1]}])
        history = [{"role": "user", "content": exchange[0], "name": "you", "t": now - 300, "seq": 1},
                   {"role": "assistant", "content": exchange[1], "t": now - 290, "seq": 2}]
    item = Library(ws._runtime()).add(Item(
        url=f"https://{find['site']}/{find['kind']}/{number}{int(now)}", site=find["site"], kind=find["kind"],
        title=find["title"], description=find["excerpt"], picture="cover.jpg", seen_at=int(now) - 3600))

    async def due() -> bool:
        return True

    async def take(surface: str, now: bool = False):
        return {"line": find["line"]}, item

    ws._share_due, ws.chooser.take = due, take
    assert await ws.share() == 1
    asked, quotes = ws._record_asked(room, message, [], [], item.id if answers else "")
    text = await agent._read_message([*quotes, {"type": "text", "text": message}])
    history.append({"role": "user", "content": text, "name": "you", "t": time.time(), "seq": len(history) + 1})
    system = agent._dm_system()
    plan, ratio = agent._turn_plan(system, tools=True)
    prompt = agent._build_dm_prompt(history, room=plan.turn / ratio, window=plan.window, pkey=pkey)
    sent = [{"role": "system", "content": system}, *prompt.messages_with_context(prompt.messages)]
    reply = said(relay.ask(sent, agent._offered_tools()))
    asked.pop("pending", None)
    acted, verdict = judge(relay, row, reply)
    return {"label": label, "right": right, "acted": acted, "ok": acted in right.split("|"), "reply": reply,
            "verdict": verdict, "user_turn": text, "finds": "<finds_in_this_chat>" in prompt.turn_context}


def show(number: int, got: dict) -> None:
    print(f"{number:>2} {got['label']:<14} right {got['right']:<10} acted {got['acted']:<7} "
          f"{'ok' if got['ok'] else 'WRONG'}  | {got['reply'][:90]!r}", flush=True)


async def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("home")
    args.add_argument("--keys", required=True)
    args.add_argument("--out", required=True)
    args.add_argument("--only", default="")
    args.add_argument("--calls", type=int, default=44)
    args.add_argument("--rejudge", default="", help="judge the replies of a results file again")
    a = args.parse_args()
    if a.rejudge:
        import scratchhome
        relay = Relay(scratchhome.keys(a.keys), a.calls)
        with open(a.out, "a", encoding="utf-8") as out:
            for line in Path(a.rejudge).read_text(encoding="utf-8").splitlines():
                got = json.loads(line)
                got["acted"], got["verdict"] = judge(relay, CASES[got["case"] - 1], got["reply"])
                got["ok"] = got["acted"] in got["right"].split("|")
                out.write(json.dumps(got, ensure_ascii=False) + "\n")
                show(got["case"], got)
        print(f"calls used: {relay.used}")
        return
    home = Path(a.home).resolve()
    home.mkdir(parents=True, exist_ok=True)
    os.environ["AGENT_HOME"] = str(home)
    import scratchhome
    keys = scratchhome.keys(a.keys)
    from mibo import paths, settingsfile, taste
    from mibo.agent import Agent
    from mibo.workspace import Workspace
    settingsfile.write(home, {"LLM_BASE_URL": keys["LLM_BASE_URL"], "LLM_MODEL": "haiku", "PERSONA_NAME": "Mibo",
                              "AGENT_LANG": "zh", "ROAM_ENABLED": "false", "UPDATE_CHECK_ENABLED": "false"})
    paths.use_home(home)
    taste.fit = lambda runtime, soon=False: None
    ws = Workspace(home)
    agent = Agent(api_key=keys["LLM_API_KEY"], base_url=keys["LLM_BASE_URL"], model="haiku", llm_dm_model="haiku",
                  agent_lang="zh", persona_name="Mibo", memory_file=str(home / "runtime" / "memory.json"),
                  embedding_model="")
    relay = Relay(keys, a.calls)
    only = {int(n) for n in a.only.split(",") if n}
    with open(a.out, "a", encoding="utf-8") as out:
        for number, row in enumerate(CASES, 1):
            if only and number not in only:
                continue
            got = await case(ws, agent, relay, number, row)
            out.write(json.dumps({"case": number, **got}, ensure_ascii=False) + "\n")
            out.flush()
            show(number, got)
    print(f"calls used: {relay.used}")


if __name__ == "__main__":
    asyncio.run(main())
