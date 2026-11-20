"""The desk panel: start at sign-in, and backing up, restoring and resetting the home."""
from __future__ import annotations

import io
import json
import os
import zipfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import pytest

from persona_agent import i18n, shortcut
from persona_agent import setup_wizard as sw
from persona_agent import welcome
from persona_agent.panels import desk

TOKEN = "test-local-capability"
HEADERS = {welcome.TOKEN_HEADER: TOKEN}
KEY = "sk-desk-secret-0123456789"
MCP_KEY = "ghp-desk-secret-0123456789"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    desktop, documents = tmp_path / "Desktop", tmp_path / "Documents"
    desktop.mkdir()
    documents.mkdir()
    monkeypatch.setenv(desk.DIRS_ENV, os.pathsep.join([str(desktop), str(documents)]))
    links = [tmp_path / "links" / k for k in shortcut.SPECIAL]
    monkeypatch.setenv(shortcut.DIRS_ENV, os.pathsep.join(map(str, links)))
    value = welcome.Workspace(home)
    yield value
    value.close()


@pytest.fixture
def client(workspace):
    app = welcome.create_app(workspace.home, TOKEN, workspace=workspace)
    # What welcome._start gives the page: a new start, and this one ending.
    app.state.restarts = []
    app.state.relaunch = lambda: app.state.restarts.append("relaunch")
    app.state.shutdown = lambda: app.state.restarts.append("shutdown")
    # No lifespan: its loops write into the home, which the app that asked has left by the next start.
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def opened(monkeypatch):
    seen = []
    monkeypatch.setattr(desk, "open_path", seen.append)
    return seen


