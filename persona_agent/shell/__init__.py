"""Doing things on this computer by command, for the person, behind permissions kept in code.

The reply model writes one PowerShell command (tool.py). The app reads it with
PowerShell's own parser and sorts what it would do (read.py), checks that
against the person's switch, granted folders and the never list (grants.py),
and then runs it, asks on a card in the chat, or refuses (panel.py). Running is
a child PowerShell with no profile, a cleaned environment, a time limit and its
whole process tree ended on stop (run.py). Plain words for the card and the
step log are made by the app, never by the model (words.py).

Ideas from DeepSeek's dsh (MIT, see NOTICE): a fresh `-NoProfile
-NonInteractive` PowerShell for every command, UTF-8 output pinned in a
preamble, capped output and ending the whole process tree.
"""
