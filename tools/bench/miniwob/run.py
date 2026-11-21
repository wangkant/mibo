"""MiniWoB++ as BrowserGym defines it (125 tasks, AgentLab's five seeds each), worked by Mibo as a person works a
page with it: the task's page open in the app's own browser, the goal typed once in a private chat beside the page,
and the app's reply loop doing the rest with its own tools (look, act) in one chat turn. Nothing of the app is
changed; its background rounds (feeds, walks, remarks, memory folds, the public-site probe) are kept idle so every
model call counted is the turn's.

    python -I tools/bench/miniwob/run.py --env <.env with LLM_API_KEY, LLM_BASE_URL> --data <miniwob/html>
        --out <folder> [--model deepseek/deepseek-v4.1-flash] [--tasks all|forty|click-button,...]
        [--repeats 1] [--workers 2] [--budget 0.50] [--ports 61280]

How the run stands in for the person, stated with every result:
- The page is the app's browser with no window: tests/harness/pane.py, a stand-in of browser.Pane over one headless
  Edge, its column beside the page the one Operating tells, at BrowserGym's 332x214 viewport. The task's tab is in
  front, so the turn's look and act work on it as on the page a person has open.
- The message is the task's goal, word for word, sent with the turn choice the chat beside the page sends ("page",
  browse.js paBeside), so the page in front comes looked at.
- Cards: every card of the app's browser is answered yes, this once (never "always"): the person asked for the task
  and the page is the task's own. Cards of the app's other places (commands and files, programs, MCP, switches) are
  answered no: no task needs them. The app's floors stay: a password field is never typed into.
- The episode ends as BrowserGym ends it: when the page's reward fires the turn is stopped as the stop button stops
  it, and the score is what the page held then. A turn past EPISODE_S seconds is stopped too.

The episode is set up as BrowserGym's AbstractMiniwobTask.setup does it: the human display taken off (the goal is not
on the page, only in the task's words), Math.seedrandom(page seed), EPISODE_MAX_TIME 1,000,000 ms,
core.startEpisodeReal(), the goal from core.getUtterance(). It is scored as its validate() does: reward 1 when the
page's raw reward is above 0 and the page is still the task's address. `reward10` is that score when the tenth action
on the page had been made (AgentLab's max_steps 10, one action a step; a Hands action that does something to the
page counts one), `reward` when the turn ended.

The model is measured by the app itself at its start (modelbar, abilities.check), never named in a table. Each worker
is its own process (at most --workers, below-normal priority), with its own home under <out>, the app served in it,
and a counting pass-through (tools/everyday.py's Meter) holding --budget / workers dollars, which refuses calls past
it. The key is read from --env by the parent, handed to the workers in their environment, and reaches the app
through a stand-in of the credential store that reads it from there: nothing of it is written or printed.

Out: <out>/results.jsonl (one line an episode; a rerun skips the episodes already there), <out>/episodes/ (each
episode's reply, steps and the lines of its model calls in <out>/w<k>/model-full.jsonl), <out>/w<k>/log.txt (a
line an episode as it ends), <out>/run.json."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO), str(REPO / "tools"), str(REPO / "tests"), str(HERE)]

from tasks import FORTY, TASKS  # noqa: E402

# The product files this run was made with: a short hash of each.
CODE = {f: hashlib.sha1((REPO / "mibo" / f).read_bytes()).hexdigest()[:10]
        for f in ("loop.py", "surface.py", "panels/browser.py", "web/operate.py", "web/pageops.py", "web/gate.py")}
# BrowserGym's AbstractMiniwobTask: viewport, episode time; AgentLab's DEFAULT_BENCHMARKS["miniwob"]: max_steps.
VIEWPORT = {"width": 332, "height": 214}
EPISODE_MS = 1_000_000
STEPS = 10
EPISODE_S = 420
# Hands actions that do something to the page: one BrowserGym action each (a click with `times` counts its presses).
PAGE_DOS = {"click", "type", "press", "hover", "drag", "scroll", "navigate", "back"}
TOKEN = "miniwob-local-capability"
WINDOW = "miniwob-window"
CARD_PATHS = ("shell", "programs", "mcp", "turnon")
BELOW_NORMAL = 0x00004000
NO_WINDOW = 0x08000000

# BrowserGym's remove_human_display script (browsergym/miniwob/base.py, Apache-2.0, ServiceNow 2024), unchanged:
# the query, reward display, click canvas and cover leave the page and come back only while core reads or ends.
HIDE = r"""
let __display_ids = ['reward-display', 'click-canvas', 'sync-task-cover'];
let __display_divs = {};
let __query_div_hidden_copy = null;

