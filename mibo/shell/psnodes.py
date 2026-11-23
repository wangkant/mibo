"""Reading the nodes parse.ps1 hands back: a value or a list, a bound parameter, a switch, a command's name
after aliases and its arguments as plain words."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .paths import Paths


def _items(value) -> list:
    """A field that holds one value or a list, as a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _bound(node: dict, name: str):
    """The argument bound to the parameter `name`, or None."""
    got = (node.get("bound") or {}).get(name)
    return got.get("el") if isinstance(got, dict) else None


def _switch(node: dict, name: str) -> bool:
    got = (node.get("bound") or {}).get(name)
    return isinstance(got, dict) and str(got.get("cv") or "True").lower() != "false"


def _named(node: dict) -> tuple[str, str, str]:
    """(canonical lowercased name, command type, program path) of a command after aliases."""
    res = node.get("res") or {}
    name = str(res.get("n") or node.get("name") or "")
    return name.lower(), str(res.get("ct") or ""), str(res.get("path") or "")


def _plain_args(node: dict, paths: Paths) -> list[str] | None:
    """A command's arguments as written (parameters with their dash), or None when one is computed."""
    out = []
    for el in _items(node.get("args")):
        if isinstance(el, dict) and el.get("k") == "p":
            out.append("-" + str(el.get("v") or ""))
            continue
        got = paths.strings(el)
        if got is None:
            return None
        out += got
    return out
