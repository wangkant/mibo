"""LoCoMo (snap-research/locomo, locomo10.json) put through Mibo as a person uses it: each conversation fed as one
person's chat with the character over its dated sessions, then each question of categories 1-4 asked once, in its
own words, in a fresh chat. score.py scores the answers.

    python tools/bench/locomo/replay.py --data <locomo10.json> --out <folder> --keys <file> [--convs 2]
        [--seed 20261121] [--mode real|oracle|off] [--budget 0.60] [--port 61480] [--only conv-49]
        [--every 1] [--model deepseek/deepseek-v4.1-flash]

The rule, stated with every result (README.md):
- Speakers: speaker_a is the person, speaker_b the character. The character's name in the app is speaker_b's name;
  before the first session the person tells it their own name with the remember command, as on a first day.
- Feeding: every line of the person's is a message in the app's main chat, sent through its own chat interface
  (POST /api/chat), so the app's own turn path takes it in: its chat record, the page's copy, the person's store
  after the turn, its compaction and the fold's own triggers. The character's answer to it is the next line of
  speaker_b, handed to the reply loop in place of the reply model's answer (the turn makes no model call); a session
  that ends on the person's line is answered "Talk soon!". A session that speaker_b opens has that line put in the
  chat's turns the way the app keeps a line the character says unasked (followup.py's commit). A shared photo is its
  BLIP caption after the words, as LoCoMo's own evaluation puts it: "... [shared a photo: <caption>]".
- Time: the app runs on a movable clock (tools/memory_life.py's sitecustomize: time.time, datetime.now and
  date.today in the app's process give the session's date). Each session starts at its date and time, a line a
  minute. After its last line the clock goes six minutes on, past the fold's five minutes of quiet, and the app's own
  trigger (Agent._maybe_fold_person, what its minute loop calls) is called at once rather than waiting for the loop.
  The day after the last session, 10:00, the chat record is pruned as the app's daily round prunes it
  (ChatLog.prune: MEMORY_LOG_DAYS, 30 by default) and the questions are asked.
- Questions: each in a new chat (POST /api/chats), the question's words alone, answered by the app's reply loop with
  its own recall and tools; the chat is deleted afterwards (POST /api/chats/delete) so no later question finds it.
  While the questions run the fold is held (marked running), so each question sees the same store.
- Offline: the app's process reaches no host but this computer (the model is the Meter on 127.0.0.1): a public copy
  of LoCoMo is on the web, and a reply loop that searches finds it.
- Modes: real (the reply loop on the model), oracle (the reply loop's answer is the gold answer: the scorer's top),
  off (memory off in Settings > Memory and no chat record from the start, the same feed: the floor; give it its own
  --out).
  --resume starts a fed home again and asks the questions its answers file does not hold yet (after a budget cut).

Every model call goes through tools/everyday.py's Meter, which refuses calls past --budget dollars; the key is read
from --keys (LLM_API_KEY and LLM_BASE_URL), never printed, and reaches the app only through its environment
(tools/scratchhome.py). Out, per conversation: <out>/<id>/answers.jsonl, feed.jsonl, model.jsonl and
model-full.jsonl (every call, whole), calls.jsonl (each call's purpose), folds.jsonl, person_s<N>.json (the store
after each session's fold), person_end.json; <out>/run.json."""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE), str(REPO / "tools"), str(REPO)]

import memory_life  # noqa: E402  (the movable clock, the control channel and the fold trigger)
import scratchhome  # noqa: E402
from everyday import Meter  # noqa: E402
from sessions import asked_on, keys, old, when  # noqa: E402

SEED = 20261121
CATS = (1, 2, 3, 4)
LINE_S = 60
QUIET_S = 6 * 60
LAST_WORD = "Talk soon!"
PRICE = (0.0498, 0.000996, 0.1992)

# Installed in the app through the control channel: a reply call of the turn whose message is the scripted one is
# answered with the scripted line (no model call); every other call goes on as it was.
SCRIPTED = '''
import pathlib
from mibo import llm
book = pathlib.Path(%r)
real = agent._post_chat
async def post(url, key, payload, *, timeout, retries=0):
    if llm._call_purpose.get() == "reply":
        try:
            s = json.loads(book.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            s = {}
        users = [m for m in payload.get("messages") or [] if m.get("role") == "user"]
        last = json.dumps(users[-1].get("content") if users else "", ensure_ascii=False)
        if s.get("said") and s.get("reply") and json.dumps(s["said"][:60], ensure_ascii=False)[1:-1] in last:
            return {"id": "scripted", "object": "chat.completion", "model": payload.get("model"),
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": s["reply"]}}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0}}
    return await real(url, key, payload, timeout=timeout, retries=retries)
agent._post_chat = post
return "scripted"
'''

