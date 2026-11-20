"""Secrets in the system's credential store through keyring: Windows Credential Manager, the macOS
keychain, the Secret Service on Linux. Nothing of them is written to a file of the home.

Each home has a service name of its own (Mibo/<hash of its path>), so two homes on one computer never
share a value. Windows keeps at most 2560 bytes (1280 characters) per entry, so a longer value, such as
an OAuth token, is kept in parts: the first entry says how many.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import keyring

#: Characters per entry, inside Windows' limit.
PART = 1200
# Starts the first entry of a value kept in parts: \x01<count>\x01<first part>.
_PARTS = "\x01"


def service(home) -> str:
    path = str(Path(home).resolve()).lower()
    return "Mibo/" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]


def get(home, name: str) -> str:
    """The value kept under `name`, or "" when there is none."""
    where = service(home)
    first = keyring.get_password(where, name) or ""
    if not first.startswith(_PARTS):
        return first
    count, _, text = first[1:].partition(_PARTS)
    return text + "".join(keyring.get_password(where, f"{name}#{i}") or "" for i in range(1, int(count)))


def put(home, name: str, value: str) -> None:
    """Keeps `value` under `name`; an empty value removes it."""
    delete(home, name)
    if not value:
        return
    where = service(home)
    parts = [value[i:i + PART] for i in range(0, len(value), PART)]
    if len(parts) == 1:
        keyring.set_password(where, name, value)
        return
    keyring.set_password(where, name, f"{_PARTS}{len(parts)}{_PARTS}{parts[0]}")
    for i, part in enumerate(parts[1:], 1):
        keyring.set_password(where, f"{name}#{i}", part)


def put_many(home, values: dict) -> None:
    for name, value in values.items():
        put(home, name, value)


def delete(home, name: str) -> None:
    where = service(home)
    first = keyring.get_password(where, name)
    if first is None:
        return
    count = int(first[1:].partition(_PARTS)[0]) if first.startswith(_PARTS) else 1
    for key in [name, *(f"{name}#{i}" for i in range(1, count))]:
        keyring.delete_password(where, key)
