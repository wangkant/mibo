"""What an installed copy needs: one version, the shipped files, the seed resolver, the CLI."""
from __future__ import annotations

import re
import runpy
from pathlib import Path

import pytest

import persona_agent
from persona_agent import cli, home, paths

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> str:
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_one_version_for_the_package_and_the_metadata() -> None:
    declared = re.search(r'^version = "([^"]+)"', _pyproject(), re.MULTILINE).group(1)
    assert declared == persona_agent.__version__, (declared, persona_agent.__version__)


def test_the_classifiers_match_a_stable_release() -> None:
    text = _pyproject()
    assert "Development Status :: 5 - Production/Stable" in text
    for minor in range(10, 15):
        assert f"Programming Language :: Python :: 3.{minor}" in text
    assert 'requires-python = ">=3.10"' in text


def _dependencies() -> list[str]:
    block = re.search(r"^dependencies = \[(.*?)^\]", _pyproject(), re.MULTILINE | re.DOTALL).group(1)
    return re.findall(r'^\s*"([^"]+)",', block, re.MULTILINE)


def test_the_dependencies_have_floors_and_stay_on_pydantic_2() -> None:
    requirements = _dependencies()
    assert any(re.fullmatch(r"pydantic>=2[.\d]*,<3", ln) for ln in requirements), requirements
    assert all(">=" in ln for ln in requirements), "every dependency has a floor"


def test_the_window_toolkit_is_required_only_where_the_system_has_one() -> None:
    """Windows ships WebView2; macOS and Linux opt in with the `app` extra,
    so a server install never needs a GUI toolkit."""
    webview = [ln for ln in _dependencies() if ln.startswith("pywebview")]
    assert len(webview) == 1 and webview[0].endswith("; sys_platform == 'win32'"), webview
    extra = re.findall(r'"([^"]+)"', re.search(r"^app = \[(.*)\]$", _pyproject(), re.MULTILINE).group(1))
    assert [spec.split(";")[1].strip() for spec in extra] == [
        "sys_platform != 'linux'", "sys_platform == 'linux'"], extra
    assert extra[1].startswith("pywebview[qt]>="), "pywebview alone brings Linux no toolkit"


