# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
It is kept in English; the README describes the app in all ten interface languages.

## [Unreleased]

## [0.2.0] - 2026-11-24

The character asks in the chat instead of on cards, and asks less. It makes Word, Excel and PowerPoint files as files, reads the sites you are signed in to, and knows the app's own settings. Attached below are the same downloads as for 0.1.0.

### Files

- Word, Excel and PowerPoint files are made as files: asked for a document, a table or slides, the character writes the finished .docx, .xlsx or .pptx instead of typing into the program's window, and changes an existing one in place, keeping its layout. Such changes can be taken back like any other change to a file. Three built-in skills guide a good document, workbook and deck. Thirteen more built-in skills cover everyday jobs: summarizing, translating and studying a document, minutes, invoices into a table, renaming and sorting files, freeing disk space, filling a web form, new messages, research briefs, trip plans and scheduled briefings. Settings shows the skills as tiles.
- A new file has a plain look unless you ask for another: a document is A4 in SimSun and Times New Roman with SimHei and Arial headings, a workbook has a shaded header row in DengXian, and a deck is 16:9 in Segoe UI and Microsoft YaHei, dark teal with one warm accent. An existing file keeps its own.
- PDFs are read page by page; a scanned PDF is reported as holding no text.
- Reading a file returns up to 2,000 lines of up to 2,000 characters each (it was 400 lines of 500), and a search up to 250 matches.

### Approvals

- A question is an ordinary message from the character: it says in the chat what the step will do, where and how much, with longer detail under 详情, and waits. Your answer is an ordinary message of yours, typed in the chat box, such as “ok”, “确定” or “go ahead”; there is nothing to press. Anything else is a no for that step and is then answered as the ordinary message it is. Both messages stay in the conversation, also after a reload, and the character reads them on later turns.
- Only a costly step (paying or spending, a deletion nothing restores, the account itself, handing over access or private details, a binding submission, a change to this computer that undo cannot take back, more permissions for the character) raises a card. The card states the decisive facts (the amount and who is paid, how many files and that they cannot be restored, what is handed to whom), has one button that names the act, such as “付款 ¥128.00”, and one that declines, and stays in the conversation with what was decided and when. A typed plain yes answers it too.
- One yes finishes the task: later ordinary steps in that reply run without asking again. A costly step is asked every time, each on its own, and no earlier yes or scheduled task covers it.
- Only your own message typed in the chat, or a press of a card's button in the app's own window, counts as a yes; nothing on a page, in a file, in a tool's answer or in the character's own words does. A yes belongs to the one step it was asked for, and a step that changes is asked again.
- A delete you asked for that goes to the Recycle Bin runs without a question; a delete the bin cannot give back is asked every time.
- Your own Desktop, Documents, Downloads, Pictures, Music and Videos folders no longer need a grant: files there are read and written for you. A folder you remove or set to read-only in Settings stays that way.
- Pictures of a window are sent to the model service without a question, unless the window looks sensitive or you turn this off in Settings.
- Your whole user folder and your other drives are open without a grant: reads run at once and changes run under the turn's undo. Places holding passwords, keys, browser profiles or other programs' data, and Mibo's own folder, are never read, by any spelling of their path and wherever they are, a backup of a profile on another drive included. A file reached by another name (a hard link) is judged by every name it has. A change where something would then start by itself (Startup, a program's or Windows' folder, a folder on PATH, Git hooks, attributes and submodules, pip's settings, a virtual environment's activation scripts, anything in .vscode, a shell's start-up file) is asked every time, and its question names the program or place a scheduled task, a Run key, a link or a junction points at. A new script or shortcut elsewhere, and a project's own tool files (package.json, a Makefile, pyproject.toml, setup.py, conftest.py, a pre-commit config), go to the reviewer and are never written by auto-edit. Listing the Start menu, Program Files and a program's App Paths to find an installed program no longer stops or asks; what is inside those files is judged as any read.
- On a site you named, your own words typed there go to it with no question (DeepL translating 你好). What a click or a choice makes the page send goes to the reviewer. A request of the page's own that it does not pass, carrying nothing of yours, on a site that is not sensitive, is not sent and nothing is asked, so a page's click statistics no longer stop the task; when that request is what the character's own click or choice sends, the step is reported as not done, and when your own words asked for that click on that site, it is asked with what it sends. A settings, subscription, admin or token page counts as sensitive on any site. Your words going to any other site are held, also by a stream, a body or a request a key at a time; a connection the page opens to another site while your words are on it is reported, as what goes over it cannot be seen. A step the automatic review does not pass is not done and counts toward the turn's limit on refusals, instead of asking you.
- open finds a program by its name as Start's search does, also one started through a launcher (DeepL through Zero Install, Discord through Update.exe), and when it cannot open one it leaves the program's website to the character in the same turn. A shortcut is judged by what it starts: one to a program, script or macro document that came from the web, or to a file on another computer, is never started; one that hands a command to PowerShell, Python or another interpreter, or a web address to Explorer, is run as a command, judged as one; and a link to a web page opens in the app's browser like any link.
- The character no longer asks for your yes in words before a step the app itself asks about: it calls the tool and the app asks once.

