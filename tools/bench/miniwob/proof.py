"""Shows run.py's set-up, its driving of the app and its scoring are faithful before any of its numbers counts. No
real model is called.

    python -I tools/bench/miniwob/proof.py --data <miniwob/html> --out <folder> [--ports 61300]

1. Untouched: every one of the 125 tasks set up as run.py sets it up (its first AgentLab seed) and scored at
   once: reward 0 and not done, as BrowserGym's test_validate_teardown asks.
2. BrowserGym's own reference solutions (tests/miniwob: test_cheat of click-scroll-list, click-menu-2 and
   use-colorwheel-2, seeds 0-4) through run.setup and run.score: reward 1. A wrong answer on the same pages
   (another option, another colour, another item): reward 0.
3. The app as run.py drives it (run.episode: the page in the app's browser, the goal sent in a private chat, the
   cards answered by the rule), with a scripted stand-in for the model behind the same counting pass-through: in
   the reply loop it reads the page in front that came looked at, calls act once with the right answer (reward
   1) or a wrong one (reward 0), then replies; `idle` replies in words alone and acts on nothing (reward 0);
   `command` asks for a command off the page, whose card the bench must answer no at once (reward 0, the turn over
   in well under a minute). On click-button, enter-text and click-scroll-list.
The verdicts go to <out>/proof.json and are printed."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run  # noqa: E402
from tasks import TASKS  # noqa: E402

# np.random.RandomState(s).randint(0, 1000000) for s in 0..4: the page seeds of gym's reset(seed=s).
TEST_SEEDS = [985772, 128037, 875688, 71530, 991406]
ICONS = {"Save": "ui-icon-disk", "Prev": "ui-icon-seek-start", "Stop": "ui-icon-stop", "Play": "ui-icon-play",
         "Next": "ui-icon-seek-end", "Zoom In": "ui-icon-zoomin", "Zoom Out": "ui-icon-zoomout"}


async def hidden(page) -> str:
    """The query as the task drew it, before the human display was taken off (run.HIDE keeps a copy and brings it back)."""
    return await page.evaluate("() => { bringBackDisplay(); const drawn = document.getElementById('query')"
                               ".innerHTML; removeDisplay(); return drawn; }")


async def cheat(page, name: str, goal: str, right: bool) -> None:
    """BrowserGym's test_cheat actions for the task, or the same with a wrong answer. Its tests read the icon and
    the colour from the goal; at BrowserGym's pinned MiniWoB commit the goal is the query's text, which drops the
    icon and the swatch, so they are read from the query as drawn."""
    if name == "click-scroll-list":
        options = re.match("Select (.+) from the scroll list and click Submit.", goal).group(1).split(", ")
        if not right:
            options = [await page.evaluate("(o) => [...document.querySelectorAll('#options option')]"
                                           ".map((e) => e.textContent).find((t) => !o.includes(t))", options)]
        await page.locator("#options").select_option(options)
        await page.get_by_role("button", name="Submit").click()
    elif name == "click-menu-2":
        label = re.match('Click the "Menu" button, and then find and click on the item labeled "(.+)".', goal)
        icon = ICONS[label.group(1)] if label else re.search(r"ui-icon (ui-icon-[\w-]+)", await hidden(page)).group(1)
        if not right:
            icon = next(i for i in ICONS.values() if i != icon and i in ("ui-icon-disk", "ui-icon-zoomin"))
        await page.get_by_text("Menu").click()
        if icon in ("ui-icon-seek-start", "ui-icon-stop", "ui-icon-play", "ui-icon-seek-end"):
            await page.get_by_text("Playback").click()
        await page.locator(f".{icon}").click()
    else:
        color = re.search(r"background-color: ?#([0-9a-fA-F]{6})", await hidden(page)).group(1)
        await page.locator("#col").fill(color.upper() if right else ("000000" if color.upper() != "000000"
                                                                     else "FFFFFF"))
        await page.get_by_role("button", name="Submit").click()


class StandIn:
    """An OpenAI-compatible stand-in for the model. In the reply loop (a request offering act) it answers the task
    set in `task` and `mode` ("right", "wrong", "idle", "command") from the page in front that came looked at: one
    act call, then a reply in words; "command" runs a command off the page instead, whose card the bench answers
    no. Every other call (the reviewer, a read) gets "OK"."""

    def __init__(self, port: int):
        self.task, self.mode = "", "idle"
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send(json.dumps({"data": [{"id": "stub"}]}).encode())

            def do_POST(self):
                sent = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                message = stand_in.answer(sent)
                self.send(json.dumps({"id": "stub", "object": "chat.completion", "model": "stub",
                                      "choices": [{"index": 0, "message": message, "finish_reason":
                                                   "tool_calls" if message.get("tool_calls") else "stop"}],
                                      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode())

            def send(self, body: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def answer(self, sent: dict) -> dict:
        names = [t.get("function", {}).get("name") for t in sent.get("tools") or []]
        if "act" not in names:
            return {"role": "assistant", "content": "OK"}
        messages = sent.get("messages") or []
        last = max(n for n, m in enumerate(messages) if m.get("role") == "user")
        acted = any(c["function"]["name"] == "act" for m in messages[last:] for c in m.get("tool_calls") or [])
        looked = [str(m.get("content") or "") for m in messages[last:] if m.get("role") == "tool"]
        if self.mode == "command":
            # Off the page: a command outside the folders the home grants, whose card the bench answers no.
            if any(c["function"]["name"] == "use_computer" for m in messages[last:] for c in m.get("tool_calls") or []):
                return {"role": "assistant", "content": "好的。"}  # copy: voice
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "cmd_0", "type": "function", "function": {"name": "use_computer", "arguments": json.dumps(
                    {"command": r"Get-ChildItem C:\Windows", "seconds": 30})}}]}
        if self.mode == "idle" or acted or not looked:
            return {"role": "assistant", "content": "好的。"}  # copy: voice
        steps = self.steps(str(messages[last].get("content") or ""), looked[-1])
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "act_0", "type": "function", "function": {"name": "act", "arguments": json.dumps({"steps": steps})}}]}

    def steps(self, said: str, page: str) -> list[dict]:
        """The task's steps by the refs on the page: right, or wrong on purpose."""
        right = self.mode == "right"
        refs = {m.group(3): int(m.group(1)) for m in re.finditer(r'\[(\d+)\] (button|option) "([^"]+)"', page)}
        box = int(re.search(r"\[(\d+)\] (?:textbox|listbox)", page).group(1))
        if self.task == "click-button":
            want = re.search(r'"(.+)" button', said).group(1)
            pick = want if right else next(k for k in refs if k != want)
            return [{"do": "click", "ref": refs[pick], "what": pick}]
        if self.task == "enter-text":
            word = re.search(r'Enter "(.+)" into', said).group(1)
            return [{"do": "type", "ref": box, "text": word if right else word + "x", "what": "type"},
                    {"do": "click", "ref": refs["Submit"], "what": "Submit"}]
        options = re.search(r"Select (.+) from the scroll list", said).group(1).split(", ")
        chosen = options if right else [next(k for k in refs if k not in options and k != "Submit")]
        return [{"do": "select_option", "ref": box, "values": chosen, "what": "select"},
                {"do": "click", "ref": refs["Submit"], "what": "Submit"}]


