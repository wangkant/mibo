# Mibo

A companion that lives on your desktop: one character that talks with you, remembers you, brings you one thing worth your time, and can act for you on the web, in other programs and in your files, each time behind a card you approve.

<p>
  <a href="https://github.com/wangkant/mibo/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI&labelColor=24292f" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square&labelColor=24292f" alt="Python 3.10–3.14"></a>
  <a href="https://github.com/wangkant/mibo/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square&labelColor=24292f" alt="License: Apache 2.0"></a>
</p>

**English** · [简体中文](README.zh-CN.md)

Mibo runs on your own computer, with a model you bring, and keeps what it stores in one folder there. It is built for Windows 10 and 11 first. It is not released yet: there is no installer to download, and it runs from this repository.

## What it does

- **Talks with you.** One character with a voice of its own, in a window and as a small figure on the desktop. Pick one of the characters that ship with it or write your own. The model is yours: any service that speaks the OpenAI chat API, with your key.
- **Remembers you.** What you tell it is kept as dated facts and plans, shown under Settings › Memory, where each one can be changed or removed. Saying "remember…" or "forget…" works in the chat. ID numbers, card numbers, passwords and codes are refused.
- **Brings you one thing at a time.** It reads public sources in the background and learns what you care for from what you do with what it shows: how long you stayed counts, an open alone does not. Each card says why it is shown, takes a "not interested" with a reason and an undo, and everything shown can be found again. Pace and quiet hours are yours to set.
- **Goes out on the web as a visitor.** It reads public pages, signed in to nothing, keeps to robots.txt, and tells you what it found when you ask it to look something up.
- **A browser of its own, with the chat beside the page.** Ask in the chat and it works the page for you. Sending, posting, uploading a file, a download and leaving for another site each wait for your press. What it reports is checked against what changed on the page.
- **Works in other programs** (Windows). It finds a program by the name Start gives it, asks before it touches it, waits while your hands are on the keyboard, and can carry an errand across up to three programs.
- **Commands and files, in the folders you grant.** Every command is read before it runs and shown in plain words when it needs your yes. Deletes go to the Recycle Bin, and a turn's file changes can be undone from under the reply.
- **Skills and connectors.** Skills are folders with a `SKILL.md`, from a market of reviewed sources or your own. MCP servers connect with one press, sign in through your browser, and keep their tokens in the system's credential store.
- **Scheduled tasks, and a memory of past chats** it can search.
- **Ten interface languages**: English, 简体中文, 繁體中文, 日本語, 한국어, Español, Français, Deutsch, Português (Brasil), Русский.

## What it will not do

- It never reads or types a password, a payment detail or a verification code. Signing in is always yours to do.
- Paying, buying, deleting and anything about an account's security ask every time, with no "always allow".
- Nothing runs with nobody there unless you set it up as a scheduled task. Such a run reads; what it would do beyond what you allowed that task is left as a button for you.
- Your sign-ins and cookies stay on this computer. Your model key is sent to the model service you chose and nowhere else.

## Run it

Python 3.10 to 3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

`mibo` opens the window and walks you through the first run: language, character, model key, what you care for. Windows uses the WebView2 that Windows 10 and 11 already have. On macOS and Linux install the window with `python -m pip install -e ".[app]"`; working in other programs and the browser of its own are Windows only for now.

Everything Mibo keeps lives in one folder: `~/mibo`, or the folder you name with `mibo --home DIR`.

## Develop

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI runs the suite on Linux (Python 3.10 to 3.14) and on Windows, builds the wheel and installs it clean. Measuring scripts live under `tools/`: `tools/recsim` simulates people for the recommender, `tools/opbench.py` and `tools/optruth.py` exercise page operation on a practice site, `tools/copy_check.py` keeps the Chinese interface text written rather than spoken. See [CONTRIBUTING](.github/CONTRIBUTING.md).

## Where it stands

It is under active construction. Known and not yet fixed:

- Memory's background writer does not yet match the code it replaced on the acceptance run.
- On Windows the page's own Maximize button does not maximise the window, and the process can outlive a closed window.
- This README is in two languages; the interface is in ten.

## License

[Apache License 2.0](LICENSE). Code adapted from other projects keeps its licence ([NOTICE](NOTICE)); the character portraits are CC BY-NC-SA 4.0 ([their licence](mibo/static/characters/LICENSE.md)). See also the [disclaimer](docs/DISCLAIMER.md).
