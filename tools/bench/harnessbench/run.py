"""Harness-Bench's Standard274 tasks through Mibo itself, without Docker: for each task a fresh home of the app
and a fresh copy of the task's workspace, the task's instruction typed in the chat as a person would type it, the
app's reply loop doing the rest with its own tools, then the benchmark's own scoring (grade.py) of what is left in
the workspace.

    python tools/bench/harnessbench/run.py check --checkout <harness-bench> --work <folder> --python <3.12+ with PyYAML>
    python tools/bench/harnessbench/run.py run --checkout <harness-bench> --work <folder> --python <...> --keys <.env>
                                               [--only 001-meeting-summary,...] [--sample 12 --seed 7]
                                               [--part 1/2] [--port 59711] [--continues 3] [--model haiku]
                                               [--out <json>]

The benchmark runs each harness in a Debian container and grades in another. Here the task runs on this computer
(Windows) and the grader in a process of its own, so only tasks shown to be the same here count. `check` shows it
task by task and writes `<work>/valid.json`: a task is in when it has one prompt and no environment hooks or
services, needs nothing but Python, its untouched workspace does not pass, and its own reference answer laid over
the workspace passes. `run` draws from those.

How the bench stands in for the benchmark's controller and for the person:
- The prompt is the controller's (tools/run_benchmark.py render_prompt): instruction.md and the workspace change
  contract, with /workspace, /runtime and /tmp written as the folders they are here, after one line that names the
  workspace (the container starts the agent in it; a chat has no folder of its own).
- `python3` and `python` are the interpreter given with --python in UTF-8 mode (the container's locale), by two
  command files in a folder put first on the app's PATH; the grader runs in the same mode.
- The tasks are offline and the benchmark's containers have no network: the app reaches nothing past this computer
  (tools/offline.py).
- Questions: a command or a folder inside the task's own folders is answered yes, everything else no.
- A turn of the chat ends at the reply loop's own ceilings (loop.ROUNDS steps, loop.WITHIN_S seconds); the
  benchmark gives a harness the task's whole timeout. When a turn ended at a ceiling the person says "Continue.",
  at most --continues times. Each task's record says how many turns it took.
- The semantic judge is not run (grade.py).

A task whose result is already in `<work>/<task>/result.json` is kept, so a run can be stopped and started again.
When the model service refuses a call (its limit), the task is thrown away and tried again after WAIT_S. `--part k/n`
takes every n-th task from the k-th, and `--port` moves the run's two ports, so several runs share the work."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
_spec = importlib.util.spec_from_file_location("mcpmark_run", HERE.parent / "mcpmark" / "run.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

import scratchhome  # noqa: E402  (mcpmark's run.py put the repo and tools/ on the path)
from everyday import Meter  # noqa: E402

from mibo import loop  # noqa: E402

SUITE = "catalog/standard274.yaml"
# What a task may name as needed: Python itself, parts of its standard library, and the packages the Python given
# with --python has (PyYAML, tzdata, pytest, lxml, python-docx, python-slugify, typing_extensions). Not git, and
# not fork, which Windows has not.
PYTHON_ONLY = {"python", "python3", "json", "sqlite3", "sha256", "datetime", "re", "tarfile", "zoneinfo", "subprocess",
               "json_state_machine", "PyYAML", "pytest", "lxml", "python-docx", "python-slugify", "typing_extensions"}
# Haiku 4.5, dollars per million tokens: input, cached input, output. Used when an answer carries no cost.
PRICE = (1.0, 0.1, 5.0)
GRADE_S = 600
# How long a run waits before trying a task again after the model service refused a call.
WAIT_S = 900


def load(checkout: Path) -> list[dict]:
    import yaml
    ids = yaml.safe_load((checkout / SUITE).read_text(encoding="utf-8"))["task_ids"]
    return [{**yaml.safe_load((checkout / "tasks" / i / "task.yaml").read_text(encoding="utf-8")), "id": i} for i in ids]


def leaves_out(task: dict) -> str:
    """Why a task cannot be run here as the benchmark runs it, or ''."""
    env = task.get("environment") or {}
    if task.get("prompt_files") or task.get("hooks") or env.get("hooks") or env.get("services") or task.get("services"):
        return "rounds, hooks or services of the controller"
    extra = sorted(set(env.get("required_tools") or {}) - PYTHON_ONLY)
    return f"needs {', '.join(extra)}" if extra else ""


def grade(python: Path, *args) -> dict:
    done = subprocess.run([str(python), "-I", "-X", "utf8", str(HERE / "grade.py"), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=GRADE_S, creationflags=base.NO_WINDOW if base.WIN else 0)
    if done.returncode:
        raise RuntimeError(done.stderr.strip()[-400:])
    return json.loads(done.stdout)


def laid(checkout: Path, task: dict, place: Path, python: Path) -> tuple[Path, Path]:
    """The task's workspace copied fresh under `place`, and the file holding its manifest before any work."""
    shutil.rmtree(place, ignore_errors=True)
    workspace = place / "workspace"
    shutil.copytree(checkout / "tasks" / task["id"] / (task.get("workspace_dir") or "workspace"), workspace)
    before = place / "before.json"
    before.write_text(json.dumps(grade(python, "manifest", workspace, checkout)), encoding="utf-8")
    return workspace, before


