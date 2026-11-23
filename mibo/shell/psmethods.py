"""Sorting the .NET parts of a PowerShell command: type names, method calls, members called by name and the
objects New-Object makes. The part of pssort.Sorter that knows .NET (*_TYPES and *_METHODS in pstables)."""
from __future__ import annotations

from urllib.parse import urlsplit

from .paths import Paths, _local_host
from .psnodes import _bound, _items
from .pstables import (
    FILE_READ_METHODS,
    FILE_TYPES,
    GENERIC_COLLECTIONS,
    METHOD_KINDS,
    NET_METHODS,
    NET_TYPES,
    NEVER_METHODS,
    NEVER_TYPES,
    PLAIN_OBJECTS,
    PURE_METHODS,
    SAFE_MEMBERS,
    SAFE_TYPES,
    STRING_MEMBERS,
    STRING_ONLY_METHODS,
)


class Methods:
    """Mixed into pssort.Sorter, whose add(), loopback(), provider(), literal_places(), paths and origin these
    use."""

    def type_name(self, name: str) -> None:
        low = name.lower()
        if _never_type(low):
            self.add("hidden", "hidden", f"uses the .NET type [{name}], which can run code that cannot be read first")
        elif _net_type(low):
            self.add("network", "net", f"uses [{name}] to reach the network", sends=True)

    def method(self, node: dict) -> None:
        member = str(node.get("member") or "").lower()
        on = str(node.get("on") or "").lower()
        text = str(node.get("text") or "")[:80]
        args = _items(node.get("args"))
        first = args[0] if args else None
        if member in ("foreach", "where") and isinstance(first, dict) and first.get("type") not in (
                "ScriptBlockExpressionAst", "TypeExpressionAst"):
            # .ForEach('Delete') calls that method on every item.
            self.member(first, text)
            return
        if on in FILE_TYPES and member != "exists":
            self.file_method(member, node, first)
            return
        if on in ("environment", "system.environment") and member.startswith("getenvironmentvariable") and (
                int(node.get("nargs") or 0) >= 2 or (member.endswith("s") and int(node.get("nargs") or 0) >= 1)):
            self.add("secrets", "secrets", "reads the person's saved environment variables, where programs keep keys")
            return
        if not member:
            self.add("hidden", "hidden", f"calls a method whose name is computed ({text})")
        elif member in METHOD_KINDS:
            kind = METHOD_KINDS[member]
            self.add(kind, kind, f"calls .{node.get('member')}()")
        elif member in STRING_ONLY_METHODS and not self.stringy(node):
            self.add("unknown", "unknown", f"calls .{node.get('member')}() on something that may be a file ({text})")
        elif member in NEVER_METHODS:
            self.add("hidden", "hidden", f"calls .{node.get('member')}(), which runs or loads code that cannot be read first")
        elif member in NET_METHODS:
            url = " ".join(self.paths.strings(first) or []) if first is not None else ""
            host = (urlsplit(url).hostname or "").lower()
            if host and _local_host(host):
                self.loopback(host)
            else:
                self.add("network", "net", f"calls .{node.get('member')}() to reach {host or 'the network'}",
                         host=host or "?", sends=True)
        elif node.get("static") and on and on not in SAFE_TYPES:
            self.add("unknown", "unknown", f"calls [{node.get('on')}]::{node.get('member')}()",
                     paths=self.literal_places(node), write=True)
        elif member not in PURE_METHODS:
            self.add("unknown", "unknown", f"calls .{node.get('member')}() ({text})",
                     paths=self.literal_places(node), write=True)

    def stringy(self, node: dict) -> bool:
        """The method is called on a string: a string written out, a string member, or a constant string."""
        recv, rname = str(node.get("recv") or ""), str(node.get("rname") or "").lower()
        if recv in ("StringConstantExpressionAst", "ExpandableStringExpressionAst"):
            return True
        if recv in ("MemberExpressionAst", "InvokeMemberExpressionAst", "ConvertExpressionAst"):
            return rname in STRING_MEMBERS
        if recv == "VariableExpressionAst":
            const = self.paths.consts.get(rname)
            return isinstance(const, dict) and const.get("k") == "s"
        return False

    def member(self, el, text: str) -> None:
        """A member called by name on what comes down the pipeline (ForEach-Object Name, .ForEach('Name'))."""
        names = self.paths.strings(el)
        if names is None:
            self.add("hidden", "hidden", f"calls a member whose name is computed ({text[:60]})")
            return
        for name in (n.lower() for n in names):
            if name in SAFE_MEMBERS or (name in PURE_METHODS and name not in STRING_ONLY_METHODS):
                continue
            if name == "delete":
                self.add("delete", "skip_bin", "deletes what comes down the pipeline by .Delete(), past the Recycle Bin")
            elif name in ("kill", "closemainwindow"):
                self.add("program", "stop", "ends a running program", name=text[:120])
            elif name in METHOD_KINDS:
                self.add(METHOD_KINDS[name], METHOD_KINDS[name], f"calls .{name}() on what comes down the pipeline")
            else:
                self.add("unknown", "unknown", f"calls .{name}() on what comes down the pipeline")

    def file_method(self, member: str, node: dict, first) -> None:
        """[IO.File] and [IO.Directory]: the file it names, read or changed."""
        strings = self.paths.strings(first) if first is not None else None
        if not strings:
            self.add("unknown", "unknown", f"calls [{node.get('on')}]::{node.get('member')}() on a computed path")
            return
        provider, place = Paths(self.origin).place(strings[0])
        if provider != "file":
            self.provider(provider, place, member not in FILE_READ_METHODS, node)
            return
        if member in FILE_READ_METHODS:
            self.add("read", "read", f"reads {place}", paths=[place], raw=[strings[0]])
        elif member == "delete":
            self.add("delete", "skip_bin", f"deletes {place} by [{node.get('on')}]::Delete(), past the Recycle Bin",
                     paths=[place], write=True, raw=[strings[0]])
        else:
            self.add("unknown", "unknown", f"calls [{node.get('on')}]::{node.get('member')}() on {place}",
                     paths=[place], write=True, raw=[strings[0]])

    def new_object(self, node: dict, name: str) -> None:
        if _bound(node, "ComObject") is not None:
            # Shell, scripting and task objects run programs, elevate and schedule outside PowerShell's reading.
            self.add("hidden", "hidden", "makes a COM object, which can run things that cannot be read first")
            return
        typed = self.paths.strings(_bound(node, "TypeName"))
        if typed is None:
            self.add("hidden", "hidden", "makes an object of a computed type")
            return
        for made in typed:
            low = made.lower()
            if _net_type(low):
                self.add("network", "net", f"makes a {made} to reach the network", sends=True)
            elif _never_type(low):
                self.add("hidden", "hidden", f"makes a {made}, which can run code that cannot be read first")
            elif low not in PLAIN_OBJECTS and not low.startswith(GENERIC_COLLECTIONS):
                self.add("unknown", "unknown", f"makes a {made}")


def _never_type(low: str) -> bool:
    """A .NET type (lowercased) that can run code which cannot be read first."""
    return any(low == t.rstrip(".") or low.startswith(t if t.endswith(".") else t + ".") for t in NEVER_TYPES)


def _net_type(low: str) -> bool:
    """A .NET type (lowercased) that reaches the network."""
    return any(low == t or low.startswith(t + ".") for t in NET_TYPES)


