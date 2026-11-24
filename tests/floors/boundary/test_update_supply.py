"""The in-app update is the app running a program fetched from the network (mibo/updates.py). Only a press on the
app's own page starts it, only for the version the app's own check found; the file comes only over https from the
project's GitHub releases and GitHub's asset host, from public addresses, no larger than the listing states; it
runs only once its size and SHA-256 match the release (and its signature, once there is a key), and only if it is
still the file that was checked. Otherwise nothing runs and nothing is left. The release is the stand-in of
harness/releases.py: the app's checks run whole, and nothing starts for real."""
from __future__ import annotations

import base64
import hashlib
import os
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient
from harness.releases import API_HOST, ASSET_HOST, FILE_HOST, INSTALLER, Releases

from mibo import ed25519, updates, welcome

TOKEN = "test-local-capability"
KEY = "frame-key-of-the-window"
OWN = {welcome.TOKEN_HEADER: TOKEN, "X-Mibo-Window": KEY}
NEW = "99.0.0"


class Window:
    """The app window as the route reads it: its key, and nothing else."""
    frame_key = KEY
    can_hide = frameless = maximized = False

    def is_own_page(self, key: str) -> bool:
        return key == KEY


@pytest.fixture
def releases(monkeypatch, site, web):
    monkeypatch.setattr(updates, "way", lambda: "installer")
    yield Releases(monkeypatch, site, web)
    updates._jobs.clear()


@pytest.fixture
def page(tmp_path):
    """The app's routes with its window, and what closing the app for the installer did."""
    workspace = welcome.Workspace(tmp_path)
    app = welcome.create_app(workspace.home, TOKEN, workspace=workspace)
    app.state.window = Window()
    app.state.closed = []
    app.state.shutdown = lambda: app.state.closed.append(True)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.home = workspace.home
    yield client
    workspace.close()


