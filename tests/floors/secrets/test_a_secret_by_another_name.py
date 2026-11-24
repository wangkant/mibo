"""A key file is the key file by any of its names: a hard link to it in an ordinary folder is refused as the key is,
for a command and a file tool alike, its names read from Windows itself; and a program the reader cannot follow
(robocopy, tar) that names a key's folder is refused, not asked. (2026-11-23 review of 0368fcc: Documents\\notes.txt
hard-linked to .ssh\\id_ed25519 was read with no question; robocopy and tar of .ssh were only asked.)

A stand-in key in a temp folder; the reviewer is scripted to pass everything, and every question is answered no."""
from __future__ import annotations

import json
import os
import sys

import pytest
from harness.model import call, say, text

from mibo.shell import files
from mibo.shell import read as reading
from mibo.shell.grants import LOG_FILE, Grants, link_names, norm

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="hard links' names and the reader are Windows'")

PASSES = [text(json.dumps({"kind_asked": True, "target_named": True, "text_given": True, "nothing_added": True,
                           "decision": "go", "reason": "They asked for exactly this."}))] * 3


@pytest.fixture
def key(tmp_path):
    place = tmp_path / "keys" / ".ssh"
    place.mkdir(parents=True)
    (place / "id_ed25519").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    return place / "id_ed25519"


def test_a_hard_link_to_a_key_is_the_key(key, tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    os.link(key, docs / "notes.txt")
    home = tmp_path / "home"
    grants = Grants(home / "runtime" / "desktop", home)
    assert grants.add(str(docs)) == ""
    assert norm(key) in link_names(norm(docs / "notes.txt"))
    for command in ("Get-Content notes.txt", "Select-String -Path notes.txt -Pattern KEY", "cmd /c type notes.txt"):
        verdict = reading.judge(reading.read(command, str(docs)), grants)
        assert verdict.action == "refuse", command
    job = {"op": "read", "path": str(docs / "notes.txt"), "recursive": False}
    verdict = reading.judge(reading.Reading("read_file", str(docs), files.acts(job, str(docs)), []), grants)
    assert verdict.action == "refuse"


def test_a_program_that_names_a_keys_folder_is_refused_not_asked(app, turn, key, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(folder)) == ""
    for command in (f'robocopy "{key.parent}" "{folder}\\bk" /MIR', f'tar -cf out.tar -C "{key.parent.parent}" .ssh'):
        app.model.script(*PASSES, purpose="reviewer")
        done = turn("备份一下文件", call("use_computer", command=command, folder=str(folder)), say("I left it."),  # copy: voice
                    cards="no")
        assert done.cards == [], command
    logged = [json.loads(line) for line in (app.home / "runtime" / "desktop" / LOG_FILE).read_text(
        encoding="utf-8").splitlines()]
    assert [row["outcome"] for row in logged] == ["refused", "refused"]
    assert not (folder / "bk").exists() and not (folder / "out.tar").exists()


def test_a_secrets_data_stream_and_a_junction_to_its_link_are_the_secret(key, tmp_path):
    """(2026-11-23 review of f3e736f: `Get-Content .env::$DATA` in a granted project was only asked; a key's hard link
    read through a junction, and the browser's History and the app's own files by hard links, are refused too.)"""
    import _winapi
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    os.link(key, docs / "k.txt")
    _winapi.CreateJunction(str(docs), str(tmp_path / "J"))
    home = tmp_path / "home"
    grants = Grants(home / "runtime" / "desktop", home)
    assert grants.add(str(docs)) == ""
    for command in ("Get-Content .env::$DATA", "Get-Content '.env::$DATA'", "Copy-Item .env::$DATA x.txt",
                    f"Get-Content '{key}::$DATA'", f"Get-Content '{key}:$DATA'", f'Get-Content "{tmp_path / "J" / "k.txt"}"'):
        verdict = reading.judge(reading.read(command, str(docs)), grants)
        assert verdict.action == "refuse", command
