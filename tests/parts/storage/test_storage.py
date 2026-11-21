"""What the app keeps on disk survives (mibo/storage.py, mibo/paths.py): one running copy per home, no torn
or lost row when several processes write, whole replacements readable only by the person, bad rows set
aside, nothing written outside the home, and state that a power cut damaged started over."""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import stat
from pathlib import Path

import pytest

from mibo import paths, storage


def _append_worker(path: str, worker: int, count: int) -> None:
    for index in range(count):
        storage.append_jsonl(Path(path), {"worker": worker, "index": index})


def test_a_second_running_copy_is_refused_by_the_home_lock(tmp_path: Path) -> None:
    first, second = storage.RuntimeInstanceLock(tmp_path), storage.RuntimeInstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(storage.LockUnavailable):
            second.acquire()
    finally:
        first.release()
    # Free again once the first lets go.
    second.acquire()
    second.release()


def test_appends_from_several_processes_lose_and_tear_no_row(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    workers, per_worker = 4, 40
    processes = [multiprocessing.Process(target=_append_worker, args=(str(path), worker, per_worker))
                 for worker in range(workers)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
    assert [process.exitcode for process in processes] == [0] * workers
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == workers * per_worker
    assert {(row["worker"], row["index"]) for row in rows} == {
        (worker, index) for worker in range(workers) for index in range(per_worker)}


def test_a_replacement_is_whole_leaves_no_temporary_file_and_is_private(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    storage.atomic_write_text(path, '{"version":1}\n')
    storage.atomic_write_text(path, '{"version":2}\n')
    assert path.read_text(encoding="utf-8") == '{"version":2}\n'
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_bad_rows_are_set_aside_without_rewriting_the_file(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"schema":1,"value":"ok"}\n'
                    'not json\n'
                    '{"schema":99,"value":"future"}\n'
                    '["not","an","object"]\n', encoding="utf-8")

    def validate(row: dict) -> str | None:
        if row.get("schema") != 1:
            return "unsupported schema"
        return None if isinstance(row.get("value"), str) else "value must be a string"

    result = storage.read_validated_jsonl(path, validate)
    assert result.rows == [{"schema": 1, "value": "ok"}]
    assert sorted(item.reason for item in result.quarantined) == [
        "invalid json", "row is not an object", "unsupported schema"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 4


def test_the_runtime_folder_never_leaves_the_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "ROOT", tmp_path.resolve())
    monkeypatch.setenv("AGENT_RUNTIME_DIR", "state/runtime")
    assert paths.runtime_dir() == (tmp_path / "state" / "runtime").resolve()
    inside = (tmp_path / "absolute-runtime").resolve()
    monkeypatch.setenv("AGENT_RUNTIME_DIR", str(inside))
    assert paths.runtime_dir() == inside
    for outside in (str((tmp_path.parent / "outside").resolve()), "../escape"):
        monkeypatch.setenv("AGENT_RUNTIME_DIR", outside)
        with pytest.raises(ValueError):
            paths.runtime_dir()
    monkeypatch.setenv("AGENT_RUNTIME_DIR", "runtime")
    with pytest.raises(ValueError):
        paths.resolve_runtime_state_file("../../outside.json")
    monkeypatch.delenv("AGENT_RUNTIME_DIR")
    assert paths.runtime_dir() == (tmp_path / "runtime").resolve()


def test_appended_rows_are_byte_exact_with_lf_endings(tmp_path: Path) -> None:
    """Read as bytes: splitlines would take a CRLF for a line break and hide the very fault."""
    path = tmp_path / "rows.jsonl"
    written = storage.append_jsonl(path, {"x": 1})
    raw = path.read_bytes()
    assert raw == b'{"x":1}\n'
    assert written == len(raw)
    storage.append_jsonl(path, {"y": 2})
    assert path.read_bytes() == b'{"x":1}\n{"y":2}\n'


def test_a_rebuildable_file_loads_or_is_moved_aside(tmp_path: Path, caplog) -> None:
    """State written without fsync can come back empty or cut off after a power cut: its loader starts
    empty and keeps the file for a look."""
    caplog.set_level(logging.WARNING, logger="agent.storage")

    def as_dict(data):
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data

    assert storage.load_rebuildable_json(tmp_path / "absent.json", as_dict) is None
    assert not caplog.records and not list(tmp_path.iterdir())
    good = tmp_path / "good.json"
    good.write_text('{"a": 1}', encoding="utf-8")
    assert storage.load_rebuildable_json(good, as_dict) == {"a": 1}
    assert good.read_text(encoding="utf-8") == '{"a": 1}' and not caplog.records

    path, aside = tmp_path / "state.json", tmp_path / "state.json.corrupt"
    cases = (
        ("zero-byte", b"", as_dict),
        ("truncated", b'{"a": {"b": [1, 2', as_dict),
        ("not utf-8", b'{"a": "' + bytes([0xff, 0xfe]) + b'"}', as_dict),
        ("wrong top-level type", b"[1, 2]", as_dict),
        ("missing key", b"{}", lambda data: data["rows"]),
        ("wrong inner type", b'{"rows": 3}', lambda data: sorted(data["rows"])),
        ("not a mapping", b"7", lambda data: data.items()),
    )
    for label, blob, parse in cases:
        caplog.clear()
        path.write_bytes(blob)
        assert storage.load_rebuildable_json(path, parse) is None, label
        # Moved aside, replacing an older one, with one warning naming the file.
        assert not path.exists() and aside.read_bytes() == blob, label
        said = [r.getMessage() for r in caplog.records]
        assert len(said) == 1 and str(path) in said[0], label
    assert sorted(p.name for p in tmp_path.iterdir()) == ["good.json", "state.json.corrupt"]


def test_a_rebuildable_loader_hides_only_a_bad_file(tmp_path: Path, caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="agent.storage")
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")

    def broken(data):
        raise RuntimeError("a bug in the loader")

    # A loader bug is not mistaken for a bad file.
    with pytest.raises(RuntimeError):
        storage.load_rebuildable_json(path, broken)
    assert path.exists() and not (tmp_path / "state.json.corrupt").exists()
    # A file that cannot be read still stops.
    folder = tmp_path / "folder.json"
    folder.mkdir()
    with pytest.raises(OSError):
        storage.load_rebuildable_json(folder, dict)
    assert folder.is_dir()

    def locked(src, dst):
        raise PermissionError("in use")

    # A bad file that cannot be moved still starts empty, with the one warning saying so.
    path.write_bytes(b"")
    caplog.clear()
    with monkeypatch.context() as patched:
        patched.setattr(storage.os, "replace", locked)
        assert storage.load_rebuildable_json(path, dict) is None
    said = [r.getMessage() for r in caplog.records]
    assert path.exists() and len(said) == 1 and "could not be moved aside" in said[0]


def test_a_replace_waits_out_a_reader_on_windows(tmp_path: Path, monkeypatch) -> None:
    """The page reads .env on every poll; Windows refuses to replace an open file."""
    target = tmp_path / ".env"
    target.write_text("old", encoding="utf-8")
    real, refusals = os.replace, [PermissionError(5, "Access is denied")] * 3

    def busy(source, destination):
        if refusals:
            raise refusals.pop()
        real(source, destination)

    monkeypatch.setattr(storage.os, "replace", busy)
    monkeypatch.setattr(storage, "_WINDOWS", True)
    monkeypatch.setattr(storage.time, "sleep", lambda seconds: None)
    storage.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new" and not refusals
