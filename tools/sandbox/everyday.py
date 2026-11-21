"""The everyday suite: the requests of tools/everyday.py that need a window (typed beside a page in the built-in
browser, or done in another program), sent through the app's real window with a real model: claude-haiku-5-5,
the cheapest, behind everyday.py's own meter, which refuses every call past the budget.

    python tools/sandbox/everyday.py --out <folder>

It runs only on Windows (the bench needs the app window and its browser) and only with SANDBOX_MODEL_KEY set, which
happens in a sandbox on a person's own computer alone: no model key is kept on GitHub, so on a hosted runner this
suite reports itself as not run. The cap is SANDBOX_BUDGET dollars (0.30 when unset). The key reaches everyday.py and
the app only through their environment (tools/scratchhome.py) and is never printed. Each request's verdict is the
bench's own checker on what really happened; a failed request is the model's or the app's, read its row.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

from _suite import TOOLS, Suite, run_tool, scrub_env

MODEL = "claude-haiku-5-5"
# Dollars per million tokens, input and output (Anthropic's price for prompts up to 100K tokens).
PRICE = ("0.10", "0.50")
FEATURE = "everyday requests in windows"


def window_requests() -> list[dict]:
    """The requests everyday.py marks as needing more than the chat (a page, a program): those `run --chat` leaves to
    the sandbox."""
    spec = importlib.util.spec_from_file_location("everyday_bench", TOOLS / "everyday.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    return [r for r in bench.REQUESTS if r["needs"] != "chat"]


def main() -> int:
    suite = Suite("everyday", __doc__.split("\n\n")[0])
    key = os.environ.get("SANDBOX_MODEL_KEY", "")
    if sys.platform != "win32":
        suite.not_built(FEATURE, "the bench needs the Windows app window and its built-in browser")
        return suite.finish()
    if not key:
        suite.skipped(FEATURE, "not run: no model key here (this suite runs in a sandbox on the person's own computer)")
        return suite.finish()
    scrub_env()
    budget = os.environ.get("SANDBOX_BUDGET") or "0.30"
    # everyday.py prepare lays out the home with the places folder as its computer; run reads the model from here.
    home = tempfile.mkdtemp(prefix="mibo-sandbox-", dir=os.environ.get("RUNNER_TEMP") or None)
    os.environ.update({"LLM_API_KEY": key, "LLM_BASE_URL": "https://api.anthropic.com/v1"})
    places = tempfile.mkdtemp(prefix="mibo-places-", dir=os.environ.get("RUNNER_TEMP") or None)
    wanted = window_requests()
    suite.log("requests:", ", ".join(r["id"] for r in wanted), f"model {MODEL}, cap ${budget}")
    run_tool(suite, "prepare", ["tools/everyday.py", "prepare", str(home), "--places", places], "prepare")
    bench_out = suite.out / "bench"
    run_tool(suite, "bench", ["tools/everyday.py", "run", str(home), "--places", places, "--model", MODEL,
                              "--out", str(bench_out),
                              "--only", ",".join(r["id"] for r in wanted), "--runs", "1", "--budget", budget,
                              "--price-in", PRICE[0], "--price-out", PRICE[1]], "run", timeout=2700)
    results = json.loads((bench_out / "results.json").read_text(encoding="utf-8")) if (bench_out / "results.json").is_file() else []
    left = json.loads((bench_out / "left.json").read_text(encoding="utf-8")) if (bench_out / "left.json").is_file() else []
    for request in wanted:
        rows = [r for r in results if r["id"] == request["id"]]
        if rows:
            suite.check(FEATURE, f"{request['id']} {request['say']}", rows[0]["ok"],
                        {"note": rows[0]["note"][:160], "calls": rows[0]["calls"], "cards": rows[0]["cards"]})
        else:
            suite.log(f"{request['id']} not run:", "left out (budget or a reason in the log)" if request["id"] in left else "no row")
    spent = sum(json.loads(line).get("cost") or 0 for line in (bench_out / "model.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()) if (bench_out / "model.jsonl").is_file() else 0
    suite.check("spending", f"stayed within the ${budget} cap", spent <= float(budget), round(spent, 4))
    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
