# Mibo

桌面伙伴应用。一个角色与你对话、记住你、每次推荐一项内容，并可代你在网页、其他程序和文件中执行操作。凡会产生实际影响的操作，均须经你确认。

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![许可证：Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](LICENSE)

[English](README.md) · **简体中文** · [繁體中文](docs/readme/README.zh-TW.md) · [日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) · [Español](docs/readme/README.es.md) · [Français](docs/readme/README.fr.md) · [Deutsch](docs/readme/README.de.md) · [Português (Brasil)](docs/readme/README.pt-BR.md) · [Русский](docs/readme/README.ru.md)

Mibo 在本机运行，使用你自备的模型服务，数据保存在本机的单个文件夹中。目标平台为 Windows 10 和 11。

> **状态：** 预发布。尚未提供安装包，需从源码运行。

## 功能

| | |
|---|---|
| **对话** | 单一角色，以窗口和桌面形象两种形式呈现。可选用内置角色或自行编写。支持任何兼容 OpenAI 接口的模型服务，使用你自己的密钥。 |
| **记忆** | 以带日期的事实和计划记录与你相关的信息，可在设置中查看和修改。证件号、银行卡号、密码、验证码等敏感信息不予保存。 |
| **推荐** | 从公开来源中每次推荐一项内容，依据停留时长而非点击排序。每张卡片注明推荐原因，支持反馈与撤销。 |
| **网页** | 以访客身份读取公开网页，遵守 robots.txt。内置浏览器中对话位于网页一侧，可按要求操作网页。 |
| **程序**（Windows） | 通过 UI Automation 查找并操作其他程序，逐个程序授权，且不在你输入时操作。 |
| **文件与命令** | 仅限已授权的文件夹。命令在运行前解析；删除的文件进入回收站；每轮的文件改动可撤销。 |
| **扩展** | 技能（含 `SKILL.md` 的文件夹）与 MCP 连接器，均提供经筛选的市场。连接器令牌保存在系统凭据存储中。 |
| **其他** | 定时任务、以往对话检索、十种界面语言。 |

## 安全

- 不读取、不输入密码、支付信息和验证码。
- 付款、删除以及涉及账号安全的更改，每次均须确认。
- 除你创建的定时任务外，不会在无人值守时运行；定时任务在授权范围之外只读。
- 登录状态和 Cookie 仅保存在本机。模型密钥仅发送至你选择的模型服务。

## 快速开始

需要 Python 3.10–3.14。

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

首次运行时需选择语言、角色并填写模型密钥。从克隆目录运行时，数据保存在该目录中（已列入 .gitignore）；安装版保存在 `~/mibo`。可通过 `mibo --home DIR` 指定其他文件夹。

在 macOS 和 Linux 上，请使用 `python -m pip install -e ".[app]"` 安装。程序操作和内置浏览器仅支持 Windows。

## 开发

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI 在 Linux（Python 3.10–3.14）和 Windows 上运行测试，并验证构建所得安装包可在干净环境中安装。详见[贡献指南](.github/CONTRIBUTING.md)。

## 许可证

[Apache License 2.0](LICENSE)。第三方代码保留其原许可证（见 [NOTICE](NOTICE)）；角色立绘采用 CC BY-NC-SA 4.0（[说明](mibo/static/characters/LICENSE.md)）。另见[免责声明](docs/DISCLAIMER.zh-CN.md)。
