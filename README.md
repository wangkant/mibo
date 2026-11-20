# Mibo

A desktop companion. One character talks with you, remembers you, recommends one thing at a time, and acts for you on the web, in other programs and in your files. Every action with an effect waits for your approval.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](LICENSE)

**English** · [简体中文](README.zh-CN.md)

Mibo runs locally with a model you bring, and stores its data in a single folder on your computer. It targets Windows 10 and 11.

> **Status:** pre-release. No installer is published yet; run it from source.

## Features

| | |
|---|---|
| **Conversation** | One character, in a window and as a figure on the desktop. Built-in characters or your own. Any OpenAI-compatible model service, with your key. |
| **Memory** | Dated facts and plans about you, visible and editable in Settings. Sensitive identifiers (IDs, card numbers, passwords, codes) are never stored. |
| **Recommendations** | One item at a time from public sources, ranked by how long you stay rather than by clicks. Each card states its reason and accepts feedback with undo. |
| **Web** | Reads public pages as a visitor and honours robots.txt. A built-in browser keeps the chat beside the page and operates the page on request. |
| **Programs** (Windows) | Finds and operates other programs through UI Automation, per-program consent, and never while you are typing. |
| **Files and commands** | Limited to folders you grant. Commands are parsed before they run; deletions go to the Recycle Bin; each turn's file changes can be undone. |
| **Extensions** | Skills (`SKILL.md` folders) and MCP connectors, each with a curated market. Connector tokens are kept in the system credential store. |
| **Also** | Scheduled tasks, search over past chats, ten interface languages. |

## Safety

- Passwords, payment details and verification codes are never read or typed.
- Payments, deletions and account-security changes always require confirmation.
- Nothing runs unattended except scheduled tasks you create, which are read-only beyond what you allowed.
- Sign-ins and cookies stay on your computer. Your model key goes only to the model service you chose.

## Quick start

Requires Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

The first run asks for a language, a character and a model key. Data is kept in `~/mibo`, or in the folder given with `mibo --home DIR`.

On macOS and Linux, install with `python -m pip install -e ".[app]"`. Program control and the built-in browser are Windows-only.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI runs the suite on Linux (Python 3.10–3.14) and Windows and verifies a clean install of the built wheel. See [CONTRIBUTING](.github/CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE). Third-party code keeps its own licence ([NOTICE](NOTICE)); character portraits are CC BY-NC-SA 4.0 ([details](mibo/static/characters/LICENSE.md)). See the [disclaimer](docs/DISCLAIMER.md).
