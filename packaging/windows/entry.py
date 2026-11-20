"""The program of the installer's build: `personagent` as the command line has
it, and the `python -m module ...` line the app starts a part of its own with
(the screen snip, panels/compose.py), since here the program is also the Python."""
import runpy
import sys


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["-m"] and len(args) > 1:
        sys.argv = args[1:]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        return 0
    from persona_agent import cli

    # Opened from its icon or Finder with no command: the app.
    if not any(word in cli.COMMANDS for word in args):
        args = ["start", *args]
    return cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
