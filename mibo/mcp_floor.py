"""What an MCP tool, and one call of it, does, decided by code before any reviewer and whatever the server's hints say.

A tool runs with no reviewer only when its server marks it read-only and its name reads by its own words (`reads`,
`group_of`), and one marked destructive always asks (`asks_each_time`). Whether a call pays, deletes or changes an
account's security or access is decided here from the tool's name, parameters, description and the call's arguments
with the app's one floor vocabulary (`hard`, web/gate.py); such a call is always asked in the chat, where a yes to
another kind of step earlier in the turn does not reach it (cardwait.reaches). Arguments larger than the floor reads
whole are asked about too (`cut`).
"""
from __future__ import annotations

import itertools
import re

from .web import gate


def group_of(tool: dict) -> str:
    """"read" for a tool that runs with no reviewer: its provider marks it read-only and not destructive (a hint, which
    the MCP specification says not to trust alone), its name reads by its words (`reads`), and it is no floor kind
    (`hard`); else "write"."""
    hints = tool["hints"]
    return "read" if hints.get("readOnlyHint") is True and hints.get("destructiveHint") is not True \
        and reads(tool["name"]) and not tool.get("hard") else "write"


def asks_each_time(tool: dict) -> bool:
    """A tool that may never be always allowed: its provider marks it destructive, or what it does is a floor kind."""
    return tool["hints"].get("destructiveHint") is True or bool(tool.get("hard"))


# The words are the app's one floor vocabulary (web/gate.py), read in every word of the tool's name, then, for a name
# not led by a verb that reads, in its parameters and its description, and always in the call's arguments. A read verb
# leading a name takes a thing as its object (get_payment reads a payment), but never hides a later verb
# (get_or_create_payment, fetch_and_pay, list_and_delete, check_out). Carding a harmless write is the cheap mistake,
# so the words lean wide.
_READS = frozenset(["get", "list", "read", "search", "find", "query", "fetch", "show", "view", "describe", "lookup", "look", "count", "check", "browse", "inspect", "preview", "retrieve", "peek", "poll", "status", "info", "explain", "summarize", "summarise", "analyze", "analyse", "calculate", "compute", "estimate", "compare", "validate", "verify", "ping", "echo", "whoami", "is", "has", "can", "snapshot", "screenshot", "scrape", "crawl", "extract", "convert", "diff", "scroll", "hover", "wait"])
# Words that are only ever verbs that change, run or send something: a name holding one does not read. Words that
# are also things (issue, post, run, order, update in getUpdates) are not here: after a read verb they name what is
# read, and after "and" or "or" they count as verbs anyway.
_VERBS = frozenset(["edit", "modify", "reset", "replace", "add", "remove", "send", "create", "submit", "execute", "exec", "initiate", "approve", "cancel", "write", "save", "upload", "publish", "insert", "upsert", "append", "move", "rename", "install", "uninstall", "kill", "restart", "invoke", "navigate", "drag", "apply", "deploy", "revert", "confirm", "capture", "set", "delete"])
# Words of the vocabulary that name a thing a read verb may take: list_payouts, list_trash.
_THINGS = frozenset({"payment", "payout", "deposit", "trash"})
# Verbs that are things too (list_runs, list_calls): they count only as the name's first verb (run_query).
_DOES = frozenset({"run", "call"})
_FLOOR_VERBS = frozenset(w for w in gate.PAY + gate.PAY_TOOLS + gate.DELETE + gate.DELETE_TOOLS + gate.ACCOUNT
                         + gate.GRANT if " " not in w) - _THINGS
_SECRET_FIELDS = re.compile(r"password|passwd|passcode|(?:^|_)(?:pin|otp|secret)(?:$|_)", re.I)
_ACCESS_FIELDS = re.compile(r"^(?:role|roles|permission|permissions|access_?level)$", re.I)
# Money counts only with whom it goes to or its currency beside it: a scroll's amount pays nobody.
# A least or a most (min_amount, maxPrice) filters a search and pays nobody; so does a currency or a destination.
_MONEY_FIELDS = re.compile(r"^(?!min|max).*(?:amount|price|total|cost(?!ing)|fee(?![dl]))", re.I)
_TO_FIELDS = re.compile(r"recipient|payee|beneficiary|iban|card_?number|account_?number|routing|^to$", re.I)
# Fields that hold a statement or a command; a tool that says it runs them has every argument read so.
_CODE_KEYS = frozenset(["sql", "statement", "command", "cmd", "script", "code", "shell"])
# Fields that hold a statement in a database's tool and plain words in a search: there only a whole statement
# counts, at the start or after a semicolon, never the words inside a question.
_ASKED_KEYS = frozenset(["query", "expression"])
_NAMED = r"[\w.\"`\[\]]+"
_SQL_STATEMENT = re.compile(
    r"(?:^|;)\s*(?:delete\s+from\s+" + _NAMED + r"|drop\s+(?:table|database|schema|index|collection|view)\s+"
    r"(?:if\s+exists\s+)?" + _NAMED + r"|truncate\s+(?:table\s+)?" + _NAMED + r")\s*(?:;|$|where\b|cascade\b|"
    r"restrict\b)", re.I)
