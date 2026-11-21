"""One switch (MIBO_USER_DIRS) puts every known folder the app reads in a stand-in: Downloads, Documents, the
Desktop, Pictures, Music and Videos, as Settings lists them and a press grants them, so a test or a measuring
script's scratch home reads nothing of the computer it runs on; a folder the switch leaves out is none."""
from __future__ import annotations

import os

from mibo.shell import grants


def test_one_switch_puts_every_known_folder_in_a_stand_in(monkeypatch, tmp_path):
    places = {key: tmp_path / key.title() for key in grants.DIRS}
    for place in places.values():
        place.mkdir()
    monkeypatch.setenv(grants.DIRS_ENV, os.pathsep.join(str(places[key]) for key in grants.DIRS))
    assert {row["key"]: row["path"] for row in grants.known_folders()} == {k: str(v) for k, v in places.items()}
    monkeypatch.setenv(grants.DIRS_ENV, os.pathsep.join(str(places[key]) for key in ("desktop", "documents")))
    assert [row["key"] for row in grants.known_folders()] == ["documents", "desktop"]
