"""tools/opbench.py with every task sent from the chat beside the page, the page in that chat's context (its chip
in the chat's box, browse.js): the same tasks, cards, site verdicts, counts and table.

    python tools/opcolumn.py <scratch home> --out <folder> [--runs 3] [--tasks T01,T02] [--site-port 59630]

What is sent there the character does in the page with the person's own words and no reply model in between
(the turn choice "page"), so a task's model calls and input tokens are the loop's own. opbench by itself sends
from the chat as the window's width leaves it: beside the page in a wide window, away from it in a narrow one."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opbench

# The chat brought beside the page (the bar's button) and the page put back in its context if it was taken out;
# then whether what is sent now goes to the page.
BESIDE = ("(() => { if (!document.body.classList.contains('beside')) document.querySelector('.browse-beside')?.click(); "
          "document.querySelector('.browse-context-add')?.click(); "
          "return (window.paBeside?.take() || []).some((choice) => choice.startsWith('page')); })()")


class Beside:
    """opbench's driver, with the chat made to stand beside the page before each message is sent."""

    def __init__(self, driver):
        self.driver = driver

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def click(self, selector: str) -> bool:
        if selector == ".chat-send":
            if not self.driver.js(BESIDE):
                self.driver.log("   the chat is not beside the page: this message goes to the chat alone")
            time.sleep(0.5)
        return self.driver.click(selector)


def main(argv: list[str]) -> int:
    walk = opbench._walk
    opbench._walk = lambda driver, *rest: walk(Beside(driver), *rest)
    return opbench.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