removeDisplay = function() {
  core.clearTimer();
  document.body.removeEventListener('click', core.canvasDrawClick);

  __query_div_hidden_copy = document.getElementById('query').cloneNode(true);
  document.getElementById('query').innerHTML = '';

  for (i in __display_ids) {
    elem_id = __display_ids[i];
    elem = document.getElementById(elem_id);
    elem.remove();
    __display_divs[elem_id] = elem;
  }
};

bringBackDisplay = function() {
  document.getElementById('query').innerHTML = __query_div_hidden_copy.innerHTML;
  for (var elem_id in __display_divs){
    document.body.appendChild(__display_divs[elem_id]);
  }
  core.createDisplay();
};

core.endEpisode_legacy = core.endEpisode;
core.startEpisodeReal_legacy = core.startEpisodeReal;
core.getUtterance_legacy = core.getUtterance;

core.getUtterance = function () {
  bringBackDisplay();
  utterance = core.getUtterance_legacy();
  removeDisplay();
  return utterance;
};

core.endEpisode = function(reward, time_proportional, reason){
  bringBackDisplay();
  core.endEpisode_legacy(reward, time_proportional, reason);
  removeDisplay();
};

core.startEpisodeReal = function() {
  bringBackDisplay();
  core.startEpisodeReal_legacy();
  removeDisplay();
};

removeDisplay();
"""
# The page's reward as core.js keeps it; a page that left the task has none.
ENDED = ("() => typeof WOB_DONE_GLOBAL === 'undefined' ? [false, 0, null] : "
         "[WOB_DONE_GLOBAL, WOB_RAW_REWARD_GLOBAL, WOB_REWARD_REASON]")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    # Pages loading their scripts at once overflow the default backlog of 5 (a script then fails to load).
    request_queue_size = 128
    daemon_threads = True


def serve(root: Path, port: int) -> ThreadingHTTPServer:
    import functools
    server = Server(("127.0.0.1", port), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def read_env(path: Path) -> dict:
    return {k.strip(): v.strip() for k, _, v in (line.partition("=") for line in path.read_text(encoding="utf-8").splitlines())
            if v}


async def setup(page, site: str, name: str, page_seed: int) -> tuple[str, str]:
    """The task's page as BrowserGym's setup leaves it: its address and the goal."""
    url = f"{site}/miniwob/{name}.html"
    await page.goto(url)
    await page.wait_for_function("() => document.readyState === 'complete' && window.core && core.cover_div")
    await page.evaluate(HIDE)
    await page.evaluate(f"() => {{ Math.seedrandom({page_seed}); core.EPISODE_MAX_TIME = {EPISODE_MS}; "
                        f"core.startEpisodeReal(); }}")
    await page.wait_for_function("() => WOB_TASK_READY")
    goal = await page.evaluate("() => core.getUtterance()")
    # A few tasks answer {utterance, fields}; the goal is the utterance alone.
    return url, goal["utterance"] if isinstance(goal, dict) else str(goal)


def verdict(ended: list, at: str, url: str) -> dict:
    """BrowserGym's validate(): reward 1 when the raw reward is above 0 on the task's own address."""
    done, raw, reason = ended
    stayed = at == url
    return {"reward": float(stayed and float(raw or 0) > 0), "done": bool(done), "raw": raw, "reason": reason,
            "stayed": stayed}


async def score(page, url: str) -> dict:
    return verdict(await page.evaluate(ENDED), page.url, url)


# ---------------------------------------------------------------- the app's browser with no window

def pane_class():
    from harness.pane import Pane as Standin

    class Pane(Standin):
        """The stand-in pane, a fresh browsing context for each episode at BrowserGym's viewport."""

        def fresh(self) -> None:
            async def make() -> None:
                await self.context.close()
                self.context = await self._browser.new_context(viewport=VIEWPORT)
            self._call(make)
            self.tabs_, self.front_of, self.op, self.column, self.placed = [], 0, None, [], []
    return Pane


