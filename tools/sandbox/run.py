"""Start a sandbox run on GitHub's hosted runners, wait for it, fetch its logs and pictures, print the table.

    python tools/sandbox/run.py start [--suites pet,pane] [--systems windows,linux] [--ref main] --into <folder>
    python tools/sandbox/run.py fetch <run id> --into <folder>
    python tools/sandbox/run.py table <folder>

`start` dispatches .github/workflows/sandbox.yml with the GitHub CLI (gh, signed in, run from a checkout), waits
until the run ends, downloads each system's artifact into <folder>/sandbox-<system> and prints the table of feature
by system. The runners use stand-in models only: no model key is kept on GitHub. Nothing runs on this computer: no
window, no pointer.
`table` reads every result.json under a folder (fetched, or a suite's own --out) and prints one table per suite.
The exit code is 0 when every check passed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SYSTEMS = ("windows", "linux", "macos")


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def table(folder: Path) -> int:
    """One markdown table per suite, feature by system; 0 when nothing failed."""
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.rglob("result.json"))]
    if not results:
        print(f"no result.json under {folder}")
        return 1
    from _suite import state_text

    failed = 0
    for suite in dict.fromkeys(r["suite"] for r in results):
        mine = {r["system"]: r for r in results if r["suite"] == suite}
        systems = [s for s in SYSTEMS if s in mine]
        features = list(dict.fromkeys(f for r in mine.values() for f in r["features"]))
        print(f"\n### {suite}\n")
        print("| feature | " + " | ".join(systems) + " |")
        print("|---|" + "---|" * len(systems))
        for feature in features:
            cells = []
            for system in systems:
                row = mine[system]["features"].get(feature)
                cells.append(state_text(row) if row else "")
                failed += bool(row and row["state"] == "fails")
            print(f"| {feature} | " + " | ".join(cells) + " |")
    return 1 if failed else 0


def fetch(run: str, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "run", "download", run, "--dir", str(into)], check=False)


def start(args) -> int:
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gh("workflow", "run", "sandbox.yml", "--ref", args.ref, "-f", f"suites={args.suites}", "-f",
       f"systems={args.systems}")
    run = ""
    for _ in range(60):
        rows = json.loads(gh("run", "list", "--workflow", "sandbox.yml", "--branch", args.ref, "--event",
                             "workflow_dispatch", "--limit", "5", "--json", "databaseId,createdAt"))
        mine = [r for r in rows if r["createdAt"] >= since]
        if mine:
            run = str(mine[-1]["databaseId"])
            break
        time.sleep(5)
    if not run:
        print("the run did not show up")
        return 1
    print(f"run {run}: https://github.com/{gh('repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner').strip()}"
          f"/actions/runs/{run}", flush=True)
    while json.loads(gh("run", "view", run, "--json", "status"))["status"] != "completed":
        time.sleep(30)
    print("conclusion:", json.loads(gh("run", "view", run, "--json", "conclusion"))["conclusion"])
    fetch(run, args.into)
    return table(args.into)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    s = sub.add_parser("start")
    s.add_argument("--suites", default="window,firstrun,pet,pane,programs")
    s.add_argument("--systems", default=",".join(SYSTEMS))
    s.add_argument("--ref", default="main")
    s.add_argument("--into", type=Path, required=True)
    f = sub.add_parser("fetch")
    f.add_argument("run")
    f.add_argument("--into", type=Path, required=True)
    t = sub.add_parser("table")
    t.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    if args.what == "start":
        return start(args)
    if args.what == "fetch":
        fetch(args.run, args.into)
        return table(args.into)
    return table(args.folder)


if __name__ == "__main__":
    sys.exit(main())
