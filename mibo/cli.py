"""The `mibo` command: it opens the app.

Each subcommand imports its module only when it runs, so `--home` is in the
environment before anything resolves a path or reads a setting.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import textwrap

from mibo import __version__, i18n, langs

# name -> (module, function, its one-line help in the catalog). The function takes (argv, prog).
COMMANDS = {
    "start": ("mibo.welcome", "main", "start.command"),
    # Windows: the guards on other places (the uninstaller removes them), and the optional hardening's elevated helper.
    "guards": ("mibo.shell.guards", "main", "guards.command"),
    "netguard": ("mibo.shell.netguard", "main", "netguard.command"),
}


def _broken_without_a_terminal() -> int:
    """pythonw, as the shortcut starts it, has nowhere to print an install
    that does not import: it goes to the log, and a dialog names the log."""
    import traceback

    from mibo import home, window

    log = home.find_home() / "runtime" / "desktop" / "app.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as out:
        traceback.print_exc(file=out)
    window.alert(i18n.t("cli.broken", i18n.lang(), log=log))
    return 1


def _parser(lang: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mibo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.fill(i18n.t("cli.about", lang), 78),
        # Raw, so the command list keeps one line per command.
        epilog=_usage(lang) + "\n\n" + textwrap.fill(i18n.t("cli.noCommand", lang), 78))
    p.add_argument("--version", action="version", version=f"mibo {__version__}")
    p.add_argument("--home", metavar="DIR", help=i18n.t("cli.home", lang))
    p.add_argument("command", nargs="?", choices=list(COMMANDS), metavar="command",
                   help=i18n.t("cli.command", lang))
    p.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p


def _usage(lang: str) -> str:
    width = max(map(len, COMMANDS))
    lines = [f"  {name:<{width}}  {i18n.t(spec[2], lang)}" for name, spec in COMMANDS.items()]
    return i18n.t("cli.commands", lang) + "\n" + "\n".join(lines)


def _argparse_words(lang: str):
    """argparse's gettext: its own words (the English catalog's cli.argparse) in `lang`, anything else as given."""
    keys = {text: key for key, text in i18n.words("cli", "en")["argparse"].items()}
    return lambda text: i18n.t(f"cli.argparse.{keys[text]}", lang) if text in keys else text


def _take_home(args: list[str]) -> tuple[str | None, list[str]]:
    """Pull `--home DIR` out of the words after the command, so it works there too."""
    home, rest, i = None, [], 0
    while i < len(args):
        word = args[i]
        if word == "--":
            rest += args[i:]
            break
        if word == "--home":
            if i + 1 >= len(args):
                raise SystemExit(i18n.t("cli.homeMissing", i18n.lang()))
            home, i = args[i + 1], i + 2
        elif word.startswith("--home="):
            home, i = word[len("--home="):], i + 1
        else:
            rest.append(word)
            i += 1
    return home, rest


def _unknown_leading_option(words: list[str]) -> str | None:
    """An option before the command that mibo does not know; argparse
    would take the word after it for the command (`--hme H run`)."""
    i = 0
    while i < len(words):
        word = words[i]
        if word == "--home":
            i += 2
        elif word in ("-h", "--help", "--version") or word.startswith("--home="):
            i += 1
        elif word.startswith("-") and word != "--":
            return word
        else:
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    langs.utf8_console()
    lang = i18n.lang()
    # argparse asks gettext for its own words: usage, options, its errors.
    argparse._ = _argparse_words(lang)
    p = _parser(lang)
    words = sys.argv[1:] if argv is None else argv
    unknown = _unknown_leading_option(words)
    if unknown:
        p.error(argparse._("unrecognized arguments: %s") % unknown)
    args = p.parse_args(words)
    if not args.command and langs.interactive():
        args.command = "start"
    if not args.command:
        p.print_help()
        return 0
    later_home, rest = _take_home(args.args)
    chosen = later_home or args.home
    if chosen:
        os.environ["AGENT_HOME"] = os.path.abspath(os.path.expanduser(chosen))
    module_name, func_name, _help = COMMANDS[args.command]
    try:
        func = getattr(importlib.import_module(module_name), func_name)
    except Exception:
        if sys.stderr is not None:
            raise
        return _broken_without_a_terminal()
    if args.command == "start" and not {"-h", "--help", "--no-browser"} & set(rest):
        # The app opening: start at sign-in is on by default, the first time.
        from mibo import autostart, home
        autostart.first_run_soon(home.find_home())
    try:
        result = func(rest, f"mibo {args.command}")
    except SystemExit as stop:
        if {"-h", "--help"} & set(rest) and not stop.code:
            print(i18n.t("cli.alsoHome", i18n.lang()))
        raise
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