# A line the character says unasked, kept in the chat's turns as followup.py keeps one.
UNASKED = '''
from mibo import db
from mibo.dm import chat_key
(conv,), = db.at(agent.memory_file.parent).read("SELECT conversation FROM page_chats WHERE id = 'main'")
user_id, pkey = chat_key(conv)
async with agent.locks[pkey]:
    agent._rehydrate_page(user_id, pkey)
    agent._commit_dm_history(user_id, pkey, [*agent.dm_history.get(user_id, []),
                             {"role": "assistant", "content": %r, "t": time.time(), "seq": agent._next_seq(pkey)}])
return pkey
'''

# Prepended to the movable clock's sitecustomize: the app's process reaches no host but this computer (the model is
# the Meter on 127.0.0.1), because a public copy of LoCoMo is on the web and a reply loop that searches finds it.
OFFLINE = '''import socket
_lookup = socket.getaddrinfo
def _here_only(host, *args, **kwargs):
    if host not in (None, "127.0.0.1", "localhost", "::1", b"127.0.0.1", b"localhost"):
        raise socket.gaierror(socket.EAI_NONAME, "offline")
    return _lookup(host, *args, **kwargs)
socket.getaddrinfo = _here_only
'''

HOLD = '''
agent._folding.add("person")
return {"pruned": agent.chat_log.prune(time.time()), "facts": len(agent.person_store.facts()),
        "plans": len(agent.person_store.plans())}
'''


def words(turn: dict) -> str:
    """A line as said, with a shared photo's caption after it (LoCoMo's own evaluation adds it so)."""
    caption = f" [shared a photo: {turn['blip_caption']}]" if turn.get("blip_caption") else ""
    return turn["text"] + caption


def exchanges(turns: list[dict], person: str) -> tuple[str, list[tuple[dict, str]]]:
    """(the character's opening line or "", [(the person's turn, the character's answer)]) of one session."""
    opening = ""
    if turns[0]["speaker"] != person:
        opening, turns = words(turns[0]), turns[1:]
    out = []
    for i in range(0, len(turns), 2):
        reply = words(turns[i + 1]) if i + 1 < len(turns) else LAST_WORD
        out.append((turns[i], reply))
    return opening, out


def picked(data: list[dict], n: int, seed: int) -> list[dict]:
    ids = [s["sample_id"] for s in data]
    chosen = random.Random(seed).sample(ids, n)
    return [next(s for s in data if s["sample_id"] == i) for i in chosen]


class Stub(BaseHTTPRequestHandler):
    """The model for a run with no key: every call answered "OK"."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.answer({"id": "stub", "object": "chat.completion", "model": "stub",
                     "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0}})

    def do_GET(self):
        self.answer({"data": [{"id": "stub", "context_length": 65536}]})

    def answer(self, body: dict):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Run(memory_life.Life):
    """One conversation's home and app."""

    def __init__(self, work: Path, port: int):
        super().__init__(work, port)
        self.script = self.ctl / "script.json"

    def at(self, t: datetime):
        self.set_clock(t.year, t.month, t.day, t.hour, t.minute)

    def say(self, text: str, reply: str, chat: str = "") -> dict:
        """One message of the person's; `reply` is what the scripted turn answers ("" for the real model)."""
        self.script.write_text(json.dumps({"said": text, "reply": reply}, ensure_ascii=False), encoding="utf-8")
        began = time.time()
        status, res = self.api("POST", "chat", {"text": text, **({"chat": chat} if chat else {})})
        said = [m for m in (res.get("messages") or []) if m.get("role") == "assistant"] if isinstance(res, dict) else []
        return {"status": status, "reply": "\n".join(m.get("text") or "" for m in said) if said else str(res)[:300],
                "steps": [f"{t.get('tool')} {t.get('what') or ''}".strip() for m in said for t in m.get("trace") or []],
                "used": [u for m in said for u in (m.get("memory") or {}).get("used") or []],
                "secs": round(time.time() - began, 1), "at": self.now()}


