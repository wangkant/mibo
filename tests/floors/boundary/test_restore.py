"""A backup to restore is only one of this app's own: a zip whose members escape the home (zip-slip by
.., an absolute path or a drive), name files a backup never holds, or carry no manifest is refused before
anything is planned, and so is a name outside the backup places."""
from __future__ import annotations

import os
import zipfile

from fastapi.testclient import TestClient
import pytest

from mibo import welcome
from mibo.panels import desk

TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    desktop, documents = tmp_path / "Desktop", tmp_path / "Documents"
    desktop.mkdir()
    documents.mkdir()
    monkeypatch.setenv(desk.DIRS_ENV, os.pathsep.join([str(desktop), str(documents)]))
    value = welcome.Workspace(tmp_path / "home")
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    app = welcome.create_app(workspace.home, TOKEN, workspace=workspace)
    # What welcome._start gives the page: a new start, and this one ending.
    app.state.restarts = []
    app.state.relaunch = lambda: app.state.restarts.append("relaunch")
    app.state.shutdown = lambda: app.state.restarts.append("shutdown")
    # No lifespan: its loops write into the home.
    return TestClient(app, base_url="http://127.0.0.1")


def _restore(client, place: str, name: str) -> dict:
    return client.post("/api/desk/restore", headers=HEADERS, json={"place": place, "name": name}).json()


def _nothing_planned(client, workspace, tmp_path) -> bool:
    """No restart asked, no restore waiting for the next start, and a start that finds nothing to do
    writes nothing outside the home."""
    pending = not client.app.state.restarts and not list(workspace.home.rglob("pending.json"))
    desk.apply_pending(workspace.home)
    return pending and not list(tmp_path.rglob("evil.txt")) and not list(tmp_path.rglob("abs.txt"))


@pytest.mark.parametrize("members,manifest", [
    ({"../evil.txt": "x"}, True),
    ({"runtime/../../evil.txt": "x"}, True),
    ({"/abs.txt": "x"}, True),
    ({"C:/abs.txt": "x"}, True),
    ({"runtime\\..\\evil.txt": "x"}, True),
    ({"runtime/desktop/welcome.json": "{}"}, True),
    ({"runtime/desktop/webview/x": "x"}, True),
    ({"backups/mibo-backup-1.zip": "x"}, True),
    ({"persona.txt": "x"}, False),
], ids=["parent", "parent-inside", "absolute", "drive", "backslashes", "page-link", "browser-profile",
        "a-backup-inside", "no-manifest"])
def test_restore_refuses_a_zip_with_unexpected_files(client, workspace, tmp_path, members, manifest):
    with zipfile.ZipFile(tmp_path / "Desktop" / "mibo-backup-bad.zip", "w") as archive:
        if manifest:
            archive.writestr(desk.MANIFEST, "{}")
        for name, data in members.items():
            archive.writestr(name, data)
    assert _restore(client, "desktop", "mibo-backup-bad.zip") == {"error": "desk_invalid_backup"}
    assert _nothing_planned(client, workspace, tmp_path)


def test_restore_takes_only_a_backup_in_a_backup_place(client, workspace, tmp_path):
    (tmp_path / "Desktop" / "other.zip").write_bytes(b"PK")
    for place, name in (("desktop", "../x.zip"), ("desktop", "..\\x.zip"), ("desktop", "other.zip"),
                        ("elsewhere", "mibo-backup-1.zip"), ("D:/anywhere", "mibo-backup-1.zip")):
        assert _restore(client, place, name) == {"error": "desk_invalid_backup"}, (place, name)
    assert _restore(client, "desktop", "mibo-backup-none.zip") == {"error": "desk_missing"}
    (tmp_path / "Desktop" / "mibo-backup-junk.zip").write_bytes(b"not a zip")
    assert _restore(client, "desktop", "mibo-backup-junk.zip") == {"error": "desk_invalid_backup"}
    assert _nothing_planned(client, workspace, tmp_path)