async def pages(data: Path, port: int) -> dict:
    """Parts 1 and 2: run.setup and run.score on plain headless pages, no app."""
    from playwright.async_api import async_playwright
    site = f"http://127.0.0.1:{port}"
    verdicts: dict = {"untouched": {}, "reference": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True)

        async def fresh(name: str, seed: int):
            context = await browser.new_context(viewport=run.VIEWPORT)
            page = await context.new_page()
            url, goal = await run.setup(page, site, name, seed)
            return context, page, url, goal

        for name, _, _, page_seeds in TASKS:
            try:
                context, page, url, goal = await fresh(name, page_seeds[0])
                verdicts["untouched"][name] = await run.score(page, url)
                await context.close()
            except Exception as exc:
                verdicts["untouched"][name] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        for name in ("click-scroll-list", "click-menu-2", "use-colorwheel-2"):
            for seed in TEST_SEEDS:
                for right in (True, False):
                    context, page, url, goal = await fresh(name, seed)
                    await cheat(page, name, goal, right)
                    verdicts["reference"].append({"task": name, "seed": seed, "right": right,
                                                  **await run.score(page, url)})
                    await context.close()
        await browser.close()
    return verdicts


def app_runs(out: Path, data: Path, ports: int) -> list[dict]:
    """Part 3: run.episode on the app with the stand-in model, behind the same Meter as a real run."""
    from everyday import Meter

    from mibo import abilities, installed_browser
    from mibo.endpoints import chat_completions_url
    from mibo.storage import atomic_write_text
    home = out / "home"
    home.mkdir(parents=True, exist_ok=True)
    model = StandIn(ports + 3)
    meter = Meter(f"http://127.0.0.1:{ports + 3}/v1", out / "model.jsonl", 1.0)
    meter.serve(ports + 1)
    base = f"http://127.0.0.1:{ports + 1}/v1"
    # The stand-in's record as the app's check would keep it for a model with tool calls and no pictures.
    url = chat_completions_url(base)
    atomic_write_text(home / "runtime" / abilities.FILE, json.dumps({"models": {abilities.key_of(url, "stub"): {
        "url": url, "model": "stub", "at": time.time(), "tools": "yes", "pictures": "no", "json": "yes",
        "thinking": "no", "context": 131072, "quirks": []}}}))
    # The stand-in takes any key; the app reads it from the environment as in a real run.
    os.environ["LLM_API_KEY"] = "stub"
    app = run.App(home, base, "stub", ports, measure=False)
    run.count_actions()
    server = run.serve(data, ports + 2)
    pane = run.pane_class().start(installed_browser.find_browser())
    found = []
    try:
        for name in ("click-button", "enter-text", "click-scroll-list"):
            for seed in TEST_SEEDS[:2]:
                for mode in ("right", "wrong", "idle", "command"):
                    model.task, model.mode = name, mode
                    row, detail = run.episode(app, pane, f"http://127.0.0.1:{ports + 2}", name, seed, meter)
                    found.append({"task": name, "seed": seed, "mode": mode,
                                  **{k: row[k] for k in ("reward", "reward10", "raw", "status", "calls", "moves",
                                                         "cards", "tools", "seconds")}, "trace": detail["trace"]})
                    print(f"  {name} {seed} {mode}: reward {row['reward']} raw {row['raw']} {row['status']} "
                          f"tools {row['tools']} cards {len(row['cards'])}", flush=True)
    finally:
        pane.stop()
        app.close()
        server.shutdown()
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ports", type=int, default=61300, help="app, meter, pages, stand-in model")
    parser.add_argument("--parts", default="pages,app")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    verdicts: dict = {}
    if "pages" in args.parts:
        server = run.serve(Path(args.data), args.ports + 2)
        verdicts.update(asyncio.run(pages(Path(args.data), args.ports + 2)))
        server.shutdown()
        server.server_close()
    if "app" in args.parts:
        verdicts["app"] = app_runs(out, Path(args.data), args.ports)
    summary = {}
    if "untouched" in verdicts:
        untouched = verdicts["untouched"]
        summary.update({
            "untouched_zero": sum(1 for v in untouched.values() if v.get("reward") == 0 and v.get("done") is False),
            "untouched_of": len(untouched),
            "untouched_off": {k: v for k, v in untouched.items() if not (v.get("reward") == 0 and v.get("done") is False)},
            "reference_right": sum(1 for v in verdicts["reference"] if v["right"] and v["reward"] == 1),
            "reference_wrong_zero": sum(1 for v in verdicts["reference"] if not v["right"] and v["reward"] == 0),
            "reference_of_each": len(verdicts["reference"]) // 2})
    if "app" in verdicts:
        for mode, want in (("right", 1), ("wrong", 0), ("idle", 0), ("command", 0)):
            runs = [v for v in verdicts["app"] if v["mode"] == mode]
            summary[f"app_{mode}_scores_{want}"] = f"{sum(1 for v in runs if v['reward'] == want)}/{len(runs)}"
        runs = [v for v in verdicts["app"] if v["mode"] == "command"]
        summary["app_command_card_answered_no_within_60s"] = (
            f"{sum(1 for v in runs if v['seconds'] < 60 and any(c['place'] == 'shell' and not c['yes'] for c in v['cards']))}"
            f"/{len(runs)}")
    verdicts["summary"] = summary
    (out / "proof.json").write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