def seed(home):
    sw.write_env(home / ".env", {"LLM_API_KEY": KEY, "LLM_MODEL": "m", "PERSONA_NAME": "Ann",
                                 "MIBO_MCP_GITHUB_TOKEN": MCP_KEY})
    (home / "persona.txt").write_text("You are Ann.\n", encoding="utf-8")
    (home / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    (home / "skills" / "notes").mkdir(parents=True)
    (home / "skills" / "notes" / "SKILL.md").write_text("notes", encoding="utf-8")
    runtime = home / "runtime"
    (runtime / "desktop" / "webview").mkdir(parents=True)
    (runtime / "desktop" / "webview" / "Cookies").write_text("site sign-in", encoding="utf-8")
    (runtime / "desktop" / "app.log").write_text("log line\n", encoding="utf-8")
    (runtime / "desktop" / "welcome.json").write_text('{"url": "x"}', encoding="utf-8")
    (runtime / "desktop" / "browser-chat.json").write_text('{"history": []}', encoding="utf-8")
    (runtime / "desktop" / "app.json").write_text('{"toured": true}', encoding="utf-8")
    (runtime / "memory.json").write_text('{"a": "likes tea"}', encoding="utf-8")
    (runtime / "dashboard.token").write_text("dash-token", encoding="utf-8")
    (runtime / "log").mkdir()
    (runtime / "log" / "x.jsonl").write_text("{}", encoding="utf-8")
    (home / "data").mkdir()
    (home / "data" / "examples.en.jsonl").write_text("", encoding="utf-8")


def post(client, path, payload=None):
    return client.post(f"/api/desk{path}", headers=HEADERS, json=payload or {})


def test_every_route_needs_the_local_token(client):
    assert client.get("/api/desk/data").status_code == 403
    assert client.post("/api/desk/reset", json={}).status_code == 403
    assert client.post("/api/desk/open", json={"place": "desktop"},
                       headers={**HEADERS, "Origin": "https://other.example"}).status_code == 403


def test_data_names_the_places_and_no_secret(client, workspace, tmp_path):
    seed(workspace.home)
    answer = client.get("/api/desk/data", headers=HEADERS)
    assert answer.status_code == 200
    value = answer.json()
    assert {t["id"]: t["path"] for t in value["targets"]} == {
        "desktop": str(tmp_path / "Desktop"), "documents": str(tmp_path / "Documents"),
        "backups": str(workspace.home / "backups")}
    assert value["backups"] == [] and value["restored"] is None
    assert KEY not in answer.text


def test_open_shows_only_the_places_a_backup_goes(client, opened, tmp_path, workspace):
    assert post(client, "/open", {"place": "backups"}).json() == {"ok": True}
    assert opened == [workspace.home / "backups"] and (workspace.home / "backups").is_dir()
    assert post(client, "/open", {"place": "D:/anywhere"}).json() == {"error": "desk_invalid_place"}
    assert opened == [workspace.home / "backups"]


# -- start at sign-in --------------------------------------------------------

def fake_windows(monkeypatch, found):
    """Windows' answer about the links, and every script it was asked to run."""
    ran = []

    def powershell(source):
        ran.append(source)
        return (json.dumps(found) if "ConvertTo-Json" in source else ""), ""
    monkeypatch.setattr(shortcut, "WINDOWS", True)
    monkeypatch.setattr(shortcut, "_powershell", powershell)
    return ran


def test_start_at_sign_in_tells_this_copy_from_another(client, workspace, monkeypatch):
    program, arguments = shortcut.target(workspace.home)
    fake_windows(monkeypatch, [{"kind": "startup", "target": str(program), "arguments": "-m other"}])
    assert client.get("/api/desk/shortcuts", headers=HEADERS).json() == {"login_supported": True, "login": "other"}
    fake_windows(monkeypatch, [])
    assert client.get("/api/desk/shortcuts", headers=HEADERS).json()["login"] == "off"


def test_status_asks_only_the_redirected_folders(workspace, tmp_path, monkeypatch):
    ran = fake_windows(monkeypatch, [])
    shortcut.status(workspace.home)
    assert "GetFolderPath" not in ran[-1] and str(tmp_path / "links" / "startup") in ran[-1]
    monkeypatch.setenv(shortcut.DIRS_ENV, "only-one")
    with pytest.raises(ValueError):
        shortcut.status(workspace.home)


def test_turning_it_on_writes_only_the_startup_link(client, workspace, tmp_path, monkeypatch):
    ran = fake_windows(monkeypatch, [])
    answer = post(client, "/shortcut", {"which": "login", "on": True})
    assert answer.status_code == 200 and answer.json()["login_supported"] is True
    made = [s for s in ran if "Save-Link $final" in s][-1]
    assert str(tmp_path / "links" / "startup") in made and "Desktop" not in made
    assert f'--home "{workspace.home}"' in made


def test_start_at_sign_in_refusals(client, monkeypatch):
    fake_windows(monkeypatch, [])
    monkeypatch.setattr(shortcut, "_powershell", lambda source: ("", "access denied"))
    assert post(client, "/shortcut", {"on": True}).json() == {"error": "desk_shortcut_failed"}
    assert client.get("/api/desk/shortcuts", headers=HEADERS).json() == {"error": "desk_shortcut_failed"}
    monkeypatch.setattr(shortcut, "WINDOWS", False)
    monkeypatch.setattr(desk.autostart, "MACOS", False)
    assert client.get("/api/desk/shortcuts", headers=HEADERS).json()["login_supported"] is False
    assert post(client, "/shortcut", {"on": True}).json() == {"error": "desk_unsupported"}


def test_a_startup_link_made_here_reads_as_on(workspace, monkeypatch):
    program, arguments = shortcut.target(workspace.home)
    made = shortcut.script(workspace.home, kinds=shortcut.LOGIN)
    assert f"$link.Arguments = '{arguments} --background'" in made
    fake_windows(monkeypatch, [{"kind": "startup", "target": str(program),
                                "arguments": arguments + " --background"}])
    assert shortcut.status(workspace.home)["startup"] == "on"


# -- backing up ---------------------------------------------------------------

def test_a_backup_holds_the_home_but_no_keys_logs_sign_ins_or_chat_record(client, workspace, tmp_path):
    seed(workspace.home)
    answer = post(client, "/backup", {"to": "documents"})
    assert answer.status_code == 200
    value = answer.json()
    path = tmp_path / "Documents" / value["name"]
    assert value["path"] == str(path) and value["size"] == path.stat().st_size > 0
    archive = zipfile.ZipFile(path)
    names = set(archive.namelist())
    assert {desk.MANIFEST, ".env", "persona.txt", "mcp.json", "skills/notes/SKILL.md", "runtime/memory.json",
            "runtime/desktop/browser-chat.json", "runtime/desktop/app.json", "data/examples.en.jsonl"} <= names
    for left in ("runtime/desktop/app.log", "runtime/desktop/welcome.json",
                 "runtime/desktop/webview/Cookies", "runtime/log/x.jsonl"):
        assert left not in names, left
    env = archive.read(".env").decode("utf-8")
    assert KEY not in env and MCP_KEY not in env and "LLM_MODEL=m" in env and "LLM_API_KEY=" in env
    assert json.loads(archive.read(desk.MANIFEST))["secrets"] is False
    assert [b["name"] for b in value["backups"]] == [value["name"]]
    assert value["backups"][0]["place"] == "documents"
    assert post(client, "/backup", {"to": "D:/anywhere"}).json() == {"error": "desk_invalid_place"}


def test_keys_go_into_a_backup_only_when_asked(client, workspace, tmp_path):
    seed(workspace.home)
    name = post(client, "/backup", {"to": "desktop", "secrets": True}).json()["name"]
    archive = zipfile.ZipFile(tmp_path / "Desktop" / name)
    assert KEY in archive.read(".env").decode("utf-8") and MCP_KEY in archive.read(".env").decode("utf-8")
    assert json.loads(archive.read(desk.MANIFEST))["secrets"] is True


def test_backup_reports_a_folder_it_cannot_write(client, workspace, monkeypatch, tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(desk.DIRS_ENV, os.pathsep.join([str(blocker / "inside"), str(tmp_path)]))
    assert post(client, "/backup", {"to": "desktop"}).json() == {"error": "desk_backup_failed"}
    monkeypatch.setenv(desk.DIRS_ENV, "")
    monkeypatch.setattr(desk, "_known_folder", lambda kind: None)
    assert post(client, "/backup", {"to": "desktop"}).json() == {"error": "desk_missing"}


# -- restoring ------------------------------------------------------------------

def test_a_restore_is_done_by_the_next_start_and_keeps_the_keys_here(client, workspace, tmp_path):
    seed(workspace.home)
    home = workspace.home
    name = post(client, "/backup", {"to": "desktop"}).json()["name"]
    (home / "runtime" / "memory.json").write_text('{"b": "later"}', encoding="utf-8")
    (home / "skills" / "later").mkdir()
    (home / "skills" / "later" / "SKILL.md").write_text("later", encoding="utf-8")
    answer = post(client, "/restore", {"place": "desktop", "name": name})
    assert answer.json() == {"restarting": True}
    assert client.app.state.restarts == ["relaunch", "shutdown"]
    assert json.loads((home / "runtime" / "desktop" / "pending.json").read_text(encoding="utf-8")) == {
        "restore": str(tmp_path / "Desktop" / name)}
    desk.apply_pending(home)
    assert (home / "runtime" / "memory.json").read_text(encoding="utf-8") == '{"a": "likes tea"}'
    assert not (home / "skills" / "later").exists()
    values = dotenv_values(home / ".env")
    assert values["LLM_API_KEY"] == KEY and values["MIBO_MCP_GITHUB_TOKEN"] == MCP_KEY
    assert (home / "runtime" / "desktop" / "webview" / "Cookies").exists()
    assert (home / "runtime" / "log" / "x.jsonl").exists()
    assert not (home / "runtime" / "desktop" / "pending.json").exists()
    safety = [p.name for p in (home / "backups").glob("mibo-backup-*-before-restore.zip")]
    assert len(safety) == 1
    told = client.get("/api/desk/data", headers=HEADERS).json()
    assert told["restored"] == {"error": ""}
    assert client.get("/api/desk/data", headers=HEADERS).json()["restored"] is None


def make_zip(path, members, manifest=True):
    with zipfile.ZipFile(path, "w") as archive:
        if manifest:
            archive.writestr(desk.MANIFEST, "{}")
        for name, data in members.items():
            archive.writestr(name, data)


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
])
def test_restore_refuses_a_zip_with_unexpected_files(client, workspace, tmp_path, members, manifest):
    seed(workspace.home)
    make_zip(tmp_path / "Desktop" / "mibo-backup-bad.zip", members, manifest)
    answer = post(client, "/restore", {"place": "desktop", "name": "mibo-backup-bad.zip"})
    assert answer.json() == {"error": "desk_invalid_backup"}
    assert client.app.state.restarts == []
    assert not (workspace.home / "runtime" / "desktop" / "pending.json").exists()


