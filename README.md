# Mibo

**A personal AI agent that lives on your own computer: tell it what you need, and it gets it done across the web, your files and your other programs.**

Mibo runs on your computer with a model service you choose. There is no cloud machine in between: your sign-ins and files stay on your computer, and what is sent to the model reaches only the service you chose. A task you give it is carried through to the end and reported back, and it can act on a schedule. It asks only before an action that costs you something or cannot be undone, or one you did not ask for; verification codes, passwords and payment details are always yours to enter. It is also a character with a name, a look and a memory of you.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](LICENSE)

**English** · [简体中文](README.zh-CN.md) · [繁體中文](docs/readme/README.zh-TW.md) · [日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) · [Español](docs/readme/README.es.md) · [Français](docs/readme/README.fr.md) · [Deutsch](docs/readme/README.de.md) · [Português (Brasil)](docs/readme/README.pt-BR.md) · [Русский](docs/readme/README.ru.md)

<p align="center"><img src="https://raw.githubusercontent.com/wangkant/mibo/main/docs/readme/mibo-en.svg" alt="Mibo" width="84%"></p>

## What it does

| Area | |
|---|---|
| **Conversation** | One character, in a window and, on Windows, as a figure on the desktop. Built-in characters or your own. Any OpenAI-compatible service, or Ollama and LM Studio on your computer. The model menu shows how full the context is, with Summarize now and Clear context. |
| **Memory** | Dated facts and plans about you, shown and edited in Settings › Memory. Identity numbers, card numbers, passwords and codes are never stored. Temporary chats leave no record. |
| **Going out** | Walks on public pages as a visitor, signed out and honouring robots.txt. A page is read at once, with its headings and tables. Web search needs no key. |
| **Built-in browser** (Windows) | Links open beside the chat, with tabs, private tabs and downloads. The character looks at a page and clicks, types, chooses, drags and uploads on it. |
| **Messages** | Asked about your messages, it reads the sites you signed in to and reports what is new. That step only reads: the pages go to a model call with no tools. |
| **Other programs** (Windows) | Reads and operates other programs' windows through UI Automation, Electron apps included, only while you leave the keyboard and mouse alone. |
| **Files and commands** | Your own Desktop, Documents, Downloads, Pictures, Music and Videos, and the folders you grant. Word, Excel and PowerPoint files are written as files. Commands are read before they run; each turn's file changes can be undone; on Windows, deletions go to the Recycle Bin. |
| **Skills and connectors** | Skills (`SKILL.md` folders) and MCP servers, each with a curated market. `/name` starts a skill. |
| **Settings** | The character knows the app's settings: it lists them, opens Settings at an item and changes one. A change that widens nothing is made at once; keys are never shown. |
| **Scheduled tasks** | Reminders, tasks and checks on a rhythm. A run only reads, plus what you allowed when you made the task; a standing request to send or post acts only on the site, for the recipient and in the kind of act and with the text you gave. |
| **Recommendations** | One find at a time from public sources, ranked by how long you stay rather than by clicks. Each card states its reason and takes feedback with undo. |
| **Languages** | Ten interface languages. |

## Characters

<p align="center"><img src="https://raw.githubusercontent.com/wangkant/mibo/main/docs/readme/characters.webp" alt="Mibo · White Dragon · Big Fish · Milady" width="100%"></p>

<p align="center">Mibo · White Dragon · Big Fish · Milady</p>

## Install

