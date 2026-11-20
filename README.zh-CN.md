# Mibo

一个住在桌面上的伙伴：一个角色，与你对话、记住你、每次为你带来一件值得看的内容，并可代你在网页、其他程序和文件中操作；每一次操作都先由你在卡片上确认。

<p>
  <a href="https://github.com/wangkant/mibo/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI&labelColor=24292f" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square&labelColor=24292f" alt="Python 3.10–3.14"></a>
  <a href="https://github.com/wangkant/mibo/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square&labelColor=24292f" alt="许可证：Apache 2.0"></a>
</p>

[English](README.md) · **简体中文**

Mibo 运行在你自己的电脑上，使用你自己的模型服务，所保存的内容都在本机的一个文件夹中。目前优先支持 Windows 10 和 11。它尚未发布：暂无安装包可供下载，需从本仓库运行。

## 功能

- **对话。** 一个有自己语气的角色，既在窗口中，也以桌面上的小形象出现。可选用内置角色，也可自行编写。模型由你提供：任何兼容 OpenAI 对话接口的服务，使用你自己的密钥。
- **记忆。** 你告诉它的事以带日期的事实和计划保存，可在“设置 › 记忆”中查看、修改或删除。在对话中说“记住……”“忘掉……”同样有效。证件号、银行卡号、密码和验证码不予保存。
- **每次推荐一件内容。** 它在后台读取公开来源，并根据你对所展示内容的实际反应了解你的偏好：以停留时长为准，仅点开不代表喜欢。每张卡片都说明推荐原因，可选择“不感兴趣”并注明原因，也可撤销；展示过的内容均可在“推荐记录”中找回。推荐频率和免打扰时段由你设定。
- **以访客身份外出浏览。** 只读取公开网页，不登录任何账号，遵守 robots.txt；你让它查找某件事时，它会告知查找结果。
- **内置浏览器，对话在网页旁。** 在对话中提出要求，它即代你操作网页。发送、发布、上传文件、下载以及前往其他网站，均须你确认。它报告的结果会与网页上的实际变化核对。
- **操作其他程序**（Windows）。按“开始”菜单中的名称查找程序，操作前先征得同意，你正在使用键盘鼠标时会等待，一项任务最多可跨三个程序完成。
- **命令与文件，仅限你授权的文件夹。** 每条命令在运行前都会被解析；需要你同意时，以通俗的文字说明其作用。删除的文件进入回收站，每一轮的文件改动可在回复下方撤销。
- **技能与连接器。** 技能是带有 `SKILL.md` 的文件夹，可来自经过审核的技能市场，也可自行添加。MCP 服务器一键连接，在浏览器中完成登录，令牌保存在系统的凭据存储中。
- **定时任务**，以及可检索的**以往对话**。
- **十种界面语言**：English、简体中文、繁體中文、日本語、한국어、Español、Français、Deutsch、Português (Brasil)、Русский。

## 不会做的事

- 不读取、不输入密码、支付信息或验证码。登录始终由你本人完成。
- 付款、购买、删除以及任何涉及账号安全的操作，每次都会询问，不提供“始终允许”。
- 无人值守时不会自行运行，除非你设置了定时任务。定时任务只读取内容；超出你对该任务授权范围的操作，会留作按钮等你确认。
- 你的登录状态和 Cookie 不会离开本机。模型密钥只发送给你选择的模型服务。

## 运行

需要 Python 3.10 至 3.14。

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

`mibo` 会打开窗口并引导完成首次设置：语言、角色、模型密钥、关注的话题。Windows 使用系统自带的 WebView2（Windows 10 和 11 均已包含）。在 macOS 和 Linux 上，请使用 `python -m pip install -e ".[app]"` 安装窗口组件；操作其他程序和内置浏览器目前仅支持 Windows。

Mibo 保存的所有内容都在一个文件夹中：默认为 `~/mibo`，也可通过 `mibo --home DIR` 指定。

## 开发

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI 在 Linux（Python 3.10 至 3.14）和 Windows 上运行测试，并构建安装包后在干净环境中安装。测量脚本位于 `tools/`：`tools/recsim` 为推荐模拟用户，`tools/opbench.py` 与 `tools/optruth.py` 在练习站点上检验网页操作，`tools/copy_check.py` 检查中文界面文字是否为书面语。参见[贡献指南](.github/CONTRIBUTING.md)。

## 当前状态

项目仍在建设中。已知且尚未修复的问题：

- 记忆的后台写入在验收测试中尚未达到被替换代码的水平。
- 在 Windows 上，页面自带的“最大化”按钮无法使窗口最大化；关闭窗口后进程可能仍未退出。
- 本说明仅有两种语言，界面有十种。

## 许可证

[Apache License 2.0](LICENSE)。改编自其他项目的代码保留其原许可证（见 [NOTICE](NOTICE)）；角色立绘采用 CC BY-NC-SA 4.0（[其许可证](mibo/static/characters/LICENSE.md)）。另见[免责声明](docs/DISCLAIMER.zh-CN.md)。