# ---------------------------------------------------------------- the app, served in this process

class App:
    """The app on a scratch home, as its page talks to it. The home's settings.json holds the model's address and
    name; its key comes from this process's environment through a stand-in of the credential store."""

    def __init__(self, home: Path, base: str, model: str, port: int, measure: bool = True):
        import keyring
        import uvicorn

        from everyday import no_windows
        from mibo import paths, settingsfile, situation, welcome
        from mibo.storage import atomic_write_text
        self.home = home
        # The credential store of this run: the key the parent handed over in the environment, nothing written.
        keyring.get_password = lambda service, name: os.environ.get(name) if name == "LLM_API_KEY" else None
        keyring.set_password = keyring.delete_password = lambda *args: None
        settingsfile.write(home, {"LLM_BASE_URL": base, "LLM_MODEL": model, "PERSONA_NAME": "Mibo", "AGENT_LANG": "zh",
                                  "PERSONA_TZ_OFFSET_HOURS": "-8", "ROAM_ENABLED": "false",
                                  "UPDATE_CHECK_ENABLED": "false", "PAGE_PORT": str(port)})
        paths.use_home(home)
        # The person's computer is an empty folder beside the home, the only one the app's file tools may read
        # without asking (as a person grants one in Settings), and the Desktop too: nothing of the computer the
        # run happens on reaches the model.
        from mibo.shell.grants import DIRS_ENV, Grants
        computer = home.parent / "computer"
        computer.mkdir(exist_ok=True)
        # It is the Desktop, and the computer has no other known folder.
        os.environ[DIRS_ENV] = str(computer)
        grants = Grants(home / "runtime" / "desktop", home)
        for folder in grants.folders():
            grants.remove(folder)
        grants.add(str(computer), read_only=True)

        async def nothing(*args, **kwargs) -> None:
            return None
        # Nothing of the app's own beside the turn: no probe of public sites, no feed rounds or their judging, no
        # sharing, remarks, walks or memory folds. The model's own check at the start stays, unless `measure` is
        # False (a stand-in model whose record the caller writes).
        from mibo import consolidate, roam
        from mibo.panels import modelbar, remarks
        from mibo.sources import catalog as sources
        situation.probe = nothing
        sources.Rounds.loop = remarks.Remarks.loop = welcome.Workspace.share_loop = nothing
        roam.Roam.loop = consolidate.Consolidation.loop_memory = nothing
        if not measure:
            modelbar.check_at_start = lambda workspace: None
        no_windows()
        self.app = welcome.create_app(home, TOKEN, workspace=welcome.Workspace(home))
        self.server = uvicorn.Server(uvicorn.Config(self.app, host=welcome.PAGE_HOST, port=port, log_level="warning"))
        sock = welcome._listen(port)
        self.url = f"http://{welcome.PAGE_HOST}:{port}"
        atomic_write_text(home / "runtime" / "desktop" / "welcome.json", json.dumps({"url": f"{self.url}/#token={TOKEN}"}))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        while not self.server.started:
            self.thread.join(0.05)
        self.header = welcome.TOKEN_HEADER
        self.local = threading.local()

    def call(self, method: str, path: str, body: dict | None = None, own: bool = False, timeout: float = 30) -> dict:
        import httpx
        # One kept-alive client a thread: the card watch asks several times a second, and a new socket for each
        # leaves thousands waiting to close.
        client = getattr(self.local, "client", None)
        if client is None:
            client = self.local.client = httpx.Client(trust_env=False)
        headers = {self.header: TOKEN, **({"X-Mibo-Window": WINDOW} if own else {})}
        got = client.request(method, self.url + path, headers=headers, json=body, timeout=timeout)
        return got.json() if got.content else {}

    def show(self, pane) -> None:
        """The pane as the app window's: the person at it, watching."""
        self.app.state.window = SimpleNamespace(pane=pane, show=lambda: None, attended=lambda: True, frame_key=WINDOW,
                                                is_own_page=lambda key: key == WINDOW, notify=lambda text: None)
        # The browser's operating state is made anew with the window, as when the app starts.
        self.app.state.operating = None

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(30)


