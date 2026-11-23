# Mibo

**住在桌面上的 AI 伙伴：既能陪伴，也能办事。**

角色有自己的形象和性格，与你对话、记住你、每次为你挑选一项值得看的内容。它不止于聊天：能浏览网页、操作电脑上的其他程序、处理文件和命令、使用技能和 MCP 连接器，并按时执行任务。应用在本机运行，使用你选择的模型服务。操作自动经过审查，仅在需要你决定时才在对话中询问：回复同意后，本次任务将执行完毕；付款、删除和账户变更始终单独确认。

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![版本](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![许可证：Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](LICENSE)

[English](README.md) · **简体中文** · [繁體中文](docs/readme/README.zh-TW.md) · [日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) · [Español](docs/readme/README.es.md) · [Français](docs/readme/README.fr.md) · [Deutsch](docs/readme/README.de.md) · [Português (Brasil)](docs/readme/README.pt-BR.md) · [Русский](docs/readme/README.ru.md)

<p align="center"><img src="docs/readme/mibo-zh.svg" alt="Mibo" width="84%"></p>

## 功能

| 领域 | |
|---|---|
| **对话** | 单一角色，以窗口呈现；在 Windows 上另有桌面形象。可选用内置角色或自行编写。支持任何兼容 OpenAI 接口的模型服务，以及本机运行的 Ollama 和 LM Studio。模型菜单显示上下文占用，并提供「立即归纳」和「清空上下文」。 |
| **记忆** | 以带日期的事实和计划记录与你相关的信息，可在「设置 › 记忆」中查看和修改。证件号、银行卡号、密码和验证码不予保存。无痕对话不留记录。 |
| **推荐** | 从公开来源中每次推荐一项内容，依据停留时长而非点击排序。每张卡片注明推荐原因，支持反馈与撤销。 |
| **外出** | 以访客身份浏览公开网页，不登录，遵守 robots.txt。网页一次读完，保留标题和表格。网页搜索无需密钥。 |
| **内置浏览器**（Windows） | 链接在对话旁打开，支持标签页、无痕标签页和下载。角色可查看网页，并在网页上点击、输入、选择、拖动和上传文件。 |
| **其他程序**（Windows） | 通过 UI Automation 读取并操作其他程序的窗口，包括 Electron 应用；仅在你未使用键盘和鼠标时操作。 |
| **文件与命令** | 限于你的桌面、文档、下载、图片、音乐和视频文件夹，以及你授权的文件夹。命令在运行前解析；每轮的文件改动可撤销；在 Windows 上，删除的文件进入回收站。 |
| **技能与连接器** | 技能（含 `SKILL.md` 的文件夹）与 MCP 服务器，均提供经筛选的市场。消息以 `/name`（技能名称）开头时直接启用该技能。 |
| **定时任务** | 提醒、任务和按周期进行的条件检查。运行时仅读取信息，以及执行创建任务时允许的操作。 |
| **语言** | 十种界面语言。 |

## 角色

<p align="center"><img src="docs/readme/characters.webp" alt="Mibo · 白龙 · 大肥鱼 · 大小姐" width="100%"></p>

<p align="center">Mibo · 白龙 · 大肥鱼 · 大小姐</p>

## 安装

请从[最新版本](https://github.com/wangkant/mibo/releases/latest)页面下载。安装包未经代码签名，首次启动前系统会显示警告。

| 系统 | 文件 | 首次启动 |
|---|---|---|
| Windows 10 或 11（x64） | `mibo-0.1.0-setup.exe` | 如浏览器提示该文件不常被下载，请选择「保留」。SmartScreen 显示「Windows 已保护你的电脑」时，请选择「更多信息」，再选择「仍要运行」。安装程序仅为当前账户安装，无需管理员权限。 |
| macOS（Apple 芯片） | `mibo-0.1.0-macos-arm64.dmg` | 打开磁盘映像，将 `mibo.app` 拖入「应用程序」文件夹。应用未经公证，首次打开会被阻止：请关闭提示，然后在「系统设置 › 隐私与安全性」中选择「仍要打开」并确认。 |

新版本以同样方式覆盖安装。卸载时保留数据文件夹。

### 不使用安装程序

| | |
|---|---|
| **Windows 免安装版** | 下载 `mibo-0.1.0-windows-x64.zip`，解压到任意位置后运行 `mibo.exe`。该文件同样未经代码签名。 |
| **Scoop**（Windows） | 运行 `scoop bucket add mibo https://github.com/wangkant/scoop-mibo`，然后运行 `scoop install mibo`。 |
| **Homebrew**（macOS，Apple 芯片） | 运行 `brew install --cask wangkant/mibo/mibo`。 |
| **通过 Python 安装**（3.10–3.14，任意系统） | 运行 `pipx install "mibo[app,web]"` 或 `uv tool install "mibo[app,web]"`，然后运行 `mibo`。 |

### 从源码运行（Linux 与开发）

需要 Python 3.10–3.14。

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` 在 macOS 和 Linux 上安装窗口组件，`web` 安装外出浏览所需的 Playwright。开发时请安装 `".[dev]"` 并运行 `python -m pytest -q`，详见[贡献指南](.github/CONTRIBUTING.md)（英文）。

## 首次启动

1. 依次选择语言、角色和模型，再选择感兴趣的主题并简要介绍自己。
2. 选择模型时，可选择服务并粘贴其密钥，可通过 OpenRouter 登录使用其免费模型，也可在 Ollama 或 LM Studio 运行时直接选用。
3. 密钥保存在系统凭据存储中（Windows 凭据管理器、macOS 钥匙串、Linux 上的 Secret Service），不写入任何文件。系统没有凭据存储时，密钥保存在仅当前账户可读的 `credentials.json` 中，「设置 › 本机」会注明这一点。

数据集中保存在一个文件夹中：安装版为 `~/mibo`，从源码运行时为克隆目录本身，也可通过 `mibo --home DIR` 指定。设置保存在该文件夹的 `settings.json` 中。Mibo 默认在登录时启动，可在「设置 › 本机」中关闭。

## 隐私与安全

| | |
|---|---|
| **你的模型服务** | 接收你的消息、相关记忆、回复所用的网页和文件内容，以及交由审查判断的操作步骤。模型密钥仅发送至该服务。 |
| **网站** | 外出浏览以未登录状态读取公开网页，默认每天三次（「设置 › 外出」）；回复按需读取网页。登录状态仅保存在内置浏览器中，也仅在其中使用。 |
| **其他服务** | 回复需要搜索时发送搜索词；每天最多一次向 GitHub 发送版本号以检查更新；打开市场时查询目录；角色调用 MCP 服务器工具时发送相应参数。 |
| **每次确认** | 付款或购买、删除，以及更改账号安全或访问权限，在任何模式下均须确认，对其他类型操作的同意不适用于此类操作。在银行、支付、医疗和邮件网站上的所有操作均须确认。仅你在聊天框中输入的消息可作为同意。 |
| **绝不执行** | 读取或输入密码、支付信息和验证码；以管理员身份运行任何程序；更改安全设置。 |
| **无人值守** | 仅限外出浏览和你创建的定时任务。 |

[安全策略](.github/SECURITY.md)（英文）列出了全部数据去向及各类数据的保存位置。

## 系统要求

| | Windows | macOS | Linux |
|---|---|---|---|
| **安装方式** | 安装程序 | 磁盘映像 | 从源码运行 |
| **系统** | Windows 10 或 11，x64 | Apple 芯片 | Python 3.10–3.14 |
| **内置浏览器、其他程序、桌面形象** | 支持 | 不支持 | 不支持 |
| **外出浏览** | 系统自带的 Edge | Edge、Chrome 或 Chromium | Edge、Chrome 或 Chromium |
| **模型** | 兼容 OpenAI 接口的模型服务及其密钥，或本机模型服务 | 同左 | 同左 |

## 许可证

[Apache License 2.0](LICENSE)。第三方代码保留其原许可证（见 [NOTICE](NOTICE)）；角色立绘采用 CC BY-NC-SA 4.0（[说明](mibo/static/characters/LICENSE.md)）。另见[免责声明](docs/DISCLAIMER.zh-CN.md)和[更新日志](CHANGELOG.md)（英文）。
