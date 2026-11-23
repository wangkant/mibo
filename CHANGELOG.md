# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
It is kept in English; the README describes the app in all ten interface languages.

## [Unreleased]

### Files

- Word, Excel and PowerPoint files are made as files: asked for a document, a table or slides, the character writes the finished .docx, .xlsx or .pptx instead of typing into the program's window, and changes an existing one in place, keeping its layout. Such changes can be taken back like any other change to a file. Three built-in skills guide a good document, workbook and deck.
- PDFs are read page by page; a scanned PDF is reported as holding no text.

### Approvals

- Approval cards are gone. When a step needs your decision, the character tells you in the chat what it is about to do and waits; reply in your own words, such as “ok”, “确定” or “go ahead”, and it goes ahead. Anything else is a no for that step and is then read as an ordinary message.
- One yes finishes the task: later steps of the same kind in that reply run without asking again. Paying, deleting, account changes and sending something out are asked once more on their own unless that is what you said yes to.
- Only your own message typed in the chat counts as a yes; nothing on a page, in a file, in a tool's answer or in the character's own words does. A yes belongs to the one step it was asked for, and a step that changes is asked again.
- Your own Desktop, Documents, Downloads, Pictures, Music and Videos folders no longer need a grant: files there are read and written for you, while deleting still asks.
- Pictures of a window are sent to the model service without a question, unless the window looks sensitive or you turn this off in Settings.

## [0.1.0] - 2026-11-22

First release. Attached below: an installer and a zip that needs no installing for Windows 10 and 11 (x64), a disk image for macOS on Apple silicon, and the wheel, which is also on PyPI as `mibo` for any system with Python 3.10–3.14. Mibo needs a model service you choose, with your own key, or a model server on your computer.

### Conversation and models

- One character, in a window and, on Windows, as a figure on the desktop. Built-in characters or one you write.
- Any OpenAI-compatible service: 18 are listed in Settings (DeepSeek, Qwen, Kimi, GLM, OpenRouter, OpenAI, Claude, Gemini and others), plus any address you enter. Ollama and LM Studio are found when they run on the computer; OpenRouter's free models need only a sign-in.
- Replies call tools natively, from one catalogue of tools for every model; the steps a reply took are listed under it.
- A context budget from the model's window: a gauge in the model menu, Summarize now and Clear context. A long chat keeps one summary of its older turns, readable in the chat.
- Windows and prices of listed models come from a bundled models.dev catalogue: spending is shown in money, with an optional monthly limit. A backup model answers while the main one fails.
- Temporary chats that leave no record, and search over past chats.

### Memory

- Dated facts and plans about you, shown and edited in Settings › Memory, with a trace in the chat where they are used. A list exported from another assistant can be imported item by item.
- Identity numbers, card numbers, passwords and verification codes are never stored.
- Chats and caches are kept in one SQLite file in the data folder; a forgotten line is removed from the file itself.

### Recommendations

- One find at a time from public sources, ranked by how long you stay rather than by clicks. Each card states its reason, takes feedback with undo and stays in the history list.
- Asked for something in chat, the character picks a find on that subject, or looks it up on the web when none fits.
- A daily pace, quiet hours, and nothing shown during games, full-screen video or presentations.

### The web

- Walks: up to three a day by default, the character reads public pages as a visitor through the Edge, Chrome or Chromium already installed, signed out and honouring robots.txt. Settings › Going out sets the pace or turns them off.
- A page is read at once, as a browser shows it: its own character set, its main text, headings, lists and tables; a long page by outline and section.
- Web search with no key, or with a Brave or Tavily key.

### Built-in browser (Windows)

- Links open in the app beside the chat: tabs, private tabs, find, print, zoom, downloads, history and site permissions. Sign-ins stay in the app's own browser profile.
- The character opens pages, looks at them as a snapshot with numbered controls and acts on them: click, type, choose, press keys, hover, drag, scroll and upload a file you named, in the tab in front or in one out of sight.
- What a press sends is watched and judged; a cookie banner gets its most private choice.

### Other programs (Windows)

- Other programs' windows are read and operated through UI Automation, including windows drawn by Chromium (Electron apps). A control without a name is described by its size, shape, colour and the words beside it.
- Keys and clicks wait until you leave the keyboard and mouse alone. Password managers, security and system settings, installers, terminals, banking and payment programs, and anything run as administrator are never operated.

### Files and commands

- Commands are read before they run: PowerShell on Windows, bash on macOS and Linux.
- A new data folder may read Desktop, Documents, Downloads, Pictures, Music and Videos; other folders are granted from a card or in Settings, and any grant can be taken back.
- File changes in each turn can be undone from under the reply. On Windows, deletions go to the Recycle Bin.

### Skills and connectors

- Skills (`SKILL.md` folders, as the Agent Skills format has them) from a curated market, a folder, a zip, an address or other apps. Each installed skill is listed to the model, which loads one when needed; `/name` at the start of a message starts one.
- MCP servers from a curated market or the MCP Registry. A tool marked read-only whose name is a read runs directly; the rest go through the review and the card; one that pays, deletes or changes an account or access asks every time, whatever its maker marked. Node.js and uv are downloaded into the data folder only when you add a server that needs them.

### Scheduled tasks

- Reminders, tasks and condition checks on a rhythm, made in chat or in Settings › Scheduled tasks.
- A run only reads, plus the kinds of action allowed when the task was made; anything else is offered as a button for you to press.

### Permission and privacy

- One acting mode for pages, programs, files and commands: off, view only, or automatic review (the default), in which what only reads or can be undone goes ahead, a reviewer model judges the rest, and a card asks you when it does not pass.
- Paying or buying, deleting, and changes to an account's security or access ask every time, in every mode, with no "always allow". On banking, payment, health and mail sites every action asks.
- Passwords, payment details and verification codes are never read or typed by the character.
- Settings are kept in `settings.json` in the data folder; keys for the model, search and connectors are kept in the system's credential store (Windows Credential Manager, the macOS keychain, Secret Service on Linux).
- Backups with or without keys, restore, and reset in Settings › This computer.

### Also

- Ten interface languages: English, 简体中文, 繁體中文, 日本語, 한국어, Español, Français, Deutsch, Português (Brasil) and Русский.
- Mibo starts at sign-in by default; Settings › This computer turns it off.
- It checks for a new release at most once a day, sending only its version number, and says when one is out.

### Known limits

- **Unsigned installers.** Neither installer is code-signed. On Windows, SmartScreen shows "Windows protected your PC": choose More info, then Run anyway. On macOS the app is not notarized: the first open is blocked, and System Settings › Privacy & Security › Open Anyway allows it.
- **Windows-only parts.** The built-in browser and acting on pages, other programs, the desktop figure and Recycle Bin deletions are Windows only. On macOS and Linux, Mibo chats, remembers, recommends, goes out on the web, and works with files, commands, skills, MCP servers and scheduled tasks.
- **Platforms.** The macOS build is for Apple silicon only; Linux has no package of its own and installs from PyPI or runs from source.
- **Updates.** There is no automatic update: install the new release over the old one; the data folder is kept.
- **Replies** appear whole when finished; they are not streamed.
- **Walks** need Edge, Chrome or Chromium installed.
- **Spending** shown from catalogue prices ignores peak-hour and long-context pricing, so it can read low for some services.

[Unreleased]: https://github.com/wangkant/mibo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wangkant/mibo/releases/tag/v0.1.0