def test_restore_refusals(client, workspace, tmp_path):
    for payload in ({"place": "desktop", "name": "../x.zip"}, {"place": "desktop", "name": "other.zip"},
                    {"place": "elsewhere", "name": "mibo-backup-1.zip"}):
        assert post(client, "/restore", payload).json() == {"error": "desk_invalid_backup"}
    assert post(client, "/restore", {"place": "desktop", "name": "mibo-backup-none.zip"}).json() \
        == {"error": "desk_missing"}
    (tmp_path / "Desktop" / "mibo-backup-junk.zip").write_bytes(b"not a zip")
    assert post(client, "/restore", {"place": "desktop", "name": "mibo-backup-junk.zip"}).json() \
        == {"error": "desk_invalid_backup"}
    assert client.app.state.restarts == []


def test_a_restore_that_fails_midway_puts_the_present_back(client, workspace, monkeypatch):
    seed(workspace.home)
    home = workspace.home
    name = post(client, "/backup", {"to": "backups"}).json()["name"]
    (home / "runtime" / "memory.json").write_text('{"b": "now"}', encoding="utf-8")
    real, failed = desk.shutil.copyfileobj, []

    def flaky(source, out, *args):
        # Only the copy out of a backup: zipfile uses the same function to write one.
        if not failed and isinstance(out, io.BufferedWriter):
            failed.append(True)
            raise OSError("disk full")
        return real(source, out, *args)
    monkeypatch.setattr(desk.shutil, "copyfileobj", flaky)
    post(client, "/restore", {"place": "backups", "name": name})
    desk.apply_pending(home)
    assert (home / "runtime" / "memory.json").read_text(encoding="utf-8") == '{"b": "now"}'
    assert (home / "persona.txt").exists() and (home / "skills" / "notes" / "SKILL.md").exists()
    assert client.get("/api/desk/data", headers=HEADERS).json()["restored"] == {"error": "desk_restore_undone"}


