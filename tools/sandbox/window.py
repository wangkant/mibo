"""The window suite: tools/window_smoke.py as it is (the app's real window opens on a scratch home, the first run is
skipped through, a chat turn with the stand-in model, Settings, close), its lines read into checks, with pictures of
the screen while it runs.

    python tools/sandbox/window.py --out <folder>
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time

from _suite import REPO, Suite, scrub_env


def main() -> int:
    suite = Suite("window", __doc__.split("\n\n")[0])
    scrub_env()
    home = tempfile.mkdtemp(prefix="mibo-sandbox-", dir=os.environ.get("RUNNER_TEMP") or None)
    smoke = subprocess.Popen([sys.executable, str(REPO / "tools" / "window_smoke.py"), "--home", home],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def pictures() -> None:
        for n in range(4):
            time.sleep(15)
            if smoke.poll() is not None:
                return
            suite.shot(f"window-{n}")

    threading.Thread(target=pictures, daemon=True).start()
    with open(suite.out / "window_smoke.txt", "w", encoding="utf-8") as kept:
        for line in smoke.stdout:
            kept.write(line)
            found = re.match(r"(ok|FAIL)\s{2,}(.*?)(?:  \((.*)\))?$", line.rstrip())
            if found:
                suite.check("window", found[2], found[1] == "ok", found[3])
    code = smoke.wait()
    suite.check("window", "window_smoke.py exits 0", code == 0, code)
    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
