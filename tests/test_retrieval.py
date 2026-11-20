"""The output filter's hot reload: a running agent applies what a cold
process would load from the same file.

Run from the repo root:

    python -m pytest tests/test_retrieval.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from persona_agent.agent import Agent

from helpers import check, isolated_agent


def make_agent(tmp: Path) -> Agent:
    return isolated_agent(tmp, persona_name="B")


def test_json_config_reload_tracks_restores_and_failed_edits() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        a = make_agent(tmp)
        a.output_filter_file = tmp / "filters.json"

        def write_configs(word, stamp):
            a.output_filter_file.write_text(json.dumps([
                {"name": "block", "pattern": word},
            ]), encoding="utf-8")
            os.utime(a.output_filter_file, ns=(stamp, stamp))

        def verify(word, label):
            check(f"config reload: filter {label}",
                  a._apply_output_filter(word) == "")

        stamp = 1_700_000_000_000_000_000
        write_configs("first", stamp)
        verify("first", "initial load")
        write_configs("restored", stamp - 10_000_000_000)
        verify("restored", "accepts older restored file")
        write_configs("changed-size", stamp - 10_000_000_000)
        verify("changed-size", "accepts size change with same mtime")

        a.output_filter_file.write_text("{broken", encoding="utf-8")
        verify("changed-size", "retains last valid config after malformed edit")
        write_configs("repaired", stamp + 10_000_000_000)
        verify("repaired", "recovers after malformed edit")
        a.output_filter_file.unlink()
        check("config reload: deleted filter clears cache",
              a._apply_output_filter("repaired") == "repaired")
        write_configs("recreated", stamp)
        verify("recreated", "loads recreated file")


def test_json_config_stat_failure_preserves_valid_cache() -> None:
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        a = make_agent(tmp)
        a.output_filter_file = tmp / "filters.json"
        a.output_filter_file.write_text(json.dumps([
            {"name": "block", "pattern": "blocked"},
        ]), encoding="utf-8")
        check("config I/O: initial filter trims", a._apply_output_filter("blocked") == "")
        original_stat = Path.stat

        def unavailable(path, *args, **kwargs):
            if path == a.output_filter_file:
                raise PermissionError("temporarily unavailable")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", unavailable):
            check("config I/O: stat failure does not disable a loaded filter",
                  a._apply_output_filter("blocked") == "")
        check("config I/O: filter recovers when readable",
              a._apply_output_filter("blocked") == "")
