"""A bash command is read before it runs (mibo.shell.bashread): parsed with tree-sitter-bash and sorted into
read.py's act kinds, over the labelled corpus in tools/xplat/bash_corpus.jsonl. The places are POSIX names; on
Windows nothing is looked up on disk, so the same sort holds there."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mibo.shell import bashread
from mibo.shell import read as reading
from mibo.shell.grants import Grants

CORPUS = [json.loads(line) for line in
          (Path(__file__).resolve().parents[3] / "tools" / "xplat" / "bash_corpus.jsonl")
          .read_text(encoding="utf-8").splitlines() if line.strip()]
CWD, HOME = "/scratch/files", "/scratch/home"


def sorted_as(label: str) -> list[tuple[str, str]]:
    return [(row["cmd"], bashread.gist(bashread.read(row["cmd"], CWD, HOME))) for row in CORPUS
            if row["label"] == label]


def test_every_never_and_ask_command_in_the_corpus_is_refused_or_asked():
    let_through = [(cmd, got) for label in ("never", "ask") for cmd, got in sorted_as(label)
                   if got not in ("never", "ask")]
    assert let_through == []


def test_no_write_delete_or_network_command_in_the_corpus_is_sorted_read():
    taken_as_read = [(cmd, got) for label in ("write", "delete", "network") for cmd, got in sorted_as(label)
                     if got == "read"]
    assert taken_as_read == []


def test_at_least_95_percent_of_read_commands_in_the_corpus_are_sorted_read():
    rows = sorted_as("read")
    assert sum(got == "read" for _, got in rows) >= 0.95 * len(rows), [r for r in rows if r[1] != "read"]


def test_a_command_bash_cannot_parse_is_asked_and_never_run():
    r = bashread.read('cat "a.txt', CWD, HOME)
    assert r.errors and bashread.gist(r) == "ask"
    assert reading.judge(r, None).action == "invalid"


def test_a_write_carries_the_place_it_lands_on():
    r = bashread.read("p=n.txt; cd 临时 && cp ../a.txt $p", CWD, HOME)
    copy = next(a for a in r.acts if a.what == "copy")
    assert copy.paths == ["/scratch/files/a.txt"] and copy.dest == "/scratch/files/临时/n.txt"
    assert not copy.unresolved


def test_a_command_after_a_cd_that_may_fail_is_not_placed_in_the_new_folder():
    # `cd x || rm -rf *` deletes in the folder it started from, exactly when x cannot be entered.
    for cmd in ("cd 临时 || rm -rf *", "cd 临时; rm -rf *", "if false; then cd 临时; fi; rm -rf *"):
        deletes = [a for a in bashread.read(cmd, CWD, HOME).acts if a.kind == "delete"]
        assert deletes and all(a.unresolved and "/scratch/files/临时" not in a.paths for a in deletes), cmd


@pytest.mark.parametrize("cmd",["cat ~/.s*/id_*", "cp a.txt /e?c/x", "cat /proc/*/environ"])
def test_a_wildcard_that_reaches_a_protected_place_is_refused(cmd):
    assert bashread.gist(bashread.read(cmd, CWD, HOME)) == "never"


@pytest.mark.skipif(os.sep != "/", reason="read.judge holds POSIX places only on a POSIX computer")
def test_the_judge_runs_no_never_ask_delete_or_network_command_with_one_folder_granted(tmp_path):
    files, home = tmp_path / "files", tmp_path / "home"
    (files / "临时").mkdir(parents=True)
    (home / "runtime" / "desktop").mkdir(parents=True)
    for name in ("a.txt", "b.txt", "notes.txt", "tool.sh", "临时/x.log"):
        (files / name).write_text("x", encoding="utf-8")
    (home / ".env").write_text("SECRET=1\n", encoding="utf-8")
    os.environ["AGENT_HOME"] = str(home)
    grants = Grants(home / "runtime" / "desktop", home)
    grants.set_on(True)
    assert grants.add(str(files)) == ""
    ran = [row["cmd"] for row in CORPUS if row["label"] in ("never", "ask", "delete", "network")
           and reading.judge(bashread.read(row["cmd"], str(files), str(home)), grants).action == "run"]
    assert ran == []
