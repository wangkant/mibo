"""Settings 1.0 retired: refuse to start on them, rename them with `doctor --fix`."""
from __future__ import annotations

import os
import sys
from pathlib import Path


from persona_agent import cli

ROOT = Path(__file__).resolve().parents[1]
OLD_ENV = (
    "# my bot\n"
    "LLM_API_KEY=sk-x\n"
    "QQ_GROUPS=111,222  # the groups\n"
    "export OWNER_QQ=42\n"
    "PORT=9000\n"
    "BOT_NAME=Mira\n")


def _home(tmp_path: Path, text: str = OLD_ENV) -> Path:
    (tmp_path / ".env").write_text(text, encoding="utf-8", newline="")
    return tmp_path


def test_home_is_accepted_after_the_command_too(monkeypatch, tmp_path: Path) -> None:
    seen: dict = {}

    def probe(argv, prog):
        seen.update(argv=argv, prog=prog, home=os.environ.get("AGENT_HOME"))
        return 0

    monkeypatch.setitem(cli.COMMANDS, "chat", (__name__, "probe", "x"))
    monkeypatch.setattr(sys.modules[__name__], "probe", probe, raising=False)
    monkeypatch.setenv("AGENT_HOME", "restored by monkeypatch")
    for argv in (["chat", "--home", str(tmp_path), "--x"], ["chat", "--x", f"--home={tmp_path}"],
                 ["--home", str(tmp_path), "chat", "--x"]):
        seen.clear()
        os.environ.pop("AGENT_HOME", None)
        assert cli.main(argv) == 0
        assert seen["argv"] == ["--x"], argv
        assert Path(seen["home"]) == tmp_path.resolve(), argv
