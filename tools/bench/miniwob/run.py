"""MiniWoB++ through Mibo's own hands: each task's page in a headless Chromium (Edge) tab, seen as pageops'
numbered lines, worked by web/operate.run's prompt, reply form and caps, every action through gate.py. The
confirmation card is answered "yes" by the bench and kept; the task's own reward says whether it was done.

    python -I tools/bench/miniwob/run.py --env <.env with LLM_API_KEY, LLM_BASE_URL> [--model deepseek/deepseek-v4-flash]
        [--out <folder>] [--tasks click-button,enter-text] [--seeds 0,1,2,3,4] [--workers 4] [--budget 0.38]
        [--port 59260] [--data <miniwob html folder>]

One episode: the task page fresh, Math.seedrandom(seed) (what the gym env's reset(seed) does), the task's timer
lifted to ten minutes (an LLM step takes seconds; the raw reward has no time penalty), core.startEpisodeReal(),
then operate.run with the task's own words. The episode ends when the task's reward fires (WOB_DONE_GLOBAL) or when
operate.run stops (done, cap, handover...). Success: done and raw reward 1.0.

Results append to <out>/results.jsonl, one line an episode (a rerun skips the episodes already there), each
episode's pages, model answers and cards to <out>/episodes/. The key is read from --env and never printed or
written; spend is summed from OpenRouter's usage.cost and no new episode starts past --budget dollars."""
from __future__ import annotations

import argparse
import asyncio
import functools
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from tasks import TASKS  # noqa: E402

from persona_agent.llm import thinking_off  # noqa: E402
from persona_agent.web import gate, operate  # noqa: E402
from persona_agent.web.pageops import fold  # noqa: E402
from persona_agent.web.tabs import PlaywrightTab  # noqa: E402

# The product files this run was made with (others edit them): a short hash of each, as imported.
CODE = {f: __import__("hashlib").sha1((REPO / "persona_agent" / "web" / f).read_bytes()).hexdigest()[:10]
        for f in ("operate.py", "pageops.py", "gate.py")}
DATA = REPO.parent / "ref" / "datasets" / "miniwob" / "src" / "miniwob" / "html"
EPISODE_MS = 600_000
EPISODE_S = 420


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    # Five pages loading their scripts at once overflow the default backlog of 5 (a script then fails to load).
    request_queue_size = 128
    daemon_threads = True


