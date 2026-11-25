"""The same Harness-Bench tasks through Claude Code itself with the same model, on this computer: what Mibo's
numbers are read against, since the published runs used other models and Debian containers.

    python tools/bench/harnessbench/claudecode.py --checkout <harness-bench> --work <folder> --python <3.12+ with PyYAML>
                                                  --valid <valid.json of run.py's check> [--only <ids>]
                                                  [--sample 16 --seed 7] [--model haiku] [--workers 2]

Each task gets a fresh copy of its workspace, the prompt run.py gives the app (prompt_of), and `claude -p` started
in the workspace with none of this computer's own settings, memory, hooks or MCP servers (--setting-sources "",
--strict-mcp-config). It may read and edit files and run the commands in ALLOWED (Python, as run.py gives it, and
the shell's reading and file commands); the web tools and subagents are off, as the tasks are offline. The result
is scored by grade.py, as the app's is."""
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("hb_run", HERE / "run.py")
hb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hb)

COMMANDS = ("python3", "python", "ls", "cat", "head", "tail", "grep", "find", "wc", "diff", "sort", "uniq", "echo",
            "mkdir", "cp", "mv", "sed", "awk", "sha256sum", "pwd", "cd", "test", "true", "file", "stat", "cut", "tr")
ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", *(f"Bash({name}:*)" for name in COMMANDS)]
OFF = ["WebFetch", "WebSearch", "Agent", "Task", "PowerShell", "NotebookEdit"]
TURNS = 200
# The longest a task is given here, whatever its own timeout.
WITHIN_S = 1800


def one(args, task: dict, tools: Path) -> dict:
    place = args.work / task["id"]
    workspace, before = hb.laid(args.checkout, task, place, args.python)
    runtime, tmp = place / "runtime", place / "tmp"
    runtime.mkdir()
    tmp.mkdir()
    prompt = hb.prompt_of(args.checkout, task, workspace, runtime, tmp)
    command = ["claude", "-p", "--model", args.model, "--setting-sources", "", "--strict-mcp-config",
               "--permission-mode", "acceptEdits", "--add-dir", str(runtime), str(tmp), "--max-turns", str(TURNS),
               "--output-format", "json", "--allowedTools", *ALLOWED, "--disallowedTools", *OFF]
    began = time.time()
    try:
        done = subprocess.run(command, input=prompt.encode("utf-8"), capture_output=True, cwd=workspace, shell=False,
                              timeout=min(task.get("timeout_sec", 600), WITHIN_S),
                              # With no settings read, Claude Code on Windows is told where its shell is.
                              env={**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
                                   "CLAUDE_CODE_GIT_BASH_PATH": args.bash},
                              creationflags=hb.base.NO_WINDOW if hb.base.WIN else 0)
        said = json.loads(done.stdout.decode("utf-8", "replace") or "{}")
    except subprocess.TimeoutExpired:
        said = {"result": "(no answer within the time)", "timed_out": True}
    result = hb.grade(args.python, "score", args.checkout, task["id"], workspace, before)
    usage = said.get("usage") or {}
    record = {
        "task": task["id"], "category": task.get("task_category"), "difficulty": task.get("difficulty"),
        "pass": bool(result["task_success"]), "weighted_score": result["weighted_score"],
        "cases": {c["id"]: bool(c["pass"]) for c in result["checks"]},
        "seconds": round(time.time() - began, 1), "turns": said.get("num_turns"), "timed_out": bool(said.get("timed_out")),
        "tokens_in": sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
        "tokens_out": usage.get("output_tokens", 0),
        "denied": [str(d.get("tool_input", ""))[:160] for d in said.get("permission_denials") or []],
        "reply": str(said.get("result") or "")[:600],
    }
    (place / "result.json").write_text(json.dumps({**record, "grade": result}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return record


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="claudecode.py")
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--valid", type=Path, required=True, help="valid.json, as run.py's check wrote it")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--only", default="")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--bash", default=shutil.which("bash") or "", help="Git Bash, on Windows")
    args = parser.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)
    every = {t["id"]: t for t in hb.load(args.checkout)}
    valid = [r["task"] for r in json.loads(args.valid.read_text(encoding="utf-8")) if not r["why_not"]]
    if args.only:
        wanted = [i for i in args.only.split(",") if i in valid]
    else:
        wanted = sorted(random.Random(args.seed).sample(valid, args.sample)) if args.sample else valid
    tools = args.work / "bin"
    tools.mkdir(exist_ok=True)
    for name in ("python", "python3"):
        # Claude Code's shell here is Git Bash, which runs a script with no extension; cmd runs the other.
        (tools / name).write_bytes(f'#!/bin/sh\nexec "{args.python.as_posix()}" -X utf8 "$@"\n'.encode())
        (tools / f"{name}.cmd").write_text(f'@"{args.python}" -X utf8 %*\r\n', encoding="utf-8")

    def run(task_id: str) -> dict:
        kept = args.work / task_id / "result.json"
        if kept.exists():
            record = json.loads(kept.read_text(encoding="utf-8"))
            return {k: v for k, v in record.items() if k != "grade"}
        try:
            record = one(args, every[task_id], tools)
        except Exception as error:
            record = {"task": task_id, "pass": False, "error": f"{type(error).__name__}: {str(error)[:300]}"}
        print(f"{task_id}: {'PASS' if record['pass'] else 'fail'} score {record.get('weighted_score')} "
              f"{record.get('seconds')}s turns {record.get('turns')} denied {len(record.get('denied') or [])}", flush=True)
        return record
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(run, wanted))
    (args.work / "results.json").write_text(json.dumps({
        "benchmark": "Harness-Bench Standard274 through Claude Code, tasks valid on this computer, no semantic judge",
        "model": args.model, "claude_code": subprocess.run(["claude", "--version"], capture_output=True, text=True,
                                                           shell=hb.base.WIN).stdout.strip(),
        "passed": sum(1 for r in results if r["pass"]),
        "mean_score": round(sum(r.get("weighted_score") or 0 for r in results) / len(results), 4),
        "full_credit": sum(1 for r in results if r.get("weighted_score") == 1 and r["pass"]),
        "ran": len(results), "tasks": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"passed {sum(1 for r in results if r['pass'])} of {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
