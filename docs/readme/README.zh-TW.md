# Mibo

桌面夥伴應用程式。一個角色與你對話、記住你、每次推薦一項內容，並可代你在網頁、其他程式和檔案中執行操作。凡會產生實際影響的操作，均須經你確認。

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![授權：Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · **繁體中文** · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

Mibo 在本機執行，使用你自備的模型服務，資料儲存在本機的單一資料夾中。目標平台為 Windows 10 和 11。

> **狀態：** 預發布。尚未提供安裝程式，需從原始碼執行。

## 功能

| | |
|---|---|
| **對話** | 單一角色，以視窗和桌面形象兩種形式呈現。可選用內建角色或自行編寫。支援任何相容 OpenAI 介面的模型服務，使用你自己的金鑰。 |
| **記憶** | 以附日期的事實和計畫記錄與你相關的資訊，可在設定中檢視和修改。證件號碼、信用卡號、密碼、驗證碼等敏感資訊不予儲存。 |
| **推薦** | 從公開來源中每次推薦一項內容，依據停留時間而非點擊排序。每張卡片註明推薦原因，支援回饋與復原。 |
| **網頁** | 以訪客身分讀取公開網頁，遵守 robots.txt。內建瀏覽器中對話位於網頁一側，可依要求操作網頁。 |
| **程式**（Windows） | 透過 UI Automation 尋找並操作其他程式，逐一程式授權，且不在你輸入時操作。 |
| **檔案與命令** | 僅限已授權的資料夾。命令在執行前解析；刪除的檔案移至資源回收筒；每輪的檔案變更可復原。 |
| **擴充** | 技能（含 `SKILL.md` 的資料夾）與 MCP 連接器，均提供經篩選的市集。連接器權杖儲存在系統認證存放區中。 |
| **其他** | 排程工作、過往對話搜尋、十種介面語言。 |

## 安全

- 不讀取、不輸入密碼、付款資訊和驗證碼。
- 付款、刪除以及涉及帳號安全的變更，每次均須確認。
- 除你建立的排程工作外，不會在無人看管時執行；排程工作在授權範圍之外僅能讀取。
- 登入狀態和 Cookie 僅儲存在本機。模型金鑰僅傳送至你選擇的模型服務。

## 快速開始

需要 Python 3.10–3.14。

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

首次執行時需選擇語言、角色並填寫模型金鑰。從複製的儲存庫執行時，資料儲存在該目錄中（已列入 .gitignore）；安裝版儲存在 `~/mibo`。可透過 `mibo --home DIR` 指定其他資料夾。

在 macOS 和 Linux 上，請使用 `python -m pip install -e ".[app]"` 安裝。程式操作和內建瀏覽器僅支援 Windows。

## 開發

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI 在 Linux（Python 3.10–3.14）和 Windows 上執行測試，並驗證建置所得的安裝套件可在乾淨環境中安裝。詳見[貢獻指南](../../.github/CONTRIBUTING.md)。

## 授權

[Apache License 2.0](../../LICENSE)。第三方程式碼保留其原授權（見 [NOTICE](../../NOTICE)）；角色立繪採用 CC BY-NC-SA 4.0（[說明](../../mibo/static/characters/LICENSE.md)）。另見[免責聲明](../DISCLAIMER.zh-TW.md)。