def feed(run: Run, sample: dict, log: Path) -> None:
    conv = sample["conversation"]
    person = conv["speaker_a"]
    order = keys(conv)
    run.at(when(conv, order[0]) - timedelta(minutes=5))
    first = run.say(f"Remember that my name is {person}.", "")
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"session": 0, "said": f"Remember that my name is {person}.", **first}, ensure_ascii=False) + "\n")
    for key in order:
        n = int(key.split("_")[1])
        start = when(conv, key)
        opening, pairs = exchanges(conv[key], person)
        minute = 0
        run.at(start)
        if opening:
            run.tag(f"s{n}.open")
            run.run(UNASKED % opening)
            minute += 1
        for turn, reply in pairs:
            run.at(start + timedelta(minutes=minute))
            run.tag(f"s{n}.{turn['dia_id']}")
            rec = run.say(words(turn), reply)
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"session": n, "dia_id": turn["dia_id"], "scripted": rec["reply"] == reply,
                                    "status": rec["status"], "secs": rec["secs"],
                                    **({} if rec["reply"] == reply else {"reply": rec["reply"]})}, ensure_ascii=False) + "\n")
            minute += 2
        run.at(start + timedelta(minutes=minute) + timedelta(seconds=QUIET_S))
        run.tag(f"fold{n}")
        fold = run.run(memory_life.FOLD)
        (run.out / f"person_s{n}.json").write_text(json.dumps(run.person(), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {sample['sample_id']} {key} ({len(pairs)} turns): fold {json.dumps(fold, ensure_ascii=False)[:160]}",
              flush=True)


def ask(run: Run, sample: dict, mode: str, every: int, meter: Meter, budget: float, out: Path) -> int:
    conv = sample["conversation"]
    run.at(asked_on(conv))
    run.tag("hold")
    print("  hold:", json.dumps(run.run(HOLD)), flush=True)
    done = {json.loads(line)["k"] for line in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    asked = 0
    for k, qa in enumerate(sample["qa"]):
        # Memory off is the floor of what needs an old session: only those are asked.
        if qa["category"] not in CATS or k % every or k in done or (mode == "off" and not old(qa, conv)):
            continue
        if meter.spent >= budget:
            print(f"  budget reached at question {k}", flush=True)
            return asked
        run.tag(f"q{k}")
        chat = run.api("POST", "chats", {})[1]["id"]
        began = len(meter.rows)
        rec = run.say(qa["question"], str(qa["answer"]) if mode == "oracle" else "", chat=chat)
        run.api("POST", "chats/delete", {"id": chat})
        calls = meter.rows[began:]
        row = {"k": k, "category": qa["category"], "question": qa["question"], "answer": qa["answer"],
               "evidence": qa.get("evidence", []), "reply": rec["reply"], "status": rec["status"],
               "steps": rec["steps"], "used": rec["used"], "secs": rec["secs"],
               "calls": len(calls), "cost": round(sum(c["cost"] for c in calls), 6),
               "full": [began, began + len(calls)], "refused": any(c["status"] == 429 for c in calls)}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        asked += 1
        print(f"  q{k} c{qa['category']} {qa['question'][:60]!r} => {rec['reply'][:90]!r}", flush=True)
    return asked


def home_env(work: Path, port: int, model: str, base: str, key: str, character: str, fresh: bool, off: bool) -> dict:
    home = work / "home"
    if fresh:
        if work.exists():
            shutil.rmtree(work)
        shutil.rmtree(f"{home}-pc", ignore_errors=True)
        for d in (work / "ctl", work / "out", work / "site"):
            d.mkdir(parents=True)
    (work / "site/sitecustomize.py").write_text(OFFLINE + memory_life.SITE, encoding="utf-8")
    extra = {"MEMORY_LOG_DAYS": "0"} if off else {}
    made = scratchhome.make(home, key=key, LLM_BASE_URL=base, PAGE_PORT=port, AGENT_LANG="en",
                            PERSONA_TZ_OFFSET_HOURS="-8", PERSONA_NAME=character, LLM_MODEL=model,
                            LLM_JUDGE_MODEL=model, **extra)
    # ddgs's own client resolves names itself: a proxy that is not there stops it.
    return {**made, "PYTHONPATH": os.pathsep.join([str(work / "site"), str(REPO), made["PYTHONPATH"]]),
            "DDGS_PROXY": "http://127.0.0.1:9"}


def one(sample: dict, args, meter: Meter, base: str, key: str) -> dict:
    conv = sample["conversation"]
    work = args.out / sample["sample_id"]
    off = args.mode == "off"
    fresh = not args.resume
    if not fresh and not (work / "home").exists():
        raise SystemExit(f"{work}: --resume starts again the home a run fed")
    run = Run(work, args.port)
    run.env = home_env(work, args.port, args.model, base, key, conv["speaker_b"], fresh, off)
    if fresh:
        run.at(when(conv, keys(conv)[0]) - timedelta(minutes=10))
    run.start()
    try:
        run.run(SCRIPTED % str(run.script))
        if off:
            print("  memory off:", run.api("POST", "person/settings", {"on": False})[0], flush=True)
        if fresh:
            feed(run, sample, run.out / "feed.jsonl")
        name = {"real": "answers.jsonl", "oracle": "answers_oracle.jsonl", "off": "answers_off.jsonl"}[args.mode]
        asked = ask(run, sample, args.mode, args.every, meter, args.budget, run.out / name)
        (run.out / "person_end.json").write_text(
            json.dumps(run.person(), ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        run.stop()
        # The chat record as the questions found it (their own chats were deleted with them), for trace.py.
        with sqlite3.connect(work / "home/runtime/mibo.db") as db:
            rows = db.execute("SELECT seq, t, name, self, text FROM chatlog ORDER BY conv, seq").fetchall()
        (run.out / "chatlog_end.json").write_text(json.dumps(
            [dict(zip(("seq", "t", "name", "self", "text"), r)) for r in rows], ensure_ascii=False), encoding="utf-8")
        for name in ("calls.jsonl", "folds.jsonl"):
            if (run.ctl / name).exists():
                shutil.copy(run.ctl / name, run.out / name)
    return {"id": sample["sample_id"], "asked": asked, "spent": round(meter.spent, 5)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keys", type=Path, help="LLM_API_KEY and LLM_BASE_URL; without it a stand-in model")
    ap.add_argument("--convs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--only", default="", help="conversation ids, comma separated, in place of the draw")
    ap.add_argument("--mode", choices=("real", "oracle", "off"), default="real")
    ap.add_argument("--resume", action="store_true", help="ask the questions not yet answered, on the fed home")
    ap.add_argument("--every", type=int, default=1, help="every Nth question by its index")
    ap.add_argument("--budget", type=float, default=0.60)
    ap.add_argument("--port", type=int, default=61480, help="the app; the meter takes the next")
    ap.add_argument("--model", default="deepseek/deepseek-v4.1-flash")
    args = ap.parse_args(argv)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    data = json.loads(args.data.read_text(encoding="utf-8"))
    samples = ([s for i in args.only.split(",") for s in data if s["sample_id"] == i] if args.only
               else picked(data, args.convs, args.seed))
    if args.keys:
        lent = scratchhome.keys(args.keys)
        upstream, key, model = lent["LLM_BASE_URL"], lent["LLM_API_KEY"], args.model
    else:
        stub = ThreadingHTTPServer(("127.0.0.1", args.port + 2), Stub)
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        upstream, key, model = f"http://127.0.0.1:{args.port + 2}/v1", "stub", "stub"
        args.model = model
    for sample in samples:
        (args.out / sample["sample_id"] / "out").mkdir(parents=True, exist_ok=True)
    meter = Meter(upstream, args.out / "model.jsonl", args.budget, PRICE)
    meter.serve(args.port + 1)
    base = f"http://127.0.0.1:{args.port + 1}/v1"
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    done = []
    for sample in samples:
        print(sample["sample_id"], args.mode, flush=True)
        done.append(one(sample, args, meter, base, key))
        if meter.spent >= args.budget:
            break
    run = {"mode": args.mode, "model": model, "seed": args.seed, "drawn": [s["sample_id"] for s in samples],
           "every": args.every, "commit": commit, "budget": args.budget, "spent": round(meter.spent, 5),
           "calls": len(meter.rows), "convs": done, "command": " ".join(["replay.py", *argv])}
    with (args.out / "run.json").open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")
    print(json.dumps(run, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