_RUNS_NAME = frozenset(["sql", "shell", "bash", "powershell", "terminal", "command", "cmd", "script", "python", "javascript", "code", "exec", "execute", "eval", "run"])
_RUNS_SAID = re.compile(r"\b(?:sql|cypher|shell commands?|statements?)\b", re.I)
_SQL_DELETES = re.compile(r"\bdelete\s+from\b|\bdrop\s+(?:table|database|schema|index|collection|view)\b|"
                          r"\btruncate\s+(?:table\s+)?\w", re.I)
_SQL_SECURITY = re.compile(r"\bupdate\s+\S+\s+set\b[^;]*\b(?:password|passwd)\b|"
                           r"\b(?:grant|revoke)\s+(?:all|select|insert|update|delete|usage|execute)\b[^;]*\bon\b", re.I)
_CODE_DELETES = re.compile(
    r"(?:^|[\s;&|(])(?:rm|del|erase|rmdir|rd|Remove-Item|ri|shred|unlink)\s+\S|\bformat\s+[a-z]:|\bgit\s+clean\b|"
    r"\bfind\b[^;|&\n]*\s-delete\b|\brmtree\s*\(|\bos\.(?:remove|unlink|rmdir|removedirs)\s*\(|\.unlink\s*\(|"
    r"\bfs\.(?:rm|rmdir|unlink)(?:Sync)?\s*\(|\brimraf\b|\b(?:File|Directory)\.Delete\s*\(", re.I)
_ACTION_KEYS = frozenset(["action", "operation", "op", "method", "intent", "verb", "httpmethod"])
# A request that writes to where payments are made.
_PAY_PATH = re.compile(r"/(?:charges|payments?|payouts?|transfers|refunds|checkout|payment_intents|invoices/[^/]+/pay|"
                       r"subscriptions)\b", re.I)
_MUTATION = re.compile(r"^\s*mutation\b[^{]*\{(.*)", re.S)


def _one(word: str) -> str:
    """A word without its plural or third-person s: payouts, Deletes, Places, searches."""
    low = word.lower()
    if len(low) > 4 and (low.endswith(("ches", "shes")) or (low.endswith("es") and low[-3] in "sxz")):
        return word[:-2]
    return word[:-1] if len(low) > 3 and low.endswith("s") and not low.endswith(("ss", "us", "is")) else word


def _one_each(text: str) -> str:
    """Prose with each word's plural or third-person s dropped, as names are read."""
    return re.sub(r"[A-Za-z]+", lambda m: _one(m.group()), text)


def _words(name: str) -> list[str]:
    """A tool name's words, lowercased: sendMoney, send_money, send-money, payouts.send and ns/sendMoney all give
    send, money; addSSHKey gives add, ssh, key."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", str(name or ""))
    return [_one(w).lower() for w in re.findall(r"[A-Za-z]+|\d+[A-Za-z]*", spaced)]


def _said(text: str) -> list[tuple[str, str]]:
    """(kind, phrase) of each floor phrase of the vocabulary in `text`."""
    return [(kind, m.group().lower()) for kind, words in gate.TOOL_WORDS for m in words.finditer(text)]


def _leads(words: list[str]) -> bool:
    """The first verb of the name is one that reads: get_balance, browser_tab_list, stripe_list_customers."""
    first = next((w for w in words if w in _READS or w in _VERBS or w in _DOES or w in _FLOOR_VERBS), "")
    return first in _READS


def _paired(bag: set) -> str:
    """The kind a change verb and what it changes say, anywhere in a name (update_user_email)."""
    for kind, verbs, things in gate.EVERY_PAIR:
        if bag & set(verbs) and any(set(thing.split()) <= bag for thing in things):
            return kind
    return ""


def _text_kind(text: str, bag: set, leads: bool) -> str:
    """The first floor kind `text` says, a thing after a leading read verb and a git checkout aside; a secret it
    names is the account's."""
    for kind, phrase in _said(text):
        if (leads and phrase in _THINGS) or (phrase in ("checkout", "check out") and bag & {"git", "branch"}):
            continue
        return kind
    return "account" if gate.SECRET_WORDS.search(text) else ""


def _name_kind(words: list[str]) -> str:
    return _text_kind(" ".join(words), set(words), _leads(words)) or _paired(set(words))


def reads(name: str) -> bool:
    """A name that reads by its words: a read verb leads, no word is a change or a floor word, and no verb follows
    "and" or "or" (get_or_create). The things a read takes (list_payments, list_trash) are not floor words there."""
    words = _words(name)
    joined = [b for a, b in itertools.pairwise(words) if a in ("and", "or")]
    return _leads(words) and not set(words) & _VERBS and all(w in _READS for w in joined) \
        and all(phrase in _THINGS for _, phrase in _said(" ".join(words))) and not _name_kind(words)