def test_the_workflows_take_pytest_and_ruff_from_the_dev_extra() -> None:
    """Their versions are written once, in pyproject.toml."""
    extra = re.search(r"^dev = \[(.*?)\]", _pyproject(), re.MULTILINE).group(1)
    tools = [re.match(r"[A-Za-z0-9_.-]+", spec).group(0)
             for spec in re.findall(r'"([^"]+)"', extra)]
    # playwright: the `web` extra, so the walks on the web are tested. (The MCP SDK is a dependency of the
    # app itself now, so the tests have it without the extra.)
    assert tools == ["pytest", "ruff", "playwright"], tools
    web = re.search(r"^web = \[(.*?)\]", _pyproject(), re.MULTILINE).group(1)
    assert re.findall(r'"([^"]+)"', web) == [re.findall(r'"(playwright[^"]*)"', extra)[0]]
    for name in ("ci.yml", "release.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert 'python -m pip install -e ".[dev]"' in text, name
        for tool in tools:
            assert not re.search(rf'["\s]{tool}\s*[<>=~!]', text), (
                f"{name} writes a version for {tool}")


def test_the_wheel_bundles_the_shared_files_under_bundled() -> None:
    """hatchling maps data/ and .env.example under persona_agent/_bundled,
    where home.resource() looks in an installed copy; CI installs the built
    wheel and reads them back."""
    text = _pyproject()
    assert '"data" = "persona_agent/_bundled/data"' in text
    assert '".env.example" = "persona_agent/_bundled/.env.example"' in text
    wheel = re.search(r"^\[tool\.hatch\.build\.targets\.wheel\]\n(.*?)\n\n", text,
                      re.MULTILINE | re.DOTALL).group(1)
    for included in ("persona_agent", "data"):
        assert f'"{included}"' in wheel, included


def test_the_wheel_leaves_bytecode_caches_out() -> None:
    # hatchling skips what .gitignore ignores.
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "__pycache__/" in ignored and "*.pyc" in ignored


def test_resource_reads_the_checkout_here_and_the_bundle_when_installed(
        monkeypatch) -> None:
    assert home.is_checkout()
    assert home.resource("data", "x") == ROOT / "data" / "x"
    monkeypatch.setattr(home, "is_checkout", lambda path=home.CHECKOUT: False)
    assert home.resource("data", "x") == home.PACKAGE_DIR / "_bundled" / "data" / "x"


def test_a_folder_is_a_home_only_with_its_own_settings(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    assert not home.looks_like_home(tmp_path), "a stray data/ folder is not a home"
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "persona.txt").write_text("", encoding="utf-8")
    assert home.looks_like_home(tmp_path)
    assert home.looks_like_home(ROOT)


def test_seeds_prefer_the_home_then_fall_back_to_the_shipped_copy(
        monkeypatch, tmp_path: Path) -> None:
    shipped = tmp_path / "shipped"
    (shipped / "data" / "personas").mkdir(parents=True)
    (shipped / "data" / "output_filter.en.json").write_text("shipped", encoding="utf-8")
    (shipped / "data" / "examples.jsonl").write_text("shipped", encoding="utf-8")
    (shipped / "data" / "personas" / "mibo.en.txt").write_text("", encoding="utf-8")
    deployment = tmp_path / "home"
    (deployment / "data").mkdir(parents=True)
    monkeypatch.setattr(paths, "ROOT", deployment)
    monkeypatch.setattr(paths, "resource", lambda *parts: shipped.joinpath(*parts))

    assert paths.seed_file("output_filter.en.json") == shipped / "data" / "output_filter.en.json"
    assert paths.seed_file("personas") == shipped / "data" / "personas"
    assert (paths.resolve_seed_lang_file("output_filter", "json", "en")
            == shipped / "data" / "output_filter.en.json")
    assert (paths.resolve_seed_lang_file("examples", "jsonl", "zh")
            == shipped / "data" / "examples.jsonl")

    (deployment / "data" / "output_filter.json").write_text("mine", encoding="utf-8")
    assert (paths.resolve_seed_lang_file("output_filter", "json", "en")
            == deployment / "data" / "output_filter.json"), "the home's own copy wins"
    (deployment / "data" / "output_filter.en.json").write_text("mine", encoding="utf-8")
    assert paths.seed_file("output_filter.en.json") == deployment / "data" / "output_filter.en.json"
    assert (paths.resolve_seed_lang_file("missing", "json", "en")
            == deployment / "data" / "missing.json")


def test_runtime_state_stays_under_the_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.delenv("AGENT_RUNTIME_DIR", raising=False)
    assert paths.runtime_dir() == (tmp_path / "runtime").resolve()


def test_the_cli_prints_its_version(capsys) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"personagent {persona_agent.__version__}"


def test_the_subcommands_this_package_serves_resolve() -> None:
    import importlib

    for name in ("start",):
        module, func, _help = cli.COMMANDS[name]
        assert callable(getattr(importlib.import_module(module), func)), name


def test_release_notes_come_from_the_changelog_section_of_the_tag() -> None:
    notes = runpy.run_path(str(ROOT / "tools" / "release_notes.py"), run_name="notes_under_test")
    changelog = "\n".join([
        "# Changelog", "", "## [Unreleased]", "", "- next", "",
        "## [1.0.0] - 2026-10-10", "", "### Added", "", "- `personagent` command", "",
        "## [0.4.0] - 2026-09-24", "", "- older", "",
        "[1.0.0]: https://github.com/wangkant/personagent/releases/tag/v1.0.0", ""])
    assert notes["changelog_section"](changelog, "1.0.0") == (
        "### Added\n\n- `personagent` command\n")
    with pytest.raises(ValueError, match="no '## .2.0.0.' section"):
        notes["changelog_section"](changelog, "2.0.0")
    assert notes["project_version"](_pyproject()) == persona_agent.__version__
    assert notes["main"](["v0.0.0-not-this"]) == 1