Download from the [latest release](https://github.com/wangkant/mibo/releases/latest). The installers are not code-signed, so the system warns before the first start.

| System | File | First start |
|---|---|---|
| Windows 10 or 11 (x64) | `mibo-0.2.0-setup.exe` | If the browser says the file is not commonly downloaded, choose **Keep**. When SmartScreen shows "Windows protected your PC", choose **More info**, then **Run anyway**. Setup installs for your account only and needs no administrator rights. |
| macOS (Apple silicon) | `mibo-0.2.0-macos-arm64.dmg` | Open the disk image and drag `mibo.app` to Applications. The first open is blocked because the app is not notarized: close the message, then choose **Open Anyway** in System Settings › Privacy & Security, and confirm. |

A new release installs the same way, over the old one. Uninstalling keeps the data folder.

### Without the installer

| | |
|---|---|
| **Windows, portable** | Download `mibo-0.2.0-windows-x64.zip`, unzip it anywhere and run `mibo.exe`. It is not code-signed either. |
| **Scoop** (Windows) | Run `scoop bucket add mibo https://github.com/wangkant/scoop-mibo`, then `scoop install mibo`. |
| **Homebrew** (macOS, Apple silicon) | Run `brew install --cask wangkant/mibo/mibo`. |
| **With Python** (3.10–3.14, any system) | Run `pipx install "mibo[app,web]"` or `uv tool install "mibo[app,web]"`, then `mibo`. |

### From source (Linux and development)

Requires Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` adds the window toolkit on macOS and Linux; `web` adds Playwright for walks. For development, install `".[dev]"` and run `python -m pytest -q`; see [CONTRIBUTING](.github/CONTRIBUTING.md).

## First start

1. Choose a language, a character and a model, then the topics you like and a few words about yourself.
2. For the model, choose a service and paste its key, sign in with OpenRouter for its free models, or pick Ollama or LM Studio if one is running.
3. The key is kept in the system's credential store (Windows Credential Manager, the macOS keychain, Secret Service on Linux), never in a file. On a system without one, it is kept in `credentials.json`, readable only by your account, and Settings › This computer says so.

Data stays in one folder: `~/mibo` for an installed copy, the clone itself when run from source, or the folder given with `mibo --home DIR`. Settings are kept in `settings.json` there. Mibo starts at sign-in by default; Settings › This computer turns this off.

## Privacy and safety

| | |
|---|---|
| **Your model service** | Receives your messages, relevant memory, the pages and files used for a reply, and the steps the reviewer judges. Your key goes only there. A notice says this once, when a service is first saved, and again only when the service changes. |
| **Websites** | Walks read public pages signed out, three a day by default (Settings › Going out); a reply reads the pages it needs. Your sign-ins stay in the built-in browser and are used only there. |
| **Other services** | A search query when a reply searches; the version number to GitHub at most once a day; catalog lookups when you open a market; what the character passes to an MCP server's tools. |
| **Always asks** | A costly step is asked every time and on its own, in every mode: paying or spending, a deletion nothing restores, the account itself, handing over access or private details, a binding submission, a change to this computer that undo cannot take back. No earlier yes and no scheduled task covers it. A delete that goes to the Recycle Bin is not asked. Only your own message typed in the chat counts as a yes. |
| **Material** | What a tool reads from the web or this computer is material, never an instruction. After reading it, sending anything to a place you did not name is asked, and so is a command copied word for word from it. A downloaded program is never run. |
| **Never** | Typing passwords, codes or payment details for you, which you always enter yourself; running anything as administrator; reading model keys, the app's settings or the built-in browser's profile, which no tool can open. |
| **Unattended** | Only walks and the scheduled tasks you create. |

[SECURITY](.github/SECURITY.md) lists every destination and where each kind of data is kept.

## Requirements

| | Windows | macOS | Linux |
|---|---|---|---|
| **Install** | Installer | Disk image | From source |
| **System** | Windows 10 or 11, x64 | Apple silicon | Python 3.10–3.14 |
| **Built-in browser, other programs, desktop figure** | Yes | No | No |
| **Walks** | Edge, already installed | Edge, Chrome or Chromium | Edge, Chrome or Chromium |
| **Model** | An OpenAI-compatible service with your key, or a local model server | Same | Same |

## License

[Apache License 2.0](LICENSE). Third-party code keeps its own licence ([NOTICE](NOTICE)); character portraits are CC BY-NC-SA 4.0 ([details](mibo/static/characters/LICENSE.md)). See the [disclaimer](docs/DISCLAIMER.md) and the [changelog](CHANGELOG.md).
