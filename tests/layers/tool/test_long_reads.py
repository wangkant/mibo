"""Long turns of large results at small, assumed and large windows (context-design's fit ladder, through whole
turns): the result the model has just asked for always arrives with a part it can read, older results give way
first, and no request passes the window."""
from __future__ import annotations

import re

import pytest
from harness.model import call, say, tokens
from harness.page import measured

from mibo.shell import files

ROUNDS = 30
_WIDE = re.compile("[⺀-鿿]")
# The cut's count of what it left out, in its own words, and the file it says holds the whole result.
_LEFT_OUT = re.compile(r"\[\.\.\. (\d+) characters of this result left out")
_KEPT_IN = re.compile(r"The whole result is in the file (.+?): read the part you need with read_file")


def _han(n: int, chars: int) -> str:
    # Distinct Chinese text, so a head and a tail can be told apart.
    return "".join(chr(0x4E00 + (n * 997 + i * 7) % 20000) for i in range(chars))


def _long_page(n: int, chars: int = 20_000) -> str:
    # A page of distinct Chinese lines, none repeated, so no line is dropped as the page's chrome.
    lines = ("".join(chr(0x4E00 + (n * 997 + i * 131 + j * 7) % 20000) for j in range(100))
             for i in range(chars // 100))
    body = "".join(f"<p>{line}</p>" for line in lines)
    return f"<html><head><title>{n}</title></head><body>{body}</body></html>"


def _first_seen(done) -> list[str]:
    """Each call's result as the request right after it carried it."""
    bodies = done.asked()
    seen = []
    for one in done.calls():
        body = next(b for b in bodies if any(m.get("tool_call_id") == one["id"] for m in b["messages"]))
        seen.append(next(m["content"] for m in body["messages"] if m.get("tool_call_id") == one["id"]))
    return seen


# A 16k window holds thirty rounds of one read; a wider one thirty rounds of three, whose older results alone
# would pass it at their small size.
@pytest.mark.parametrize("window, stated, reads", [(16384, 16384, 1), (32768, 0, 3), (131072, 131072, 3)],
                         ids=["16k", "32k-assumed", "128k"])
def test_thirty_steps_of_long_reads_each_newest_result_arrives_readable_within_the_window(
        app, site, turn, window, stated, reads):
    app.model.window = window
    measured(app, context=stated)
    pages = [site.put(f"/long{n}", _long_page(n)) for n in range(ROUNDS * reads)]
    # The person names the site: an address on it is theirs to give, round after round.
    done = turn(f"一页一页地读 {site.url} 上的页面", *[[call("read_page", url=page) for page in pages[k:k + reads]]
                               for k in range(0, len(pages), reads)], say("读完了。"))
    bodies = done.asked()
    # Every round was asked with its tools, and the stand-in, which refuses a request past its window, answered it.
    assert done.reply == "读完了。" and len(bodies) == ROUNDS + 1 and all(b.get("tools") for b in bodies)
    assert all(tokens(b) + b["max_tokens"] <= window for b in bodies)
    # No newest result arrives as a cut mark alone: each carries at least a few hundred characters of its page
    # (the mark names the file the whole result is in, so the least it leaves changes with that path's length).
    assert min(len(_WIDE.findall(text)) for text in _first_seen(done)) >= 500


def test_a_file_larger_than_the_window_arrives_cut_once_saying_what_was_left_out_and_how_to_read_it(
        app, turn, tmp_path):
    app.model.window = 16384
    measured(app, context=16384)
    big = tmp_path / "big.txt"
    big.write_text("\n".join(f"{n:06d} " + _han(n, 50) for n in range(14_000)), encoding="utf-8")
    assert big.stat().st_size > 2_000_000
    done = turn("读一下这个文件", call("read_file", path=str(big)), say("这个文件很大，我读了开头和结尾。"))
    (body, _), (one,) = done.asked(), done.calls()
    assert tokens(body) + body["max_tokens"] <= 16384
    seen = done.result_of(one["id"])
    head, tail = seen.split("\n\n[... ", 1)[0], seen.rsplit("...]\n\n", 1)[1]
    # What the tool gave: the file's text as the file tools read it, fenced as data.
    lead, close = head.split("[command_output]\n", 1)[0], tail.rsplit("\n[/command_output]", 1)[1]
    whole = f"{lead}[command_output]\n{files.read(str(big))}\n[/command_output]{close}"
    # One cut: its head and its tail, and the count of what lies between them.
    assert whole.startswith(head) and whole.endswith(tail) and len(_LEFT_OUT.findall(seen)) == 1
    assert int(_LEFT_OUT.search(seen).group(1)) == len(whole) - len(head) - len(tail)
    # Enough of it to work from, and how to read the rest: the cut names a range, the tail the next lines.
    assert len(_WIDE.findall(head)) >= 600 and "offset" in seen.split("\n\n[... ", 1)[1].split("]", 1)[0]
    assert "more lines: read again with offset" in tail


def test_a_result_cut_when_it_comes_in_is_read_back_from_the_file_its_cut_names(app, turn, tmp_path):
    app.model.window = 16384
    measured(app, context=16384)
    big = tmp_path / "big.txt"
    big.write_text("\n".join(f"{n:06d} " + _han(n, 50) for n in range(1500)), encoding="utf-8")
    first = turn("读一下这个文件", call("read_file", path=str(big)), say("读了开头和结尾。"))
    seen = first.result_of(first.calls()[0]["id"])
    path = _KEPT_IN.search(seen).group(1)
    with open(path, encoding="utf-8") as f:
        whole = f.read()
    # The file holds the result as it came in: what the model saw is its head and its tail.
    head, tail = seen.split("\n\n[... ", 1)[0], seen.rsplit("...]\n\n", 1)[1]
    assert whole.startswith(head) and whole.endswith(tail) and len(whole) > 2 * len(seen)
    # Any part of it is read with the file tool, with no question asked.
    lines = whole.splitlines()
    middle = len(lines) // 2
    again = turn("中间那部分呢", call("read_file", path=path, offset=middle, limit=3), say("读到了。"), cards="no")
    assert again.cards == []
    assert _WIDE.findall(lines[middle - 1])[:40] == _WIDE.findall(again.result_of(again.calls()[0]["id"]))[:40]
