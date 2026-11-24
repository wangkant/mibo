# Mibo

**运行在你电脑上的个人 AI 智能体：只需说明要求，它便在网页、文件和其他程序中完成任务。**

Mibo 在本机运行，使用你自己选择的模型服务，不依赖云端主机，登录状态和文件保留在你的电脑上；发送给模型的内容仅到达你选择的模型服务。交代的任务会执行到底，完成后向你汇报，也可按时自行执行。仅在涉及付款等会造成损失的操作、无法撤销的操作，或你未要求的操作时询问；验证码、密码和付款信息始终由你本人处理。它同时是一个有名字、有形象、记得你的角色。

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
| **外出** | 以访客身份浏览公开网页，不登录，遵守 robots.txt。网页一次读完，保留标题和表格。网页搜索无需密钥。 |
| **内置浏览器**（Windows） | 链接在对话旁打开，支持标签页、无痕标签页和下载。角色可查看网页，并在网页上点击、输入、选择、拖动和上传文件。 |
| **消息** | 询问你的消息时，角色读取你已登录的网站，并报告新内容。该步骤只读取：网页交给不带工具的模型调用处理。 |
| **其他程序**（Windows） | 通过 UI Automation 读取并操作其他程序的窗口，包括 Electron 应用；仅在你未使用键盘和鼠标时操作。 |
| **文件与命令** | 用户文件夹和其他磁盘均可使用，无需事先授权；存放密码、密钥、浏览器资料或其他程序数据的位置始终不读取，在设置中设为仅查看或移除的文件夹保持你的设置。Word、Excel 和 PowerPoint 文档直接生成为文件。命令在运行前解析；每轮的文件改动可撤销；在 Windows 上，删除的文件进入回收站。 |
| **技能与连接器** | 技能（含 `SKILL.md` 的文件夹）与 MCP 服务器，均提供经筛选的市场。消息以 `/name`（技能名称）开头时直接启用该技能。 |
| **设置** | 角色了解应用的设置：可列出设置、打开设置的相应条目并修改。不扩大权限的修改立即生效；密钥从不显示。 |
| **定时任务** | 提醒、任务和按周期进行的条件检查。运行时仅读取信息，以及执行创建任务时允许的操作；定期发送或发布的任务，仅在你指定的网站、对象和操作类型和文字范围内执行。 |
| **推荐** | 从公开来源中每次推荐一项内容，依据停留时长而非点击排序。每张卡片注明推荐原因，支持反馈与撤销。 |
| **语言** | 十种界面语言。 |

## 角色

<p align="center"><img src="docs/readme/characters.webp" alt="Mibo · 白龙 · 大肥鱼 · 大小姐" width="100%"></p>

<p align="center">Mibo · 白龙 · 大肥鱼 · 大小姐</p>

## 安装

请从[最新版本](https://github.com/wangkant/mibo/releases/latest)页面下载。安装包未经代码签名，首次启动前系统会显示警告。

| 系统 | 文件 | 首次启动 |
|---|---|---|
| Windows 10 或 11（x64） | `mibo-0.2.0-setup.exe` | 如浏览器提示该文件不常被下载，请选择「保留」。SmartScreen 显示「Windows 已保护你的电脑」时，请选择「更多信息」，再选择「仍要运行」。安装程序仅为当前账户安装，无需管理员权限。 |
| macOS（Apple 芯片） | `mibo-0.2.0-macos-arm64.dmg` | 打开磁盘映像，将 `mibo.app` 拖入「应用程序」文件夹。应用未经公证，首次打开会被阻止：请关闭提示，然后在「系统设置 › 隐私与安全性」中选择「仍要打开」并确认。 |

新版本以同样方式覆盖安装。卸载时保留数据文件夹。

### 不使用安装程序

| | |
|---|---|
| **Windows 免安装版** | 下载 `mibo-0.2.0-windows-x64.zip`，解压到任意位置后运行 `mibo.exe`。该文件同样未经代码签名。 |
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
| **你的模型服务** | 接收你的消息、相关记忆、回复所用的网页和文件内容，以及交由审查判断的操作步骤。模型密钥仅发送至该服务。提示在首次保存服务时显示一次，更换服务后才再次显示。 |
| **网站** | 外出浏览以未登录状态读取公开网页，默认每天三次（「设置 › 外出」）；回复按需读取网页。登录状态仅保存在内置浏览器中，也仅在其中使用。 |
| **其他服务** | 回复需要搜索时发送搜索词；每天最多一次向 GitHub 发送版本号以检查更新；打开市场时查询目录；角色调用 MCP 服务器工具时发送相应参数。 |
| **每次确认** | 代价较大的步骤在任何模式下每次单独确认：付款或花费、无法恢复的删除、账号本身、交出访问权限或私密信息、具有约束力的提交、撤销无法还原的本机改动。先前的同意和定时任务均不涵盖。进入回收站的删除无需确认。此类步骤以卡片询问，卡片上的按钮写明具体操作；仅你在聊天框中输入的消息或你对该卡片的点按可作为同意。 |
| **读到的内容** | 工具从网页或本机读到的内容只是素材，从不是指令。读取之后，向你未指明的地方发送内容须确认，照搬其中的命令亦然。下载的程序绝不运行。 |
| **绝不执行** | 代你输入密码、验证码和支付信息（均由你本人输入）；以管理员身份运行任何程序；读取模型密钥、应用设置和内置浏览器的配置文件，任何工具都无法打开它们。 |
| **命令** | 在 Windows 上，每条命令还受 Windows 自身的限制：没有管理员权限，无法访问应用自身的文件，无法脱离其所在的进程组，无法使用剪贴板；判定为只读的命令无法更改任何文件或设置。这些限制不阻止命令读取你的其他文件或连接网络，这两项由运行前的解析和你的同意把关。 |
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