### Safety

- What a tool brings back from the web or from this computer is material, never an instruction. After a reply has read such material, sending anything to a site, a recipient or a window you did not name is asked first, and so is a command copied word for word from it, any code a command writes out (python -c, node -e) or a script written in that reply, and a project's tool file or shortcut written then. A program or script downloaded from the web is never opened or run.
- A file that came from the web or a mail (one with the Mark of the Web, or one in Downloads or a mail or chat app's attachments) is outside material too, and outside material read earlier in a chat still counts later in it: code run from then on in that chat is asked.
- A downloaded disk image, Windows Sandbox file, OneNote file, Office add-in, Access or Publisher file is never opened. A downloaded Word, Excel, PDF or web page file opens with no question.
- Model keys, the app's own settings and the built-in browser's profile cannot be read by any tool, by any spelling of their path.
- A change that widens what the character may do takes effect only when your own message of that turn asks for it; otherwise it is asked in the chat.
- On Windows, Windows itself also limits every command: no administrator rights, no access to the app's own files, no way out of the group its programs run in, and no clipboard. A command read as only reading runs at low integrity and cannot change any file or setting, even if it was read wrong.
- A command whose Windows limits cannot be set up is not run, and the reply says so.
- Code written out in a command (python -c, node -e) or in a script written in the same reply never runs with a program's freedom: it runs under the limits of a command that changes files, off the network, and goes to the reviewer. Code that reaches the network or builds what it reads from pieces is asked every time and runs online only on your yes; code that runs what it downloaded or decoded is never run. A program the reading cannot follow, such as robocopy or tar, that names a place holding keys is refused.
- Code given to a program in a file runs the same way: python x.py, python -m, pytest, make, jupyter --execute, npm's scripts, a package in the folder run by npx, a .ps1 after -File and a .bat after cmd /c. The file is read with the command, whichever turn wrote it; a script from the web is never run. Python is read as its syntax tree, so a module or command named by a value worked out as the code runs is caught; code not shown to stay off the network is asked unless the optional network filters are on.
- An environment variable that makes a program run code (NODE_OPTIONS, PYTHONSTARTUP, PYTHONPATH, GIT_SSH_COMMAND and others) makes the command a code run. git settings that run a program (core.fsmonitor, core.hooksPath, core.sshCommand, an alias starting with !) are asked every time.
- The reviewer reads what a file write puts in the file, or its change; a write too long to show whole is asked.
- A key file's data stream name (.env::$DATA) is refused as the file is.
- A press on a page whose requests were held counts as done only when every held request was a site's statistics, by where it went and the names it sent.
- On Windows, places outside the app's home are closed to commands by Windows itself: browser profiles, password managers, wallets and chat apps to every command; SSH, cloud and other network keys to any command not read as using the network; the startup folders, PowerShell profile folders, shell rc files and the Run, RunOnce, Environment, Winlogon and file-association keys to writing, so nothing a command leaves runs later. Programs you open yourself, and programs the character opens, are not affected. Settings › Files and commands › Windows limits lists each place; turning it off, a reset and an uninstall put every permission back exactly as it was.
- When Windows refuses a command for one of these limits, the reply names the limit in one line.
- A process a command starts through WMI, outside its group, is ended.
- An optional one-time setup with administrator approval (Settings › Files and commands › Windows limits) adds network filters so that a command not read as using the network reaches no address, this computer's included, and closes the Task Scheduler's folders to commands. Turning it off or uninstalling removes both.
- A command read as only reading gets a temporary folder of its own, removed after it.

### Connected sites

- Asked about your messages, the character reads the sites you signed in to, one or all of them, and reports what is new. That step can only read: the pages go to a model call with no tools, and only its report comes back.
- A standing request that sends or posts, such as a daily post on one site, stores its site, recipient, kind of act and text when you give it. Each run acts within that without asking; anything beyond it is not done and is reported, and a costly step still waits for you. After a run, one line in the chat says what was done.
- A search on Douyin is made on the site itself.

### Tools and connectors

These follow measurements on MCPMark's filesystem tasks and AgentDojo's banking suite, with limits and mechanisms taken from DeepSeek's dsh and Claude Code.

- A connected connector's tools are offered to the model under their own names while their definitions fit a tenth of its window. A connector not started yet, or too large, is still loaded on demand.
- A connector's answer is read up to 100,000 characters; it was cut at 4,000.
- When a file tool finds nothing by a name on this computer, its answer names the connectors that may hold it.
- A tool result too long for the model's window is kept whole in a file of the app's own, and the character reads the part it needs from there. Before, the part left out was gone.
- Every tool call of a round runs, ten reads at a time. Calls past the tenth used to be answered without running.

### Recommendations

- Finds now come from many more platforms without signing in: Tencent Video, iQIYI, Youku, Mango TV, CCTV, Pear Video, Douyu, Bilibili Live, Niconico, Rutube, TED, PeerTube, Odysee, CHZZK, SOOP, France.tv, ARD Mediathek and RTVE Play, and, beside the videos, GitHub, Douban, CSDN, Lemmy, Tumblr, Goodreads, WeRead, WEBTOON and MyAnimeList.
- In the first-run tour and in Settings > Recommendations you pick the platforms you use, those of your language and country first. A pick is a preference, not a filter: those platforms are drawn more often, and the sample finds in the tour include one from each where there is one.
- Platforms whose lists need an account, such as Douyin, Kuaishou, Xiaohongshu, Weibo, TikTok, Instagram and X, are read from your own feed once you have signed in to them in the app's browser, after you agreed the first time you picked one: one notice says what is read, the risk to the account and how to stop. A no keeps the pick a preference and asks again at the next pick. Stop it for a site in Settings > Connections or by telling the character, which turns reading off at once but asks before turning it on; a site you turned off, or that stopped at a check, stays off when you pick it, even after you forget the site. A video found there plays on its card.
- Douyin and TikTok links in every form (a video opened over a list, a share page, the mobile site, a picture note) are one video with its caption, author, cover and the site's own player, and a short link is followed to where it goes. Their hot lists (Douyin's 热点, TikTok's Explore) are read signed out.
- Your Douyin and TikTok feeds are read from 精选 and Explore, where each card is a link: each video is kept with its caption, author and cover, and plays on its card. Douyin's search and either site's messages and following feed still need you signed in.
- A find with no picture, or one whose picture cannot be had, gets a text card of its own in the chat, the history list, the pet's card and the first-run tour: the title is larger and the summary has the room a picture would take, and a video with no cover still has its play button.
- The preferences card in Settings is simpler: the platforms and the topics you chose, and what the app has learned about you, which you can reset.
- The sample finds of the first-run tour are chosen to teach the app the most from your answers: each of your topics and platforms, video and text, and a couple outside your topics come up, from different sites and subjects, so ten answers say more about what you like.
- Finds from your signed-in feeds (Douyin, Xiaohongshu, Weibo, TikTok and the rest) now keep their cover, and a card whose picture failed to load once asks again instead of staying blank; more covers are kept from sites that serve large photos, pages of one site are asked for theirs one at a time, and covers named without https are fetched over it.

### Updates

- Settings › About shows the version, checks for a new release on request, and says what to do for the way Mibo runs here. The installed Windows app updates itself from there: it downloads the installer, checks it, closes, installs over the same folder with the options chosen at the first install, and opens again on the same data. The first start after says in the chat which version is now running, or that the update did not finish, with the release page. The first such update is from 0.2.0 to the release after it.
- The installer is taken only from the release the app's own check found, newer than this version, over https from GitHub, no larger than the release lists it; its SHA-256 must match the release's `SHA256SUMS.txt`, and once a release with a signed checksum file is installed, an unsigned one is refused. Setup runs as you, never as administrator, and the file is held unchanged from the check until it starts. Only the button in the app's own window starts an update; the character cannot.
- The Mac app downloads and checks the new disk image and opens it for you to drag over the old copy. A pip install, a checkout and the zip are shown the command or the download that updates them.

### Settings

- The character knows the app's settings: it can list them, open Settings at an item and change one. A change that widens nothing is made at once; keys are never shown.
- The notice that page text, window pictures and file text go to the model service you chose is shown once, when a service is first saved, and again only when the service changes.
- The interface has a new palette: primary actions are ink, as the send button is, and links, switches, focus and "new" tags share one quiet blue that no longer changes with the character. The character's own colour marks only the character: its face, its card in the picker and the line along the window's top.

### Models

- On a model with a small context window, the first request is smaller: tools are sent in order of need while they fit, the rest are loaded on demand, and an installed skill is listed by its description alone, and the list of skills is shorter: past its room for that window, a skill is listed by name. When a model service refuses a request as too long and states its size, the request is fitted again to that size.

### Documentation

- The READMEs, the in-app about line and the package descriptions now present Mibo as a personal agent on your own computer, with the character second.

### Fixes

- Mibo's icon stays in the notification area for as long as the app runs, with the window open or the pet out too. It used to appear only once the window was put away.
- A command's `PATH` starts from Windows' real folder. On a computer where Windows is not in `C:\Windows` it named a folder that does not exist.
- In first-run setup, a model service that is not in the list is reported as an invalid service, not as a general failure.
- In Settings, clicking the label of a key field focuses the field.
- The line a scheduled task writes when it stops at a limit or fails is in the language in use when it is written.
- Stop pressed while a reply is still starting always ends that reply; after a slow start the press used to be lost.
- On a busy computer, the first command after the app starts is no longer treated as unreadable when Windows PowerShell is slow to start.
- The app starts about 0.2 s sooner: the feed parser is loaded when the first feed is read.

### Development

- The largest modules and scripts are split by what they do; the largest source file went from 2,700 lines to under 900. Behaviour changes only where this list says so.
- The lint rule set is written in `pyproject.toml`, and CI runs `ruff check .` over the whole repository.
- The suite runs one process per core: `python -m pytest -q -n auto --dist loadfile`.
- `python -m mibo.taste_replay replay` replaces `python -m mibo.taste replay`.

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

[Unreleased]: https://github.com/wangkant/mibo/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/wangkant/mibo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wangkant/mibo/releases/tag/v0.1.0
