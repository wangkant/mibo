"""Seed data kept fresh on disk: the filters."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("agent")


class DataViews:
    @staticmethod
    def _pool_stamp(paths, *, strict: bool = False) -> tuple:
        """Identity, nanosecond mtime and size per file; `strict` raises on an
        unreadable (not absent) file."""
        out: list = []
        for p in paths:
            try:
                st = p.stat()
                out.append((st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size))
            except FileNotFoundError:
                out.append((0, 0, 0, 0))
            except OSError:
                if strict:
                    raise
                out.append((0, 0, 0, 0))
        return tuple(out)

    def _reload_json_if_stale(self, path: Path, attr: str, parse,
                              name: str, unit: str) -> None:
        """Re-read a changed JSON config; a missing file empties
        the cache. `parse(data)` returns the entries to cache."""
        try:
            stamp = self._pool_stamp((path,), strict=True)
        except OSError as exc:
            logger.warning("[Agent] %s stat failed: %s", name, exc)
            return
        if stamp == ((0, 0, 0, 0),):
            setattr(self, attr + "_cache", [])
            setattr(self, attr + "_stamp", stamp)
            return
        if stamp == getattr(self, attr + "_stamp"):
            return
        try:
            entries = parse(json.loads(path.read_text(encoding="utf-8-sig")))
            setattr(self, attr + "_cache", entries)
            setattr(self, attr + "_stamp", stamp)
            logger.info("[Agent] %s loaded %d %s", name, len(entries), unit)
        except Exception as e:
            logger.warning("[Agent] %s.json load failed: %s", name, e)

    def _reload_filters_if_stale(self) -> None:
        self._reload_json_if_stale(self.output_filter_file, "_filters", parse_filters,
                                   "output_filter", "rules")

    def _apply_output_filter(self, reply: str) -> str:
        """The reply with the person's own rules applied: each rule's matches
        replaced by its `replacement`. The app ships no rules."""
        self._reload_filters_if_stale()
        for f in self._filters_cache:
            reply = f["regex"].sub(f["replacement"], reply)
        return reply


def parse_filters(data) -> list:
    """The output filter rules the agent applies: a pattern and what replaces
    its matches (nothing, unless the rule says). A rule whose pattern does
    not compile is left out. A file of the wrong shape raises."""
    raw = data.get("filters", []) if isinstance(data, dict) else data
    compiled = []
    for f in raw:
        pat = f.get("pattern")
        if not pat:
            continue
        try:
            compiled.append({
                "name": f.get("name", "?"),
                "regex": re.compile(pat, re.IGNORECASE | re.DOTALL),
                "replacement": f.get("replacement", ""),
            })
        except re.error as e:
            logger.warning("[Agent] output_filter '%s' regex compile failed: %s",
                           f.get("name"), e)
    return compiled