# ---------------------------------------------------------------- one episode

class Count:
    """The page actions of the episode under way, and the score when the tenth had been made."""
    moves = 0
    at_steps: dict | None = None
    url = ""


def count_actions() -> None:
    """Hands.act observed, not changed: each action that does something to the page counts, and the page is scored
    when the tenth has been made."""
    from mibo.web import operate
    act = operate.Hands.act

    async def counted(self, action: dict) -> dict:
        result = await act(self, action)
        if action.get("do") in PAGE_DOS:
            times = action.get("times")
            Count.moves += int(times) if isinstance(times, int) and times > 1 else 1
            if Count.moves >= STEPS and Count.at_steps is None:
                try:
                    Count.at_steps = verdict(await self.tab.evaluate(ENDED), self.tab.url, Count.url)
                except RuntimeError:
                    # Between documents: the next action's end is scored instead.
                    pass
        return result
    operate.Hands.act = counted


def answer_cards(app: App, cards: list[dict]) -> None:
    """Every card up now answered by the rule at the top."""
    card = app.call("GET", "/api/browser/confirm").get("card")
    if card and all(card["id"] != c["id"] for c in cards):
        cards.append({"id": card["id"], "place": "browser", "yes": True,
                      **{k: str(card.get(k) or "")[:300] for k in ("kind", "button", "to", "text", "what")}})
        app.call("POST", "/api/browser/confirm", {"id": card["id"], "yes": True, "never": False}, own=True)
    for path in CARD_PATHS:
        card = app.call("GET", f"/api/{path}/card").get("card")
        if card and all(card["id"] != c["id"] for c in cards):
            cards.append({"id": card["id"], "place": path, "yes": False,
                          **{k: str(card.get(k) or "")[:300] for k in ("type", "tool", "command", "what")}})
            # A press is taken from the app window's own page only, as for the browser's cards.
            app.call("POST", f"/api/{path}/card", {"id": card["id"], **({"answer": "no"} if path == "mcp" else
                                                                         {"yes": False})}, own=True)