def _walk(value, key: str = "", depth: int = 0, out: list | None = None) -> list[tuple[str, object]]:
    """(key, value) of every field of an argument value, nested dicts and lists of operations included, to a bound."""
    out = [] if out is None else out
    if len(out) >= 4096 or depth > 6:
        return out
    if isinstance(value, dict):
        for inner_key, inner in list(value.items())[:64]:
            out.append((str(inner_key), inner))
            _walk(inner, str(inner_key), depth + 1, out)
    elif isinstance(value, list):
        for inner in value[:32]:
            if not isinstance(inner, (dict, list)):
                out.append((key, inner))
            _walk(inner, key, depth + 1, out)
    return out


def cut(value, depth: int = 0) -> bool:
    """Whether arguments are larger than the floor reads whole (_walk's bounds): such a call is asked about, since
    what was not read cannot be judged."""
    if depth > 6:
        return True
    if isinstance(value, dict):
        return len(value) > 64 or any(cut(inner, depth + 1) for inner in value.values())
    if isinstance(value, list):
        return sum(isinstance(inner, (dict, list)) for inner in value) > 32 or any(
            cut(inner, depth + 1) for inner in value)
    return False


def _statement_kind(key: str, value: str, runs: bool) -> str:
    """The floor kind of a statement or a command in one field: one that changes security or access, or one that
    deletes. In a field of plain words (a search's query) only a whole statement counts."""
    if runs or set(_words(key)) & _CODE_KEYS:
        deletes = _SQL_DELETES.search(value) or _CODE_DELETES.search(value)
    elif set(_words(key)) & _ASKED_KEYS:
        deletes = _SQL_STATEMENT.search(value)
    else:
        return ""
    if _SQL_SECURITY.search(value):
        return "account"
    return "delete" if deletes else ""


def _mutation_kind(value: str) -> str:
    """The floor kind of the first GraphQL mutation field that names one."""
    mutation = _MUTATION.match(value)
    if not mutation:
        return ""
    return next((kind for field in re.findall(r"([A-Za-z_]\w*)\s*[({]", mutation.group(1))
                 if (kind := _name_kind(_words(field)))), "")


def _action_kind(value: str, fields: list[tuple[str, object]]) -> str:
    """The floor kind an action field names: a DELETE request, a floor act in its first words, or a request that
    writes to a payments address."""
    if value.strip().upper() == "DELETE":
        return "delete"
    kind = _name_kind(_words(value)[:3])
    if kind:
        return kind
    if value.strip().upper() in ("POST", "PUT", "PATCH") and any(
            isinstance(v, str) and _PAY_PATH.search(v) for _, v in fields):
        return "order"
    return ""


def _arguments_kind(tool: dict, arguments: dict) -> str:
    """The floor kind what a call sends says: a statement or a command that deletes, an action field naming a floor
    act at any depth, a GraphQL mutation, a DELETE request or one that posts to a payments address, a password, or an
    amount with whom it goes to."""
    fields = _walk(arguments)
    keys = {re.sub(r"[^a-z0-9]", "", k.lower()) for k, _ in fields}
    runs = bool(set(_words(tool["name"])) & _RUNS_NAME) or bool(_RUNS_SAID.search(tool.get("description") or ""))
    for key, value in fields:
        if not isinstance(value, str):
            continue
        action = re.sub(r"[^a-z0-9]", "", key.lower()) in _ACTION_KEYS
        kind = _statement_kind(key, value, runs) or _mutation_kind(value) or (
            _action_kind(value, fields) if action else "")
        if kind:
            return kind
        if _SECRET_FIELDS.search(key) and value:
            return "account"
    if any(_MONEY_FIELDS.search(k) for k in keys) and any(_TO_FIELDS.search(k) for k, _ in fields):
        return "order"
    return ""


def hard(tool: dict, arguments: dict | None = None) -> str:
    """The floor kind of a tool (and of one call of it, given its `arguments`): "order" (pays, buys, books or
    changes a payment), "delete", "account" (its security, sign-in or details), "grant" (who may reach what) or
    "bind" (signs or files a binding submission); "" for anything else. A floor kind is costly (cardwait.COSTLY):
    asked in the chat every time, as its own risk. Hints are not read: a tool that says it only reads is judged by
    what it is."""
    words = _words(tool["name"])
    kind = _name_kind(words)
    if kind:
        return kind
    if not _leads(words):
        fields = list(((tool.get("inputSchema") or {}).get("properties") or {}).keys())
        if any(_SECRET_FIELDS.search(f) for f in fields):
            return "account"
        if any(_ACCESS_FIELDS.search(f) for f in fields):
            return "grant"
        if any(_MONEY_FIELDS.search(f) for f in fields) and any(_TO_FIELDS.search(f) for f in fields):
            return "order"
        said = _one_each(f"{tool.get('title') or ''} {tool.get('description') or ''}"[:600])
        kind = _text_kind(said, set(words) | set(_words(said)), False)
        if kind:
            return kind
    return _arguments_kind(tool, arguments) if isinstance(arguments, dict) and arguments else ""