# -- resetting --------------------------------------------------------------------

def test_a_reset_backs_up_first_when_asked_then_leaves_only_the_backups(client, workspace, tmp_path):
    seed(workspace.home)
    home = workspace.home
    (home / "backups").mkdir()
    (home / "backups" / "mibo-backup-old.zip").write_bytes(b"kept")
    answer = post(client, "/reset", {"backupTo": "desktop", "secrets": True})
    value = answer.json()
    assert value["restarting"] is True and value["path"].startswith(str(tmp_path / "Desktop"))
    assert KEY in zipfile.ZipFile(value["path"]).read(".env").decode("utf-8")
    assert client.app.state.restarts == ["relaunch", "shutdown"]
    assert (home / ".env").exists(), "nothing is deleted before the next start"
    desk.apply_pending(home)
    assert (home / "backups" / "mibo-backup-old.zip").exists() and (home / "runtime" / "desktop" / "app.log").exists()
    for gone in (".env", "persona.txt", "mcp.json", "skills", "data", "runtime/memory.json", "runtime/log",
                 "runtime/desktop/webview", "runtime/desktop/app.json", "runtime/desktop/pending.json"):
        assert not (home / gone).exists(), gone


def test_a_reset_without_a_backup_writes_none(client, workspace, tmp_path):
    seed(workspace.home)
    assert post(client, "/reset", {}).json() == {"restarting": True, "path": ""}
    assert list((tmp_path / "Desktop").iterdir()) == [] and list((tmp_path / "Documents").iterdir()) == []


def test_a_start_with_nothing_asked_changes_nothing(workspace):
    seed(workspace.home)
    before = sorted(p.relative_to(workspace.home).as_posix() for p in workspace.home.rglob("*"))
    desk.apply_pending(workspace.home)
    assert sorted(p.relative_to(workspace.home).as_posix() for p in workspace.home.rglob("*")) == before


def test_errors_are_ones_the_page_can_show():
    assert all(code.startswith("desk_") for code in desk.ERRORS)
    for code in (*desk.ERRORS, "desk_restore_undone", "desk_restore_failed"):
        for lang in ("zh", "en"):
            assert code in i18n.catalog(lang)["setup_device"]["errors"], (lang, code)