def serve(root: Path, port: int) -> ThreadingHTTPServer:
    server = Server(("127.0.0.1", port), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def read_env(path: Path) -> dict:
    return {k.strip(): v.strip() for k, _, v in (line.partition("=") for line in path.read_text().splitlines())
            if v}


class Model:
    """The operate call as search.py makes it: max_tokens 900, temperature 0.2, a JSON object, thinking off."""

    def __init__(self, base: str, key: str, model: str, budget: float):
        import httpx
        self.base, self.key, self.model, self.budget = base.rstrip("/"), key, model, budget
        self.client = httpx.AsyncClient(timeout=120, trust_env=False)
        self.spent = 0.0
        self.reasoning = {"enabled": False}

    async def ask(self, system: str, messages: list[dict], log: list) -> str:
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages],
                   "max_tokens": 900, "temperature": 0.2, "response_format": {"type": "json_object"},
                   "usage": {"include": True}}
        thinking_off(payload, self.base, False)
        began = time.monotonic()
        data, error = {}, ""
        for attempt in range(3):
            if "reasoning" in payload:
                payload["reasoning"] = self.reasoning
            try:
                answer = await self.client.post(self.base + "/chat/completions", json=payload,
                                                headers={"Authorization": f"Bearer {self.key}"})
                data = answer.json()
            except Exception as exc:
                error, data = type(exc).__name__, {}
                await asyncio.sleep(2 + 3 * attempt)
                continue
            if answer.status_code == 200 and data.get("choices"):
                error = ""
                break
            error = f"{answer.status_code} {str((data.get('error') or {}).get('message') or '')[:160]}"
            if answer.status_code == 400 and "reasoning" in error.lower() and self.reasoning.get("enabled") is False:
                self.reasoning = {"effort": "minimal"}
                continue
            await asyncio.sleep(2 + 3 * attempt)
        usage = data.get("usage") or {}
        cost = float(usage.get("cost") or 0)
        self.spent += cost
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        log.append({"s": round(time.monotonic() - began, 2), "error": error, "answer": content,
                    "prompt": messages[-1]["content"], "in": usage.get("prompt_tokens", 0),
                    "out": usage.get("completion_tokens", 0),
                    "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0), "cost": cost})
        return content


class BenchHands(operate.Hands):
    """Hands on a MiniWoB page: a look after the task's reward fired says the episode is over."""

    def __init__(self, tab: PlaywrightTab, **kw):
        super().__init__(tab, **kw)
        self.bench_typed: list[str] = []
        self.looks: list[str] = []

    async def ended(self) -> bool:
        try:
            return bool(await self.tab.evaluate("() => WOB_DONE_GLOBAL"))
        except Exception:
            return False

    async def look(self) -> dict:
        if await self.ended():
            return {"status": "ended"}
        look = await super().look()
        self.looks.append(str(look.get("state") or ""))
        return look

    async def act(self, action: dict) -> dict:
        if action.get("do") == "type":
            self.bench_typed.append(str(action.get("text") or ""))
        return await super().act(action)


async def episode(page, site: str, name: str, seed: int, model: Model, allowed: gate.Allowed) -> tuple[dict, dict]:
    tab = PlaywrightTab(page)
    await tab.goto(f"{site}/miniwob/{name}.html")
    await page.wait_for_function("() => document.readyState === 'complete' && window.core && core.cover_div")
    await page.evaluate(f"() => {{ Math.seedrandom({seed}); core.setDataMode('train'); "
                        f"core.EPISODE_MAX_TIME = {EPISODE_MS}; core.startEpisodeReal(); }}")
    for _ in range(40):
        if await page.evaluate("() => WOB_TASK_READY"):
            break
        await asyncio.sleep(0.05)
    task = await page.evaluate("() => core.getUtterance()")
    # A few tasks answer {utterance, fields}; the person's words are the utterance alone.
    task = task["utterance"] if isinstance(task, dict) else str(task)
    cards: list[dict] = []
    calls: list[dict] = []
    hands: BenchHands

    async def ask(card: dict) -> dict:
        shown = fold(await page.evaluate("() => document.body.innerText") or "")
        values = await page.evaluate("() => [...document.querySelectorAll('input,button')].map((e) => e.value || '')")
        button = fold(card.get("button") or "").strip()
        text = card.get("text") or ""
        cards.append({**{k: card.get(k, "") for k in ("kind", "button", "to", "text", "label", "why")},
                      "button_on_page": bool(button) and (button in shown or any(button == fold(v).strip()
                                                                                 for v in values)),
                      "text_typed": (not text) or any(t and t.strip() in text for t in hands.bench_typed)})
        return {"yes": True, "never": False}

    hands = BenchHands(tab, ask=ask, allowed=allowed, attended=lambda: False)

    async def ask_model(system: str, messages: list[dict]) -> str:
        return await model.ask(system, messages, calls)

    began = time.monotonic()
    try:
        outcome = await asyncio.wait_for(operate.run(ask_model, hands, task), timeout=EPISODE_S)
    except asyncio.TimeoutError:
        outcome = {"status": "timeout", "result": "", "steps": []}
    except Exception as exc:
        outcome = {"status": "error", "result": f"{type(exc).__name__}: {str(exc)[:300]}", "steps": []}
    seconds = time.monotonic() - began
    if hasattr(hands, "close"):
        await hands.close()
    meta = await page.evaluate("() => ({done: WOB_DONE_GLOBAL, raw: WOB_RAW_REWARD_GLOBAL, "
                               "reason: WOB_REWARD_REASON})")
    row = {"task": name, "seed": seed, "model": model.model, "utterance": task,
           "success": bool(meta["done"]) and float(meta["raw"] or 0) >= 1.0, "done": bool(meta["done"]),
           "raw": meta["raw"], "reason": meta["reason"], "status": outcome.get("status"),
           "result": outcome.get("result", "")[:300], "calls": len(calls),
           "in": sum(c["in"] for c in calls), "out": sum(c["out"] for c in calls),
           "cached": sum(c["cached"] for c in calls), "cost": round(sum(c["cost"] for c in calls), 6),
           "errors": sum(1 for c in calls if c["error"]), "seconds": round(seconds, 1), "cards": cards, "code": CODE,
           "steps": outcome.get("steps", [])}
    detail = {**row, "looks": hands.looks, "answers": [{k: c[k] for k in ("answer", "error", "s")} for c in calls]}
    return row, detail


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, help=".env holding LLM_API_KEY and LLM_BASE_URL")
    parser.add_argument("--model", default="deepseek/deepseek-v4-flash")
    parser.add_argument("--out", default="")
    parser.add_argument("--tasks", default="")
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget", type=float, default=0.38, help="dollars; no new episode past it")
    parser.add_argument("--port", type=int, default=59260)
    parser.add_argument("--data", default=str(DATA))
    args = parser.parse_args(argv)
    env = read_env(Path(args.env))
    slug = args.model.replace("/", "_").replace(":", "_")
    out = Path(args.out or REPO.parent / "ref" / "bench" / "miniwob" / slug).resolve()
    (out / "episodes").mkdir(parents=True, exist_ok=True)
    names = [n for n, _ in TASKS if not args.tasks or n in args.tasks.split(",")]
    seeds = [int(s) for s in args.seeds.split(",")]
    results = out / "results.jsonl"
    have = set()
    if results.exists():
        for line in results.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            have.add((row["task"], row["seed"]))
    todo = [(n, s) for s in seeds for n in names if (n, s) not in have]
    print(f"{len(todo)} episodes to run ({len(have)} already in {results})", flush=True)

    server = serve(Path(args.data), args.port)
    model = Model(env["LLM_BASE_URL"], env["LLM_API_KEY"], args.model, args.budget)
    allowed = gate.Allowed(out)
    queue: asyncio.Queue = asyncio.Queue()
    for item in todo:
        queue.put_nowait(item)
    skipped: list[tuple[str, int]] = []
    tries: dict[tuple[str, int], int] = {}
    lock = asyncio.Lock()
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True)

        async def worker() -> None:
            while not queue.empty():
                name, seed = queue.get_nowait()
                if model.spent >= args.budget:
                    skipped.append((name, seed))
                    continue
                # A context of its own each episode: no history, storage or focus carried from the last task.
                context = await browser.new_context(viewport={"width": 1000, "height": 700})
                try:
                    row, detail = await episode(await context.new_page(), f"http://127.0.0.1:{args.port}", name,
                                                seed, model, allowed)
                except Exception as exc:
                    # The page failed to set up (a script that did not load): tried once more, then reported.
                    tries[(name, seed)] = tries.get((name, seed), 0) + 1
                    again = tries[(name, seed)] < 2
                    if again:
                        queue.put_nowait((name, seed))
                    print(f"  {name} seed {seed}: harness error{' (again later)' if again else ''} "
                          f"{type(exc).__name__}: {str(exc)[:200]}", flush=True)
                    continue
                finally:
                    await context.close()
                async with lock:
                    with results.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    (out / "episodes" / f"{name}-{seed}.json").write_text(
                        json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  {name} seed {seed}: {'OK ' if row['success'] else 'no '} {row['status']:<9} "
                      f"raw={row['raw']} calls={row['calls']} {row['seconds']}s  spent ${model.spent:.4f}", flush=True)

        await asyncio.gather(*(worker() for _ in range(args.workers)))
        await browser.close()
    server.shutdown()
    await model.client.aclose()
    if skipped:
        print(f"budget reached: {len(skipped)} episodes not run: {skipped}", flush=True)
    print(f"spent this run ${model.spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
