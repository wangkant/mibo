"""A WebVoyager subset on real sites through Mibo's own hands: each task's start page in a headless Edge tab, worked
by web/operate.run (its prompt, reply form, budget and gate) with the task's own words, then judged WebJudge-style
from the final page.

    python -I tools/bench/webvoyager/run.py --env <.env with LLM_API_KEY, LLM_BASE_URL> [--model deepseek/deepseek-v4.1-flash]
        [--out <folder>] [--ids Apple--0,ArXiv--1] [--workers 1] [--budget 0.05] [--tools no|yes] [--cheapest]

The tasks are tasks.json (30 of WebVoyager's 643, on sites a visitor reads signed out). The browser is signed out
and fresh each task, with the headless browser's own user agent: a bot check is not got past, it is the task's
result (operate.run hands such a page back). The bench answers no to every card the gate raises and the run stops
there: a card on a reading task means it was about to send, change or leave the site, and that stop is its result.
One task at a time by default, with a pause between, so no site gets more than a person's pace.

The judge follows WebJudge (Online-Mind2Web, arXiv:2504.01382): one call lists the task's key points from its words
alone, a second decides from the key points, the run's steps, its answer and the final page as text lines whether
every key point is met. The judge is the same model, called the same way; its calls count toward --budget.

Results append to <out>/results.jsonl, one line a task (a rerun skips those already there); each task's steps, model
answers, final page and verdict go to <out>/episodes/. A person reading a sample writes <out>/hand.json
({"id": [true|false, "why"]}) and report.py puts the two side by side. The key is read from --env and never
printed or written; spend is summed from OpenRouter's usage.cost and no new task starts past --budget dollars."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from mibo.roam import fence_pages  # noqa: E402
from mibo.textproc import strip_json_fences  # noqa: E402
from mibo.web import gate, operate  # noqa: E402
from mibo.web.pageops import clip  # noqa: E402
from mibo.web.tabs import PlaywrightTab  # noqa: E402

# The MiniWoB bench's model call and .env reader, loaded under a name of its own (both files are run.py).
_spec = importlib.util.spec_from_file_location("miniwob_run", HERE.parent / "miniwob" / "run.py")
miniwob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(miniwob)

TASK_S = 300
PAUSE_S = 3.0
FINAL_MAX = 20_000

KEY_POINTS = """You read a task a web agent was given on a real website. List its key points: each requirement the \
outcome must meet, as the task words it (a filter, a sort order, a range, a count, a date, a piece of information to \
report). Do not add requirements the task does not state. Answer with one JSON object: {"key_points": ["...", "..."]}"""

VERDICT = """You judge whether a web agent completed a task on a real website. You get the task, its key points, the \
agent's steps, its final answer and the final page as text lines (`[id] role "name"` lines are controls, other \
lines are text the page shows).
- Success only when every key point is met.
- A filter, sort order or range the task names must have been applied on the site: the steps, the address or the \
final page must show it. Saying so is not enough.
- Information the task asks for must be in the final answer, and the final page or the steps must agree with it. An \
answer the page does not support, or no answer to a task that asks for information, is a failure.
- A run that stopped at a sign-in, a bot check or a question to the person, with the task not done, is a failure.
- The task may have been written years ago: where the site now shows newer items (a newer model, a later date), \
using the current ones is right.
Answer with one JSON object: {"met": [true or false for each key point, in order], "success": true or false, \
"why": "<one sentence>"}"""


def _json(answer: str) -> dict:
    try:
        value = json.loads(strip_json_fences(str(answer or "")))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def judge(model, task: str, steps: list[str], status: str, result: str, url: str, page: str,
                log: list) -> dict:
    """WebJudge's key points, then the verdict from the final page."""
    points = _json(await model.ask(KEY_POINTS, [{"role": "user", "content": f"Task: {task}\nReply with one JSON "
                                                                               f"object."}], log))
    points = [str(p) for p in points.get("key_points") or []][:12]
    verdict = _json(await model.ask(VERDICT, [{"role": "user", "content": (
        f"Task: {task}\nKey points:\n" + "\n".join(f"{n}. {p}" for n, p in enumerate(points, 1))
        + "\nSteps:\n" + "\n".join(f"- {clip(s, 300)}" for s in steps[-15:])
        + f"\nHow the run ended: {status}\nFinal answer: {result or '(none)'}\nFinal address: {url}\n"
        + "Final page:\n" + fence_pages(page) + "\nReply with one JSON object.")}], log))
    return {"key_points": points, "met": verdict.get("met"), "success": verdict.get("success") is True,
            "why": " ".join(str(verdict.get("why") or "").split())[:300]}


