"""How each way of running is updated (mibo/updates.py): which way this copy is, read from the copy itself; the
command for the ways the app does not update itself; what the installer is told (packaging/windows/mibo.iss);
what the start after an update says; and the release workflow that signs and tries the update."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest
import yaml

from mibo import ed25519, home, updates, welcome

ROOT = Path(__file__).resolve().parents[3]


def _frozen_at(monkeypatch, program: Path, platform: str) -> None:
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))
    monkeypatch.setattr(sys, "platform", platform)


def test_the_installers_copy_is_known_by_its_uninstaller_beside_the_program(monkeypatch, tmp_path):
    _frozen_at(monkeypatch, tmp_path / "Mibo" / "mibo.exe", "win32")
    assert updates.way() == "zip"
    (tmp_path / "Mibo" / "unins000.exe").write_bytes(b"")
    assert updates.way() == "zip", "the uninstaller's record comes with it"
    (tmp_path / "Mibo" / "unins000.dat").write_bytes(b"")
    assert updates.way() == "installer"
    assert updates.command("installer") == ""


def test_the_mac_app_is_known_by_its_bundle_and_any_other_frozen_copy_by_nothing(monkeypatch, tmp_path):
    _frozen_at(monkeypatch, tmp_path / "Applications" / "mibo.app" / "Contents" / "MacOS" / "mibo", "darwin")
    assert updates.way() == "macos"
    assert updates.asset("1.2.3", "macos") == "mibo-1.2.3-macos-arm64.dmg"
    _frozen_at(monkeypatch, tmp_path / "loose" / "mibo", "darwin")
    assert updates.way() == "other"
    _frozen_at(monkeypatch, tmp_path / "linux" / "mibo", "linux")
    assert updates.way() == "other"


def test_a_python_install_is_told_its_own_pip_and_a_checkout_its_git(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert updates.way() == ("checkout" if home.is_checkout() else "pip")
    assert updates.command("checkout") == f'git -C "{home.CHECKOUT}" pull'
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Python313\python.exe")
    assert updates.command("pip") == r'"C:\Program Files\Python313\python.exe" -m pip install -U mibo'
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    assert updates.command("pip") == "/usr/bin/python3 -m pip install -U mibo"
    monkeypatch.setattr(home, "is_checkout", lambda path=home.CHECKOUT: False)
    assert updates.way() == "pip"


def test_the_installer_is_told_to_wait_for_the_app_and_open_it_again_on_its_home():
    """The switches updates.installer_command passes are the ones mibo.iss reads."""
    script = (ROOT / "packaging" / "windows" / "mibo.iss").read_text(encoding="utf-8")
    command = updates.installer_command(Path("C:/x/mibo-9.9.9-setup.exe"), Path("C:/home"))
    for switch in ("/WAITPID=", "/RESTARTHOME="):
        assert switch in command and "{param:" + switch[1:-1] in script
    assert "Check: Restarting" in script and "function PrepareToInstall" in script
    assert "procedure DeinitializeSetup" in script, "an update that did not install opens the old copy again"
    assert "PrivilegesRequired=lowest" in script and "/VERYSILENT" in command and "runas" not in command


def test_the_start_after_an_update_says_what_became_of_it_once(tmp_path, monkeypatch):
    folder = tmp_path / "runtime" / "updates"
    folder.mkdir(parents=True)
    monkeypatch.setattr(updates, "TIDY_EVERY_S", 0.01)
    (folder / "state.json").write_text(json.dumps({"pending": {"version": updates.__version__, "from": "0.1.0"}}))
    (folder / "mibo-9.9.9-setup.exe").write_bytes(b"x")
    (folder / "setup.log").write_text("ok")
    (folder / "mibo-9.9.9-setup.exe.1a2b.part").write_bytes(b"x")
    updates.settle(tmp_path)
    assert updates.outcome(tmp_path) == {"version": updates.__version__, "from": "0.1.0", "ok": True,
                                         "url": updates.RELEASE_URL.format(version=updates.__version__)}
    workspace = welcome.Workspace(tmp_path)
    try:
        assert workspace.summary()["updated"]["ok"] is True, "the chat says it in one line"
    finally:
        workspace.close()
    _gone_but_state(folder)
    updates.settle(tmp_path)
    assert updates.outcome(tmp_path) is None, "said in the start after the update, not again"


def test_an_update_that_did_not_install_keeps_its_log_and_says_this_version(tmp_path, monkeypatch):
    folder = tmp_path / "runtime" / "updates"
    folder.mkdir(parents=True)
    monkeypatch.setattr(updates, "TIDY_EVERY_S", 0.01)
    (folder / "state.json").write_text(json.dumps({"pending": {"version": "99.0.0", "from": updates.__version__}}))
    (folder / "setup.log").write_text("failed")
    (folder / "mibo-99.0.0-setup.exe").write_bytes(b"x")
    updates.settle(tmp_path)
    found = updates.outcome(tmp_path)
    assert found["ok"] is False and found["url"].endswith("/v99.0.0")
    _gone_but_state(folder, "setup.log")
    updates.dismiss(tmp_path)
    assert updates.outcome(tmp_path) is None


def _gone_but_state(folder: Path, *kept: str) -> None:
    deadline = time.monotonic() + 5
    while sorted(p.name for p in folder.iterdir()) != sorted({"state.json", *kept}):
        assert time.monotonic() < deadline, sorted(p.name for p in folder.iterdir())
        time.sleep(0.01)


def test_the_signature_check_is_rfc_8032s():
    # RFC 8032, 7.1, test 1: the empty message.
    public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    signature = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e"
                              "39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert ed25519.verify(public, b"", signature)
    assert not ed25519.verify(public, b"x", signature)
    assert not ed25519.verify(public, b"", signature[:32] + (int.from_bytes(signature[32:], "little")
                                                             + ed25519.L).to_bytes(32, "little"))
    assert not ed25519.verify(public[:31], b"", signature)
    assert updates.SIGNING_KEY == "" or len(base64.b64decode(updates.SIGNING_KEY)) == 32


def test_the_release_signs_its_checksums_and_tries_the_update_before_publishing():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    windows = [step.get("run", "") for step in workflow["jobs"]["windows-installer"]["steps"]]
    assert any("tools/update_e2e.py run" in run for run in windows)
    assert "windows-installer" in workflow["jobs"]["github-release"]["needs"]
    assert "windows-installer" in workflow["jobs"]["pypi"]["needs"]
    signing = [step for step in workflow["jobs"]["github-release"]["steps"] if step.get("name") == "Sign SHA256SUMS.txt"]
    assert signing and signing[0]["env"] == {"RELEASE_SIGNING_KEY": "${{ secrets.RELEASE_SIGNING_KEY }}"}
    assert "pkeyutl -verify" in signing[0]["run"] and "SHA256SUMS.txt.sig" in signing[0]["run"]


@pytest.mark.parametrize("version, newer", [("0.0.0", False), (updates.__version__, False), ("999.0.0", True)])
def test_the_update_offers_only_a_newer_plain_release(version, newer):
    assert updates.newer(version) is newer