def episode(app: App, pane, site: str, name: str, page_seed: int, meter) -> tuple[dict, dict]:
    pane.fresh()
    app.show(pane)
    ident = pane.open_tab("about:blank")
    page = pane.core_of(ident)
    url, goal = pane._call(lambda: setup(page, site, name, page_seed))
    Count.moves, Count.at_steps, Count.url = 0, None, url
    chat = app.call("POST", "/api/chats", {"private": True})["id"]
    seen = len(meter.rows)
    cards: list[dict] = []
    sent: dict = {}
    ended: dict | None = None
    status = "replied"

    def post() -> None:
        sent["answer"] = app.call("POST", "/api/chat", {"text": goal, "chat": chat, "choices": ["page"]},
                                  timeout=EPISODE_S + 120)
    began = time.monotonic()
    thread = threading.Thread(target=post, daemon=True)
    thread.start()
    while thread.is_alive():
        answer_cards(app, cards)
        if ended is None:
            try:
                now = verdict(pane._call(lambda: page.evaluate(ENDED)), page.url, url)
            except RuntimeError:
                # The page is between documents (a navigation): read again on the next round.
                now = {"done": False}
            if now["done"]:
                # The reward fired: BrowserGym's episode is over, so the turn is stopped as the stop button does.
                ended, status = now, "ended"
                app.call("POST", "/api/chat/stop", {"chat": chat})
        if ended is None and time.monotonic() - began > EPISODE_S:
            status = "timeout"
            app.call("POST", "/api/chat/stop", {"chat": chat})
            thread.join(60)
        thread.join(0.3)
    seconds = round(time.monotonic() - began, 1)
    end = ended or pane._call(lambda: score(page, url))
    answer = sent.get("answer") or {}
    said = [m for m in answer.get("messages") or [] if m.get("role") != "user"]
    reply = str(answer.get("reply") or "\n".join(str(m.get("text") or "") for m in said))
    trace = [{k: str(s.get(k) or "")[:600] for k in ("tool", "status", "what", "out")}
             for m in said for s in m.get("trace") or []]
    rows = meter.rows[seen:]
    app.call("POST", "/api/chats/delete", {"id": chat})
    # A stopped turn lets its pages go from a thread of its own: the next episode waits for that.
    operating = app.app.state.operating
    while operating is not None and operating.places and time.monotonic() - began < seconds + 30:
        time.sleep(0.1)
    row = {"task": name, "utterance": goal, **end, "reward10": (Count.at_steps or end)["reward"], "moves": Count.moves,
           "status": status if answer or status != "replied" else "error", "result": reply[:300], "calls": len(rows),
           "in": sum(r["in"] for r in rows), "out": sum(r["out"] for r in rows),
           "cached": sum(r["cached"] for r in rows), "cost": round(sum(r["cost"] for r in rows), 6),
           "errors": sum(1 for r in rows if r["status"] != 200),
           "tools": [n for r in rows for n, _ in r["called"]], "seconds": seconds, "cards": cards, "code": CODE,
           "lines": [seen, seen + len(rows)]}
    detail = {**row, "reply": reply, "trace": trace, "error": answer.get("error") or ""}
    return row, detail


# ---------------------------------------------------------------- a worker: one process, one app, one browser

def worker(args) -> int:
    from everyday import Meter
    from mibo import installed_browser
    out = Path(args.out).resolve()
    mine = out / f"w{args.worker}"
    home = mine / "home"
    home.mkdir(parents=True, exist_ok=True)
    shard = json.loads(args.shard)
    seeds = {t[0]: (t[2], t[3]) for t in TASKS}
    port = args.ports + 4 * args.worker
    # The meter's lines start after those an earlier run of this worker left, which the episodes' ranges count.
    base = len((mine / "model.jsonl").read_text(encoding="utf-8").splitlines()) if (mine / "model.jsonl").exists() else 0
    meter = Meter(os.environ.pop("BENCH_UPSTREAM"), mine / "model.jsonl", args.budget)
    meter.serve(port + 1)
    server = serve(Path(args.data), port + 2)
    app = App(home, f"http://127.0.0.1:{port + 1}/v1", args.model, port)
    count_actions()
    pane = pane_class().start(installed_browser.find_browser())
    try:
        for name, index in shard:
            if meter.spent >= args.budget:
                print(f"  {name} #{index}: not run, budget reached", flush=True)
                continue
            row, detail = episode(app, pane, f"http://127.0.0.1:{port + 2}", name, seeds[name][1][index], meter)
            if meter.spent >= args.budget:
                # Calls of this episode may have been refused by the budget: it is dropped, never scored.
                print(f"  {name} #{index}: cut by the budget, not scored", flush=True)
                continue
            row = {"index": index, "seed": seeds[name][0][index], "page_seed": seeds[name][1][index],
                   "model": args.model, "worker": args.worker, **row, "lines": [n + base for n in row["lines"]]}
            with (mine / "results.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            (out / "episodes" / f"{name}-{index}.json").write_text(json.dumps({**detail, **row}, ensure_ascii=False,
                                                                              indent=1), encoding="utf-8")
            print(f"  {name} #{index}: {'OK ' if row['reward'] else 'no '} {row['status']:<8} raw={row['raw']} "
                  f"calls={row['calls']} moves={row['moves']} {row['seconds']}s spent ${meter.spent:.4f}", flush=True)
    finally:
        pane.stop()
        app.close()
        server.shutdown()
    print(f"worker {args.worker} spent ${meter.spent:.4f}", flush=True)
    return 0


