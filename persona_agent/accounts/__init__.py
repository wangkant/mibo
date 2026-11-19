"""The person's own accounts the character reads, one connector each (see base.py).

CONNECTORS is every connector class, in the order the page lists them: each
module's Connector subclasses that have a key, as the module defines them.
"""
from __future__ import annotations

import importlib

from .base import AccountError, Connector

MODULES = ("outlook", "qqbot", "wechat", "slack", "github", "matrix", "youtube", "sites", "discord_bot")


def _classes(name: str) -> list[type[Connector]]:
    module = importlib.import_module(f"{__name__}.{name}")
    return [c for c in vars(module).values()
            if isinstance(c, type) and issubclass(c, Connector) and c.__module__ == module.__name__ and c.key]


CONNECTORS: list[type[Connector]] = [c for name in MODULES for c in _classes(name)]

__all__ = ["AccountError", "CONNECTORS", "Connector"]
