"""Two checks of working a window by picture (mibo/see), with no window and no model.

    python tools/sight_check.py [--tree DIR]

1. Who gets picture mode. For a window that can only be worked by picture, the route the app takes for each of
   fifteen models: picture-taking models in the measured table, picture-taking models outside it, and one that
   takes no pictures. Each model's abilities are given as the app's check would have measured them.
2. When "done" is taken. Six answer patterns seen in the picture runs of 2026-11-19 are replayed through the
   picture loop (see/run.py) over a stand-in window whose picture changes only where an action is scripted to
   change it. A "done" for a task that was not done is a false done.

`--tree` checks another copy of the package (an earlier one, for a before and after).
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path

from PIL import Image

MODELS = (
    # In the measured table.
    "qwen/qwen3.7-flash", "deepseek/deepseek-v4.1-flash", "z-ai/glm-5.3-flash", "anthropic/claude-haiku-5.5",
    "openai/gpt-6-luna", "bytedance/ui-tars-1.5-7b",
    # Not measured here, though they take pictures.
    "google/gemini-3-flash", "qwen/qwen3-vl-plus", "openai/gpt-6-mini", "mistralai/pixtral-large-2611",
    "meta-llama/llama-5-scout", "moonshotai/kimi-vl-a3b", "x-ai/grok-5-fast", "minimax/minimax-vl-02",
)
BLIND = "deepseek/deepseek-chat-v4"

# Each pattern: the scripted answers, in order, and whether the task was really done at the end.
PATTERNS = {
    "D1 done at the first look, nothing done (deepseek, puzzle, 3 of 3)": (
        [{"actions": [{"do": "done", "success": True, "result": "拼图已完成"}]}] * 4, False),
    "D2 a click that changed nothing, done in the same reply": (
        [{"actions": [{"do": "click", "x": 300, "y": 200, "target": "the red colour"},
                      {"do": "done", "success": True, "result": "已选红色"}]}]
        + [{"actions": [{"do": "done", "success": True, "result": "已选红色"}]}] * 3, False),
    "D3 a drag off the handle that moved nothing, then done (qwen, slider)": (
        [{"actions": [{"do": "drag", "x": 100, "y": 300, "to_x": 400, "to_y": 300, "target": "the slider"}]}]
        + [{"actions": [{"do": "done", "success": True, "result": "音量已调到 75"}]}] * 3, False),
    "D4 a drag that drew, done in the same reply": (
        [{"actions": [{"do": "drag", "x": 100, "y": 300, "to_x": 400, "to_y": 300, "target": "moves: a line"},
                      {"do": "done", "success": True, "result": "已画好一条线"}]}]
        + [{"actions": [{"do": "done", "success": True, "result": "已画好一条线"}]}] * 3, True),
    "D5 a drag that drew, then done after the next look": (
        [{"actions": [{"do": "drag", "x": 100, "y": 300, "to_x": 400, "to_y": 300, "target": "moves: a line"}]},
         {"actions": [{"do": "done", "success": True, "result": "已画好一条线"}]}], True),
    "D6 a question about what the window shows, answered at the first look": (
        [{"actions": [{"do": "done", "success": True, "result": "弹窗写着：更新已完成"}]}] * 4, None),
}


class Window:
    """A stand-in picture surface: the picture changes only after an action whose target says it moves."""

    def __init__(self, frame_type, prof):
        self.frame_type, self.profile = frame_type, prof
        self.surface = type("S", (), {"name": "画板"})()
        self.changed = False

    def held(self) -> str:
        return ""

    def frame(self):
        image = Image.new("RGB", (1000, 700), (250, 250, 250) if not self.changed else (240, 240, 240))
        return self.frame_type(image=image, kind="window", origin=(0.0, 0.0), k=1.0, real=(1000, 700))

    async def look(self):
        return self.frame()

    async def act(self, a: dict) -> dict:
        moved = str(a.get("target", "")).startswith("moves")
        self.changed = self.changed or moved
        said = "the picture changed where it pointed" if moved else "no visible change in the picture"
        return {"status": "ok", "line": f"[ok] {a['do']} was sent -> {said}", "changed": moved}


def gate(when, profile) -> list[dict]:
    """The route for a window with nothing named and one drawn area over all of it."""
    params = inspect.signature(when.decide).parameters
    rows = []
    for model in (*MODELS, BLIND):
        takes = model != BLIND
        if "eyes" in params:
            # Now: the check measured pictures, and its self-test read the pointing ("px" here).
            eyes = profile.reach("yes" if takes else "no", "px" if takes else "")
            first = when.decide(named=0, drawn=1.0, eyes=eyes)[0]
            # No switch any more: picture mode starts with one card in the chat.
            rows.append({"model": model, "default": first, "switched_on": first, "card": first != "handback"})
        else:
            # Before: pictures only with the Settings switch on and a model the table marks known.
            sees = takes and profile.profile(model).known
            rows.append({"model": model,
                         "default": when.decide(named=0, drawn=1.0, sees=sees, switched_on=False)[0],
                         "switched_on": when.decide(named=0, drawn=1.0, sees=sees, switched_on=True)[0]})
    return rows


async def replay(run, frame_type, profile) -> list[dict]:
    rows = []
    for name, (answers, really) in PATTERNS.items():
        window = Window(frame_type, profile.profile("anthropic/claude-haiku-5.5"))
        script = iter(answers)

        async def ask_model(system: str, messages: list[dict]) -> str:
            return json.dumps(next(script, {"actions": [{"do": "done", "success": False, "result": "end"}]}))
        out = await run.run(ask_model, window, "按任务操作")
        done = out["status"] == "done"
        rows.append({"pattern": name, "status": out["status"], "calls": out["calls"], "result": out["result"],
                     "false_done": done and really is False})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tree", default="")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.tree).resolve() if args.tree else Path(__file__).resolve().parents[1]))
    from mibo.see import frame, profile, run, when
    print(f"package: {Path(when.__file__).parents[1]}")
    rows = gate(when, profile)
    print("\n1. a window only a picture can work: the route, by model")
    for row in rows:
        print(f"  {row['model']:34} default: {row['default']:9} with the Settings switch on: {row['switched_on']:9}"
              f"{'  (after one card in the chat)' if row.get('card') else ''}")
    takes = [r for r in rows if r["model"] != BLIND]
    print(f"  picture-taking models worked by picture: {sum(r['default'] == 'sight' for r in takes)}/{len(takes)} "
          f"by default, {sum(r['switched_on'] == 'sight' for r in takes)}/{len(takes)} with the switch on")
    done = asyncio.run(replay(run, frame.Frame, profile))
    print("\n2. done in picture mode")
    for row in done:
        print(f"  {row['pattern'][:72]:72} -> {row['status']:9} calls={row['calls']}"
              f"{'  FALSE DONE' if row['false_done'] else ''}")
    print(f"  false dones: {sum(r['false_done'] for r in done)} of {sum(1 for p in PATTERNS.values() if p[1] is False)}"
          f" patterns where nothing was done; calls in all: {sum(r['calls'] for r in done)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