def merged(out: Path) -> list[dict]:
    """Every episode run so far, from the workers' files, once each (the last run of an episode wins)."""
    rows: dict = {}
    for path in sorted(out.glob("w*/results.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows[(row["task"], row["index"])] = row
    return list(rows.values())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", help=".env holding LLM_API_KEY and LLM_BASE_URL (the parent reads it)")
    parser.add_argument("--data", required=True, help="miniwob-plusplus's miniwob/html folder")
    parser.add_argument("--model", default="deepseek/deepseek-v4.1-flash")
    parser.add_argument("--out", required=True)
    parser.add_argument("--tasks", default="all", help="all (the 125), forty, or names with commas")
    parser.add_argument("--repeats", type=int, default=1, help="the first N of AgentLab's five seeds a task")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--budget", type=float, default=0.50, help="dollars, shared evenly by the workers")
    parser.add_argument("--ports", type=int, default=61280, help="four a worker: app, meter, pages, spare")
    parser.add_argument("--worker", type=int, default=-1, help=argparse.SUPPRESS)
    parser.add_argument("--shard", default="[]", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker >= 0:
        return worker(args)
    out = Path(args.out).resolve()
    (out / "episodes").mkdir(parents=True, exist_ok=True)
    names = {"all": [t[0] for t in TASKS], "forty": list(FORTY)}.get(args.tasks) or args.tasks.split(",")
    have = {(r["task"], r["index"]) for r in merged(out)}
    todo = [(n, i) for i in range(args.repeats) for n in names if (n, i) not in have]
    print(f"{len(todo)} episodes to run ({len(have)} already in {out})", flush=True)
    env = read_env(Path(args.env))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                            text=True).stdout.strip()
    run = {"model": args.model, "date": time.strftime("%Y-%m-%d %H:%M"), "commit": commit, "code": CODE,
           "command": "python -I tools/bench/miniwob/run.py " + " ".join(argv), "workers": args.workers,
           "budget": args.budget}
    runs = json.loads((out / "run.json").read_text(encoding="utf-8")) if (out / "run.json").exists() else []
    runs.append(run)
    (out / "run.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    workers = []
    for k in range(min(args.workers, len(todo))):
        command = [sys.executable, "-I", str(Path(__file__).resolve()), *argv, "--worker", str(k),
                   "--budget", str(args.budget / args.workers), "--shard", json.dumps(todo[k::args.workers])]
        # The key and the upstream reach the worker in its environment only.
        child = {**os.environ, "LLM_API_KEY": env["LLM_API_KEY"], "BENCH_UPSTREAM": env["LLM_BASE_URL"],
                 "PYTHONIOENCODING": "utf-8"}
        (out / f"w{k}").mkdir(exist_ok=True)
        log = (out / f"w{k}" / "log.txt").open("a", encoding="utf-8")
        workers.append(subprocess.Popen(command, cwd=REPO, env=child, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=BELOW_NORMAL | NO_WINDOW if os.name == "nt" else 0))
    for child in workers:
        child.wait()
    rows = merged(out)
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    spent = sum(float(json.loads(line)["cost"]) for path in out.glob("w*/model.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines())
    left = [f"{n}#{i}" for n, i in todo if (n, i) not in {(r["task"], r["index"]) for r in rows}]
    run.update({"episodes": len(todo) - len(left), "not_run": left, "spent": round(spent, 6)})
    (out / "run.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} episodes in {out / 'results.jsonl'}; not run {len(left)}; spent in all ${spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
