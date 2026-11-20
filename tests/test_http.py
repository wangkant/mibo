"""The settings: the one numeric reader, and the template that lists every setting the code reads."""
from __future__ import annotations

from pathlib import Path

from helpers import check


def test_numeric_config_parser_is_bounded() -> None:
    """The package's one numeric reader enforces the bounds every setting gets."""
    from mibo.config_env import env_int

    def parser(name, raw, default, **kw):
        return env_int(name, default, env={name: raw}, **kw)

    check("numeric config: invalid value uses default",
          parser("SERVER_PORT", "not-a-number", 8080, minimum=1, maximum=65535) == 8080)
    check("numeric config: out-of-range value uses default",
          parser("SERVER_PORT", "70000", 8080, minimum=1, maximum=65535) == 8080)
    check("numeric config: valid value accepted",
          parser("SERVER_PORT", "9000", 8080, minimum=1, maximum=65535) == 9000)


def test_every_setting_the_code_reads_is_in_the_template() -> None:
    """`.env.example` must list every key the code reads.

    Scanned rather than listed, so the two cannot drift: `os.getenv`,
    `os.environ.get` and the `config_env` readers."""
    import ast

    # `tools/` too: the tools read settings the operator puts in `.env`.
    root = Path(__file__).resolve().parents[1]
    sources = [
        *sorted((root / "mibo").glob("*.py")),
        *sorted((root / "tools").glob("*.py")),
    ]

    readers = {"env_int", "env_float", "env_bool", "env_str", "env_csv"}

    def is_env_read(call: ast.Call) -> bool:
        fn = call.func
        if isinstance(fn, ast.Name):
            return fn.id in readers
        if not isinstance(fn, ast.Attribute):
            return False
        if fn.attr in readers:
            return True
        if fn.attr == "getenv":
            return isinstance(fn.value, ast.Name) and fn.value.id == "os"
        if fn.attr == "get":
            inner = fn.value
            return (isinstance(inner, ast.Attribute) and inner.attr == "environ"
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "os")
        return False

    read: dict[str, str] = {}
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and is_env_read(node)):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            key = node.args[0].value
            if isinstance(key, str) and key.isupper():
                read.setdefault(key, f"{path.name}:{node.lineno}")

    check("template scan found the settings at all", len(read) > 20, str(len(read)))

    template = (root / ".env.example").read_text(encoding="utf-8")
    documented = {
        line.split("=", 1)[0].strip()
        for line in template.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = sorted(
        f"{key} ({where})" for key, where in read.items()
        if key not in documented)
    check("every setting the code reads is documented in .env.example",
          not missing,
          "; ".join(missing))
