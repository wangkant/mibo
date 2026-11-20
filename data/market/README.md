# The skill market's catalog

`skills.json` lists public [Agent Skills](https://agentskills.io) (folders holding a `SKILL.md`) that Mibo's skill market offers. It points at skills and does not copy them. No skill's text or files are in this repository or in the app's package. An entry holds facts about one skill: where it lives (repository, folder, the full commit it was read at, a page to open), its licence, a category, what it needs, how well it fits Mibo, how popular it is, what a safety scan found, and a hash of its folder. Each title and one-sentence description, in Chinese and English, was written for the catalog from the skill's own description. When a person presses install, the app fetches the folder from its own public source at the entry's commit and checks that the hash matches before writing anything.

The app ships this file as a snapshot. At most once a day it fetches a fresh copy from `https://raw.githubusercontent.com/wangkant/mibo/main/data/market/skills.json` (the constant `CATALOG_URL` in `mibo/skills/market.py`). That address follows this repository, which is to be renamed. If the fetch fails, the app keeps using the snapshot. The catalog is data from the network: the app reads nothing in it as an instruction, escapes every string it shows, and drops any entry that points outside a public https git host.

`categories.json` holds the fixed categories' names in Chinese and English. `notes.json` holds the English of the Chinese notes the catalog writes.

## What it holds (build of 2026-11-20)

1,386 skills from 60 repositories: 23 publishers of their own product or model (Anthropic, OpenAI, Google, Vercel, Hugging Face, ElevenLabs, Notion, Obsidian, 飞书, MiniMax, DeepSeek, ByteDance and others), 19 community collections and 18 Chinese-language collections. 38 copies of a skill already listed and 4 folders the app could not load were left out; with them, two repositories have nothing listed (sergebulaev/linkedin-skills holds a link, alchaincyf/huashu-art-motion is too large).

- Licence: 1,352 installable (794 MIT, 502 Apache-2.0, 16 BSD-3-Clause, 1 CC-BY-4.0, 1 AGPL-3.0, 38 with no licence stated); 34 not installable (17 restricted or unclear, 17 non-commercial).
- Fit: 441 `ready`, 712 `partial`, 233 `no`.
- Scan: 821 `none`, 504 `low`, 61 `high`.

Left out on purpose: repositories made only for building on one cloud (google/skills, microsoft/azure-skills), for ML engineering (Orchestra-Research/AI-Research-SKILLs) or for code auditing (trailofbits/skills); Composio's 832 generated per-app wrappers; link lists that hold no skills of their own (the awesome lists); and large aggregators of copied skills. Skills distributed outside git, such as ClawHub's registry, are not included because they carry no readable licence and no commit to check against.

## How it is built

```
python tools/skillmarket/build.py --cache <folder>
python tools/skillmarket/check.py --cache <folder>
```

`tools/skillmarket/sources.json` lists the repositories to walk. Original publishers come before collections that gather other people's skills. A repository's `skip` says why it is left out, and its `exclude` lists folders left out of it (a repository's own bots, copies kept for other agent hosts, generated wrappers). For each repository the builder:

- Resolves the default branch to a commit (`git ls-remote`).
- Downloads one archive at that commit from `codeload.github.com` and keeps only the skill folders, the licence files above them and the README, in the cache.
- Finds every `SKILL.md` and reads its front matter with the app's own parser. Skills the app could not load are left out: bad name, no description, no body, links or refused names in the folder, or too large.
- Reads the licence that governs each skill (see below).
- Notes the scripts beside a skill and the runtimes they need.
- Dates each folder by the last commit that touched it, from a blobless clone that is deleted afterwards.
- Reads stars from GitHub's API, one call per repository, cached for the day.
- Reads install counts from the repository's public page on skills.sh. Those counts are rounded the way the page shows them.

The builder files each skill in one of the fixed categories, judges how well it fits Mibo and runs the market's own scan (`market.scan`, the same scan the app repeats on the downloaded folder before it installs). It leaves out forks and copies: when two folders are the same skill (same hash, same instructions, or same name and description), the first in source order is kept. Titles and descriptions come from `tools/skillmarket/texts.json`. A new skill, or one whose description changed, stops the build and is listed in `<cache>/pending_texts.json` until its texts are written.

The fit values are:

- `ready`: plain instructions, or uses only what Mibo has (web search and reading, the built-in browser, commands and files in granted folders, other programs).
- `partial`: part of it needs something Mibo lacks: an MCP server, an API key, image generation, subagents, a runtime such as Node.js, a vendor's command-line tool, or another host's features. `fit_note` says which.
- `no`: made for a coding agent's sandbox or for one vendor's product.

`check.py` checks every entry offline:

- The fixed shape.
- Unique ids, folders and hashes.
- Sources only on public https git hosts, at a full commit.
- A licence marked installable only when it was read and is open, or when no licence is stated.
- No written text that repeats a long run of the skill's own description.
- No spoken Chinese.

Online, it takes a sample from every repository, fetches each folder fresh from its host the way the installer does, compares the hash and opens the source page.

The hash is `market.folder_hash`: sha256 over one line per file, sorted by the file's path inside the folder (POSIX, UTF-8), each line `path NUL sha256-of-the-bytes-in-hex LF`.

## The licence rule

Licences are read, not assumed. A licence file in the skill's own folder governs. Otherwise the `license` field of its front matter governs. Otherwise the nearest licence file above it governs, and failing that, a licence the README names. When the field and the file above disagree on whether the skill is open (one says MIT, the other non-commercial), the narrower one governs. The file's words are matched against the public licences: MIT, Apache-2.0, BSD, ISC, the Unlicense, CC0, CC-BY, the GPL family, MPL and CC-BY-SA.

- **Installable:** licences that allow use and redistribution (MIT, Apache-2.0, BSD, ISC, CC0, CC-BY and the like). Share-alike licences (GPL, AGPL, CC-BY-SA, MPL) also allow redistribution, and their note says so.
- **No licence stated (`NONE`):** listed as 未声明许可. The person may still install it from its own source, and the page says that plainly before the press.
- **Restricted:** licences that restrict where or for what a skill may be used (to a vendor's own products, or no commercial use) are listed and linked to their source, but cannot be installed from here.
- **Unsure (`CUSTOM`):** text that is none of the above is not installable.

## The safety scan

A skill is material for the model and grants nothing. Installing it runs nothing. Scripts beside a skill still run only through the command gate, with a card that names the skill. The scan looks for:

- Instructions that address the model against its person. A phrase quoted as an example of injected text to refuse ("ignore previous instructions") does not count.
- Addresses that receive data.
- Encoded code that is run.
- Scripts that download and run code, read credentials or browser data, or change system settings.

Any of these makes a skill `high` risk, and a high-risk skill cannot be installed from the market. Scripts, package installs, network use or long encoded text make it `low`. Each note names a rule and a file, never the file's words.

## Removal and corrections

A publisher who wants a skill or a whole repository left out, or a fact corrected (licence, category, fit, description), can open an issue at <https://github.com/wangkant/mibo/issues> with the entry's `id`. A removal goes into `removed` in `tools/skillmarket/sources.json` (as `owner/repo` or `owner/repo/path`) and takes effect with the next build. The app picks it up within a day of the catalog being published.