async def episode(page, task: dict, model, allowed: gate.Allowed, able: dict, limits: dict) -> tuple[dict, dict]:
    tab = PlaywrightTab(page)
    await page.goto(task["web"], timeout=45_000, wait_until="domcontentloaded")
    await asyncio.sleep(2)
    cards: list[dict] = []
    calls: list[dict] = []
    judged: list[dict] = []

    async def ask(card: dict) -> dict:
        cards.append({k: str(card.get(k, ""))[:200] for k in ("kind", "button", "to", "text", "why")})
        return {"yes": False, "never": False}

    hands = operate.Hands(tab, ask=ask, allowed=allowed, attended=lambda: False,
                          held=lambda: "stopped" if cards else "", lang="en")

    async def ask_model(system: str, messages: list[dict]) -> str:
        return await model.ask(system, messages, calls)

    began = time.monotonic()
    try:
        outcome = await asyncio.wait_for(operate.run(ask_model, hands, task["ques"], able=able), timeout=TASK_S)
    except asyncio.TimeoutError:
        outcome = {"status": "timeout", "result": "", "steps": []}
    except Exception as exc:
        outcome = {"status": "error", "result": f"{type(exc).__name__}: {str(exc)[:300]}", "steps": []}
    seconds = time.monotonic() - began
    url, final = page.url, ""
    try:
        final = await hands.page.state(limits["page"])
    except Exception as exc:
        final = f"(the final page could not be read: {type(exc).__name__})"
    await hands.close()
    steps = [str(s) for s in outcome.get("steps") or []]
    verdict = await judge(model, task["ques"], steps, str(outcome.get("status")), str(outcome.get("result") or ""),
                          url, clip(final, FINAL_MAX), judged)
    row = {"id": task["id"], "site": task["web_name"], "model": model.model, "success": verdict["success"],
           "status": outcome.get("status"), "proof": outcome.get("proof", ""),
           "result": str(outcome.get("result") or "")[:600], "url": url, "calls": len(calls),
           "in": sum(c["in"] for c in calls), "out": sum(c["out"] for c in calls),
           "cached": sum(c["cached"] for c in calls), "cost": round(sum(c["cost"] for c in calls), 6),
           "judge_cost": round(sum(c["cost"] for c in judged), 6),
           "errors": sum(1 for c in calls + judged if c["error"]), "seconds": round(seconds, 1), "cards": cards,
           "why": verdict["why"], "code": miniwob.CODE}
    detail = {**row, "task": task["ques"], "steps": steps, "verdict": verdict, "final": final,
              "answers": [{k: c[k] for k in ("answer", "error", "s")} for c in calls],
              "judge": [{k: c[k] for k in ("answer", "error")} for c in judged]}
    return row, detail


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, help=".env holding LLM_API_KEY and LLM_BASE_URL")
    parser.add_argument("--model", default="deepseek/deepseek-v4.1-flash")
    parser.add_argument("--out", default="")
    parser.add_argument("--ids", default="")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--budget", type=float, default=0.05, help="dollars; no new task past it")
    parser.add_argument("--tools", choices=("no", "yes"), default="no",
                        help="whether the app's check found the model calling a tool by itself")
    parser.add_argument("--cheapest", action="store_true", help="route each call to the host's cheapest provider")
    args = parser.parse_args(argv)
    env = miniwob.read_env(Path(args.env))
    from mibo import abilities
    able = {"tools": args.tools, "context": await abilities._context(
        env["LLM_BASE_URL"].rstrip("/") + "/chat/completions", "", args.model)}
    limits = operate.budget(able)
    print(f"budget {limits} from {able}", flush=True)
    slug = args.model.replace("/", "_").replace(":", "_")
    out = Path(args.out or REPO.parent / "ref" / "bench" / "webvoyager" / slug).resolve()
    (out / "episodes").mkdir(parents=True, exist_ok=True)
    tasks = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))
    if args.ids:
        tasks = [t for t in tasks if t["id"] in args.ids.split(",")]
    results = out / "results.jsonl"
    have = {json.loads(line)["id"] for line in results.read_text(encoding="utf-8").splitlines()} \
        if results.exists() else set()
    queue: asyncio.Queue = asyncio.Queue()
    for task in tasks:
        if task["id"] not in have:
            queue.put_nowait(task)
    print(f"{queue.qsize()} tasks to run ({len(have)} already in {results})", flush=True)
    model = miniwob.Model(env["LLM_BASE_URL"], env["LLM_API_KEY"], args.model, args.budget)
    model.answer = limits["answer"]
    if args.cheapest:
        model.extra = {"provider": {"sort": "price"}}
    allowed = gate.Allowed(out)
    skipped: list[str] = []
    lock = asyncio.Lock()
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True)

        async def worker() -> None:
            while not queue.empty():
                task = queue.get_nowait()
                if model.spent >= args.budget:
                    skipped.append(task["id"])
                    continue
                # Signed out and fresh: no cookies, storage or history carried from the last task.
                context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US",
                                                    timezone_id="America/Los_Angeles")
                page = await context.new_page()
                # Playwright would dismiss a page's dialog before the hands hear it.
                page.on("dialog", lambda dialog: None)
                try:
                    row, detail = await episode(page, task, model, allowed, able, limits)
                except Exception as exc:
                    print(f"  {task['id']}: harness error {type(exc).__name__}: {str(exc)[:200]}", flush=True)
                    continue
                finally:
                    await context.close()
                async with lock:
                    with results.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    (out / "episodes" / f"{task['id'].replace(' ', '_')}.json").write_text(
                        json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  {task['id']}: {'OK ' if row['success'] else 'no '} {row['status']:<9} calls={row['calls']} "
                      f"{row['seconds']}s  spent ${model.spent:.4f}", flush=True)
                await asyncio.sleep(PAUSE_S)

        await asyncio.gather(*(worker() for _ in range(args.workers)))
        await browser.close()
    await model.client.aclose()
    if skipped:
        print(f"budget reached: {len(skipped)} tasks not run: {skipped}", flush=True)
    print(f"spent this run ${model.spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
