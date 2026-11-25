"""How much memory a running Mibo holds on Windows: its own process and every WebView2 process under it, by kind.

    python tools/webview_memory.py --pid PID [--every SECONDS]

PID is the app's own process (mibo.exe, or the python running `mibo start`). Each WebView2 browser process under it
is listed with its GPU, renderer, utility and crashpad processes, as a tree. Working set and private bytes in MB.
With --every it measures again at that interval until Ctrl+C, to watch the window being put away and brought back.
It reads process lists only and touches nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time

QUERY = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-CimInstance Win32_Process | Select-Object "
         "ProcessId,ParentProcessId,Name,CommandLine,WorkingSetSize,PrivatePageCount | ConvertTo-Json -Compress")


def processes() -> list[dict]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", QUERY], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    return json.loads(out)


def kind(row: dict) -> str:
    line = row.get("CommandLine") or ""
    found = re.search(r"--type=([\w-]+)", line)
    if not found:
        return "browser" if row["Name"].lower() == "msedgewebview2.exe" else row["Name"]
    sub = re.search(r"--utility-sub-type=([\w.]+)", line)
    return f"{found.group(1)} {sub.group(1).rsplit('.', 1)[-1]}" if sub else found.group(1)


def report(pid: int) -> None:
    rows = processes()
    children: dict[int, list[dict]] = {}
    for row in rows:
        children.setdefault(row["ParentProcessId"], []).append(row)
    total_ws = total_private = 0.0

    def show(row: dict, depth: int) -> None:
        nonlocal total_ws, total_private
        ws, private = row["WorkingSetSize"] / 2**20, row["PrivatePageCount"] / 2**20
        total_ws, total_private = total_ws + ws, total_private + private
        print(f"{'  ' * depth}{kind(row):<34} pid {row['ProcessId']:>6}  ws {ws:7.1f}  private {private:7.1f}")
        for child in children.get(row["ProcessId"], []):
            show(child, depth + 1)

    app = next((row for row in rows if row["ProcessId"] == pid), None)
    if app is None:
        raise SystemExit(f"no process {pid}")
    print(time.strftime("%H:%M:%S"))
    show(app, 0)
    print(f"{'total':<34}             ws {total_ws:7.1f}  private {total_private:7.1f}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--every", type=float, default=0)
    args = parser.parse_args()
    report(args.pid)
    while args.every:
        time.sleep(args.every)
        report(args.pid)


if __name__ == "__main__":
    main()