def _ended(client) -> dict:
    """The update's state once it has stopped moving."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get("/api/runtime", headers=OWN).json()["job"]
        if job and job["state"] not in ("downloading", "verifying"):
            return job
        time.sleep(0.02)
    raise AssertionError("the update did not end")


def _left(home) -> list[str]:
    folder = home / "runtime" / "updates"
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def _sign(secret: bytes, message: bytes) -> tuple[bytes, bytes]:
    """An Ed25519 key pair from `secret` and its signature of `message` (RFC 8032, 5.1.6), made here."""
    def encode(point) -> bytes:
        inverse = pow(point[2], ed25519.P - 2, ed25519.P)
        x, y = point[0] * inverse % ed25519.P, point[1] * inverse % ed25519.P
        return (y | (x & 1) << 255).to_bytes(32, "little")

    digest = hashlib.sha512(secret).digest()
    scalar = int.from_bytes(digest[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    public = encode(ed25519._mul(scalar, ed25519.BASE))
    r = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little") % ed25519.L
    point = encode(ed25519._mul(r, ed25519.BASE))
    h = int.from_bytes(hashlib.sha512(point + public + message).digest(), "little") % ed25519.L
    return public, point + ((r + h * scalar) % ed25519.L).to_bytes(32, "little")


def test_a_press_installs_the_found_release_over_this_folder_with_the_exact_command(releases, page):
    name = releases.publish(NEW)
    releases.found(page.home, NEW)
    started = page.post("/api/runtime/update", json={}, headers=OWN)
    assert started.status_code == 200 and started.json()["job"]["version"] == NEW
    assert _ended(page)["state"] == "installing"
    setup = page.home / "runtime" / "updates" / name
    assert releases.launched == [
        f'"{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL /CLOSEAPPLICATIONS '
        f'/DIR="{os.path.dirname(sys.executable)}" /LOG="{setup.with_name("setup.log")}" /WAITPID={os.getpid()} '
        f'/RESTARTHOME="{page.home}"']
    assert setup.read_bytes() == INSTALLER and _left(page.home) == [name, "state.json"]
    # Only https, only GitHub's listing, the project's own download and the asset host it was sent on to.
    assert [host for host, _url in releases.hops] == [API_HOST, FILE_HOST, FILE_HOST, ASSET_HOST]
    assert all(url.startswith("https://") for _host, url in releases.hops)
    deadline = time.monotonic() + 5
    while not page.app.state.closed and time.monotonic() < deadline:
        time.sleep(0.02)
    assert page.app.state.closed == [True], "the app closes for the installer"
    assert updates._state(page.home)["pending"]["version"] == NEW


@pytest.mark.parametrize("change, error", [
    ({"sums": b"0" * 64 + b"  mibo-99.0.0-setup.exe\n"}, "update_mismatch"),
    ({"sums": hashlib.sha256(INSTALLER).hexdigest().encode() + b"  mibo-99.0.0-setup.exe.old\n"}, "update_mismatch"),
    ({"size": len(INSTALLER) - 1}, "update_size"),
    ({"size": len(INSTALLER) + 1}, "update_size"),
    ({"served": INSTALLER[:-100]}, "update_size"),
    ({"served": INSTALLER + b"tail"}, "update_size"),
    ({"redirect": "https://evil.example/mibo-99.0.0-setup.exe"}, "update_source"),
    ({"redirect": f"http://{ASSET_HOST}/mibo-99.0.0-setup.exe"}, "update_source"),
    ({"redirect": "https://github.com/someone/else/releases/download/v99.0.0/mibo-99.0.0-setup.exe"}, "update_source"),
    ({"redirect": f"https://{ASSET_HOST}:8443/mibo-99.0.0-setup.exe"}, "update_source"),
    ({"tag": "v99.0.1"}, "update_gone"),
], ids=["checksum", "another-files-line", "listing-larger", "listing-smaller", "truncated", "longer", "other-host",
        "plain-http", "other-repository", "other-port", "other-tag"])
def test_nothing_runs_and_nothing_is_left_when_the_file_is_not_the_release(releases, page, change, error):
    releases.publish(NEW, **change)
    releases.found(page.home, NEW)
    assert page.post("/api/runtime/update", json={}, headers=OWN).status_code == 200
    job = _ended(page)
    assert (job["state"], job["error"]) == ("failed", error)
    assert releases.launched == [] and page.app.state.closed == []
    assert _left(page.home) in ([], ["state.json"])
    assert not (updates._state(page.home)).get("pending")
    assert all(host in (API_HOST, FILE_HOST, ASSET_HOST) and url.startswith("https://")
               for host, url in releases.hops)


def test_a_name_that_answers_with_an_internal_address_is_never_reached(releases, page, web):
    releases.publish(NEW)
    web.name(API_HOST, "10.0.0.5")
    releases.found(page.home, NEW)
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["error"] == "update_source"
    assert releases.hops == [] and releases.launched == []


@pytest.mark.parametrize("found", ["0.0.1", updates.__version__, "", "99.0.0rc1"])
def test_only_a_newer_version_the_apps_own_check_found_is_installed_whatever_the_request_says(releases, page, found):
    releases.publish(NEW)
    releases.found(page.home, found)
    # The request names a version, an address and a file: none of it is read.
    refused = page.post("/api/runtime/update", headers=OWN, json={
        "version": NEW, "url": f"https://{FILE_HOST}/wangkant/mibo/releases/download/v{NEW}/x.exe", "name": "x.exe"})
    assert (refused.status_code, refused.json()) == (400, {"error": "update_gone"})
    assert releases.hops == [] and releases.launched == [] and updates.job(page.home) is None


def test_only_the_apps_own_window_starts_it_and_never_without_the_token(releases, page):
    releases.publish(NEW)
    releases.found(page.home, NEW)
    for headers in ({welcome.TOKEN_HEADER: TOKEN}, {welcome.TOKEN_HEADER: TOKEN, "X-Mibo-Window": "guess"}):
        refused = page.post("/api/runtime/update", json={}, headers=headers)
        assert (refused.status_code, refused.json()) == (403, {"error": "local_only"})
    for headers in ({"X-Mibo-Window": KEY}, {**OWN, "Origin": "https://other.example"}):
        assert page.post("/api/runtime/update", json={}, headers=headers).status_code == 403
    assert releases.hops == [] and updates.job(page.home) is None


def test_no_tool_and_no_other_part_of_the_app_reaches_the_update():
    package = os.path.dirname(updates.__file__)
    callers = {}
    for folder, _dirs, files in os.walk(package):
        for name in files:
            if name.endswith((".py", ".js")):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as text:
                    source = text.read()
                if "runtime/update\"" in source or "updates.start(" in source or "updates.launch(" in source:
                    callers[os.path.relpath(path, package).replace(os.sep, "/")] = True
    assert sorted(callers) == ["panels/runtime.py", "static/welcome/app.js", "static/welcome/setup/about.js"]
    from mibo import appmap
    assert not any("update" in str(item.route or "") for item in appmap.ITEMS)


def test_a_second_press_while_one_runs_starts_nothing_more(releases, page, site):
    name = releases.publish(NEW)
    releases.found(page.home, NEW)
    pit = site.tarpit(f"/github-production-release-asset/{NEW}/{name}")
    assert page.post("/api/runtime/update", json={}, headers=OWN).status_code == 200
    assert pit.started.wait(10)
    again = page.post("/api/runtime/update", json={}, headers=OWN)
    assert (again.status_code, again.json()) == (400, {"error": "update_running"})
    pit.released.set()
    assert _ended(page)["state"] == "failed"
    assert releases.launched == [] and _left(page.home) in ([], ["state.json"])


def test_a_file_changed_after_its_check_is_not_started(releases, tmp_path):
    setup = tmp_path / "mibo-99.0.0-setup.exe"
    setup.write_bytes(INSTALLER)
    digest = hashlib.sha256(INSTALLER).hexdigest()
    setup.write_bytes(INSTALLER[:-1] + b"!")
    with pytest.raises(updates.Refused, match="update_changed"):
        updates.launch(setup, digest, "setup")
    assert releases.launched == []
    setup.write_bytes(INSTALLER)
    updates.launch(setup, digest, "setup")
    assert releases.launched == ["setup"]


@pytest.mark.skipif(os.name != "nt", reason="the hold is Windows' share mode")
def test_while_the_checked_file_is_held_nothing_can_write_rename_or_delete_it(tmp_path):
    setup = tmp_path / "setup.exe"
    setup.write_bytes(INSTALLER)
    with updates._held(setup) as held:
        assert held.read() == INSTALLER
        with pytest.raises(PermissionError):
            setup.write_bytes(b"swapped")
        with pytest.raises(PermissionError):
            os.replace(setup, tmp_path / "moved.exe")
        with pytest.raises(PermissionError):
            setup.unlink()
    assert setup.read_bytes() == INSTALLER


def test_a_signed_release_must_verify_and_after_one_an_unsigned_one_is_refused(releases, page, monkeypatch):
    public, _ = _sign(b"k" * 32, b"")
    monkeypatch.setattr(updates, "SIGNING_KEY", base64.b64encode(public).decode())
    sums = f"{hashlib.sha256(INSTALLER).hexdigest()}  mibo-{NEW}-setup.exe\n".encode()
    # Another key's signature, and this key's over other bytes: refused before anything runs.
    for secret, signed in ((b"o" * 32, sums), (b"k" * 32, sums + b"\n")):
        releases.publish(NEW, signature=_sign(secret, signed)[1])
        releases.found(page.home, NEW)
        page.post("/api/runtime/update", json={}, headers=OWN)
        assert _ended(page)["error"] == "update_badsig"
    assert releases.launched == []
    releases.publish(NEW, signature=_sign(b"k" * 32, sums)[1])
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["state"] == "installing" and len(releases.launched) == 1
    # The next start is the signed release: from then on this home takes signed releases alone.
    monkeypatch.setattr(updates, "__version__", NEW)
    updates.settle(page.home)
    assert updates._state(page.home)["signed"] is True
    updates._jobs.clear()
    releases.publish("99.0.1")
    releases.found(page.home, "99.0.1")
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["error"] == "update_unsigned" and len(releases.launched) == 1


def test_without_a_key_in_the_app_a_release_is_held_to_its_checksum_alone(releases, page):
    assert updates.SIGNING_KEY == ""
    releases.publish(NEW, signature=b"\x00" * 64)
    releases.found(page.home, NEW)
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["state"] == "installing" and len(releases.launched) == 1
    assert updates._state(page.home)["pending"]["signed"] is False


def test_the_disk_image_is_checked_the_same_way_and_opened_for_the_person_to_drag(releases, page, monkeypatch):
    monkeypatch.setattr(updates, "way", lambda: "macos")
    name = releases.publish(NEW, "macos")
    releases.found(page.home, NEW)
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["state"] == "opened"
    assert releases.launched == [["/usr/bin/open", str(page.home / "runtime" / "updates" / name)]]
    assert page.app.state.closed == [], "the person quits it to drag the new one in"
    updates._jobs.clear()
    releases.publish("99.0.1", "macos", sums=b"0" * 64 + b"  mibo-99.0.1-macos-arm64.dmg\n")
    releases.found(page.home, "99.0.1")
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["error"] == "update_mismatch" and len(releases.launched) == 1


@pytest.mark.parametrize("winerror, error", [(225, "update_blocked"), (4551, "update_blocked"),
                                             (1260, "update_blocked"), (740, "update_failed")])
def test_a_blocked_installer_leaves_this_version_running_and_says_so(releases, page, monkeypatch, winerror, error):
    def refuse(command, **named):
        raised = OSError(f"WinError {winerror}")
        raised.winerror = winerror
        raise raised

    releases.publish(NEW)
    releases.found(page.home, NEW)
    monkeypatch.setattr(updates, "subprocess", types.SimpleNamespace(**{**vars(updates.subprocess), "Popen": refuse}))
    page.post("/api/runtime/update", json={}, headers=OWN)
    assert _ended(page)["error"] == error
    assert page.app.state.closed == [] and _left(page.home) == ["state.json"]
    assert not updates._state(page.home).get("pending")