def check(args) -> int:
    rows = []
    for task in load(args.checkout):
        row = {"task": task["id"], "category": task.get("task_category"), "difficulty": task.get("difficulty"),
               "why_not": leaves_out(task)}
        if not row["why_not"]:
            try:
                workspace, before = laid(args.checkout, task, args.work / "check" / task["id"], args.python)
                if grade(args.python, "score", args.checkout, task["id"], workspace, before)["task_success"]:
                    row["why_not"] = "the untouched workspace passes"
                else:
                    reference = args.checkout / "tasks" / task["id"] / "tests" / "reference"
                    shutil.copytree(reference, workspace, dirs_exist_ok=True)
                    answer = grade(args.python, "score", args.checkout, task["id"], workspace, before)
                    if not answer["task_success"]:
                        row["why_not"] = f"its reference answer scores {answer['weighted_score']} here"
            except Exception as error:
                row["why_not"] = f"{type(error).__name__}: {str(error)[-200:]}"
            shutil.rmtree(args.work / "check" / task["id"], ignore_errors=True)
        rows.append(row)
        print(f"{task['id']}: {row['why_not'] or 'in'}", flush=True)
    (args.work / "valid.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"in: {sum(1 for r in rows if not r['why_not'])} of {len(rows)}")
    return 0


def prompt_of(checkout: Path, task: dict, workspace: Path, runtime: Path, tmp: Path) -> str:
    """The controller's prompt (render_prompt), its three container folders written as the ones here."""
    text = (checkout / "tasks" / task["id"] / (task.get("prompt_file") or "prompt.txt")).read_text(encoding="utf-8")
    text = text.replace("$WORKSPACE", "/workspace")
    contract = task.get("mutation_contract")
    if contract is not None:
        def paths(field: str) -> str:
            return ", ".join(f"`{p}`" for p in contract.get(field) or []) or "none"
        text = (text.rstrip() + "\n\n---\n\n## Enforced workspace change contract\n\n"
                "The controller compares the final state of `/workspace` after every round with that round's starting "
                "state. At the end of the round, only these final-state differences may remain:\n\n"
                f"- Create: {paths('allowed_created')}\n- Modify: {paths('allowed_modified')}\n"
                f"- Delete: {paths('allowed_deleted')}\n\n"
                "Do not leave any other created, modified, or deleted path in `/workspace`; do not leave symlinks, "
                "special files, or undeclared directories there. Put persistent scratch helpers in `/runtime` and "
                "single-round temporary files in `/tmp`.\n")
    for name, folder in (("/workspace", workspace), ("/runtime", runtime), ("/tmp", tmp)):
        text = text.replace(name, str(folder))
    return f"The workspace of this task is the folder `{workspace}`; run its commands there.\n\n{text}"


def one(args, task: dict, model_url: str, key: str, meter: Meter, tools: Path) -> dict:
    place = args.work / task["id"]
    workspace, before = laid(args.checkout, task, place, args.python)
    runtime, tmp, home = place / "runtime", place / "tmp", place / "home"
    runtime.mkdir()
    tmp.mkdir()
    from mibo import setup_wizard
    env = scratchhome.make(home, key=key, LLM_BASE_URL=model_url, LLM_MODEL=args.model, PAGE_PORT=base.PAGE_PORT,
                           AGENT_LANG="en", PERSONA_TZ_OFFSET_HOURS="-8", PERSONA_NAME="Mibo")
    setup_wizard.write_persona(home, setup_wizard.CHARACTERS[0].key, name="Mibo", lang="en")
    env["PATH"] = f"{tools}{os.pathsep}{os.environ['PATH']}"
    theirs = (workspace, runtime, tmp, scratchhome.pc_of(home))
    rows_before, began, turns, cards = len(meter.rows), time.time(), [], []
    app = base.App(home, place / "app.log", env, alone=True)
    try:
        app.api("/api/look/toured", {})
        said = prompt_of(args.checkout, task, workspace, runtime, tmp)
        for _ in range(1 + args.continues):
            calls, started = len(meter.rows), time.time()
            result = base.turn(app, said, theirs)
            cards += result["cards"]
            reply = result["reply"]
            took, used = time.time() - started, len(meter.rows) - calls
            turns.append({"seconds": round(took, 1), "model_calls": used,
                          "reply": str(reply.get("reply") or reply.get("error") or "")[:600]})
            if (used < loop.ROUNDS and took < loop.WITHIN_S - 5) or time.time() - began > task.get("timeout_sec", 600):
                break
            said = "Continue."
    finally:
        app.close()
    result = grade(args.python, "score", args.checkout, task["id"], workspace, before)
    rows = meter.rows[rows_before:]
    record = {
        "task": task["id"], "category": task.get("task_category"), "difficulty": task.get("difficulty"),
        "pass": bool(result["task_success"]), "weighted_score": result["weighted_score"],
        "cases": {c["id"]: bool(c["pass"]) for c in result["checks"]},
        "failed_gates": result.get("failed_gates"), "failed_contract_gates": result.get("failed_contract_gates"),
        "judge_not_run": result["judge_not_run"],
        "seconds": round(time.time() - began, 1), "turns": turns, "model_calls": len(rows),
        "tokens_in": sum(r["in"] for r in rows), "tokens_out": sum(r["out"] for r in rows),
        "refused_by_meter": sum(1 for r in rows if r["status"] == 429),
        "cards": len(cards), "cards_no": [c["what"][:160] for c in cards if c["answer"] == "no"],
    }
    (place / "result.json").write_text(json.dumps({**record, "grade": result, "cards_shown": cards}, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")
    scratchhome.clear(home)
    return record


def run(args) -> int:
    every = {t["id"]: t for t in load(args.checkout)}
    valid = [r["task"] for r in json.loads((args.work / "valid.json").read_text(encoding="utf-8")) if not r["why_not"]]
    if args.only:
        wanted = [i for i in args.only.split(",") if i in valid]
    else:
        wanted = sorted(random.Random(args.seed).sample(valid, args.sample)) if args.sample else valid
    if args.part:
        k, n = map(int, args.part.split("/"))
        wanted = wanted[k - 1::n]
    base.METER_PORT, base.PAGE_PORT = args.port, args.port + 1
    keys = scratchhome.keys(args.keys)
    meter = Meter(keys["LLM_BASE_URL"], args.work / f"model-{args.port}.jsonl", args.budget, PRICE)
    meter.serve(base.METER_PORT)
    tools = args.work / "bin"
    tools.mkdir(parents=True, exist_ok=True)
    for name in ("python", "python3"):
        (tools / f"{name}.cmd").write_text(f'@"{args.python}" -X utf8 %*\r\n', encoding="utf-8")
    out = args.out or args.work / "results.json"
    results = []
    for task_id in wanted:
        kept = args.work / task_id / "result.json"
        if kept.exists():
            record = json.loads(kept.read_text(encoding="utf-8"))
            results.append({k: v for k, v in record.items() if k not in ("grade", "cards_shown")})
            continue
        print(f"{task_id} ...", flush=True)
        while True:
            try:
                record = one(args, every[task_id], f"http://127.0.0.1:{base.METER_PORT}/v1", keys["LLM_API_KEY"], meter,
                             tools)
            except Exception as error:
                record = {"task": task_id, "pass": False, "error": f"{type(error).__name__}: {str(error)[:300]}"}
            if not record.get("refused_by_meter"):
                break
            kept.unlink()
            print(f"  the model service refused a call: waiting {WAIT_S} s", flush=True)
            time.sleep(WAIT_S)
        results.append(record)
        print(f"  {'PASS' if record['pass'] else 'fail'} score {record.get('weighted_score')} {record.get('seconds')}s "
              f"turns {len(record.get('turns') or [])} calls {record.get('model_calls')} cards {record.get('cards')}",
              flush=True)
        out.write_text(json.dumps({
            "benchmark": "Harness-Bench Standard274, tasks valid on this computer (see valid.json), no semantic judge",
            "model": args.model, "commit": base.git("rev-parse", "--short", "HEAD"),
            "checkout_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=args.checkout,
                                              capture_output=True, text=True).stdout.strip(),
            "command": " ".join(["python", "tools/bench/harnessbench/run.py", *sys.argv[1:]]),
            "valid_tasks": len(valid), "seed": args.seed, "passed": sum(1 for r in results if r["pass"]),
            "mean_score": round(sum(r.get("weighted_score") or 0 for r in results) / len(results), 4),
            "full_credit": sum(1 for r in results if r.get("weighted_score") == 1 and r["pass"]),
            "ran": len(results), "of": len(wanted), "tasks": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"passed {sum(1 for r in results if r['pass'])} of {len(results)}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="run.py")
    sub = parser.add_subparsers(dest="what", required=True)
    for name in ("check", "run"):
        p = sub.add_parser(name)
        p.add_argument("--checkout", type=Path, required=True)
        p.add_argument("--work", type=Path, required=True)
        p.add_argument("--python", type=Path, required=True)
        if name == "run":
            p.add_argument("--keys", type=Path, required=True)
            p.add_argument("--budget", type=float, default=1000.0)
            p.add_argument("--port", type=int, default=base.METER_PORT)
            p.add_argument("--part", default="")
            p.add_argument("--model", default="haiku")
            p.add_argument("--only", default="")
            p.add_argument("--sample", type=int, default=0)
            p.add_argument("--seed", type=int, default=7)
            p.add_argument("--continues", type=int, default=3)
            p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)
    return check(args) if args.what == "check" else run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
