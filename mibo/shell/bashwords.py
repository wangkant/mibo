"""tree-sitter-bash's syntax tree as bashread.py reads it, and the words a command is given."""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from .bashtables import NUMERIC_VALUES


@functools.lru_cache(maxsize=1)
def _language():
    import tree_sitter_bash
    from tree_sitter import Language
    return Language(tree_sitter_bash.language())


def _tree(text: str):
    from tree_sitter import Parser
    return Parser(_language()).parse(text.encode("utf-8")).root_node


def _text(node) -> str:
    """A node's source text."""
    return node.text.decode("utf-8", "replace")


def _short(texts: list[str | None]) -> str:
    """Words for an act's name, a computed one as "?"."""
    return " ".join(t if t is not None else "?" for t in texts)[:120]


def _bundles(word: str, letters: str) -> bool:
    """A short option bundle (-Bc, -ne) holding one of `letters`."""
    return bool(letters) and bool(re.fullmatch(r"-[A-Za-z]+", word)) and any(c in word[1:] for c in letters)


def _numeric(node) -> bool:
    """A value that can only be a number: a number written out, {1..3}, or what `seq` prints."""
    if node.type == "command_substitution":
        inner = node.named_children[0] if node.named_children else None
        name = inner.child_by_field_name("name") if inner is not None and inner.type == "command" else None
        return name is not None and _text(name) == "seq"
    return node.type in ("number", "brace_expression") or NUMERIC_VALUES.fullmatch(_text(node)) is not None


def _descendants(node):
    """`node` and every node under it."""
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.children)


def _texts(words: list) -> list[str | None]:
    """The words' texts, None for a computed one."""
    return [w.text if w is not None else None for w in words]


@dataclass
class Word:
    """One argument after expansion: its text, and whether unquoted wildcards make it a pattern."""
    text: str
    wild: bool = False
