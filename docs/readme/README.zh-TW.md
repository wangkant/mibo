# Mibo

**執行在你電腦上的個人 AI 智慧體：只需說明需求，它便在網頁、檔案和其他程式中完成任務。**

Mibo 在本機執行，使用你自己選擇的模型服務，不依賴雲端主機，登入狀態和檔案保留在你的電腦上；傳送給模型的內容僅會到達你選擇的模型服務。交辦的任務會執行到底，完成後向你回報，也可按時自行執行。僅在涉及付款等會造成損失的操作、無法復原的操作，或你未要求的操作時詢問；驗證碼、密碼和付款資訊一律由你本人處理。它同時是一個有名字、有形象、記得你的角色。

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![版本](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![授權：Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · **繁體中文** · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

<p align="center"><img src="mibo-en.svg" alt="Mibo" width="84%"></p>

## 功能

| 領域 | |
|---|---|
| **對話** | 單一角色，以視窗呈現；在 Windows 上另有桌面形象。可選用內建角色或自行編寫。支援任何相容 OpenAI 介面的模型服務，以及本機執行的 Ollama 和 LM Studio。模型選單顯示上下文佔用，並提供「立即歸納」和「清空上下文」。 |
| **記憶** | 以附日期的事實和計畫記錄與你相關的資訊，可在「設定 › 記憶」中檢視和修改。證件號碼、信用卡號、密碼和驗證碼不予儲存。無痕對話不留紀錄。 |
| **外出** | 以訪客身分瀏覽公開網頁，不登入，遵守 robots.txt。網頁一次讀完，保留標題和表格。網頁搜尋無需金鑰。 |
| **內建瀏覽器**（Windows） | 連結在對話旁開啟，支援分頁、無痕分頁和下載。角色可檢視網頁，並在網頁上點擊、輸入、選擇、拖曳和上傳檔案。 |
| **訊息** | 詢問你的訊息時，角色讀取你已登入的網站，並回報新內容。該步驟只讀取：網頁交給不帶工具的模型呼叫處理。 |
| **其他程式**（Windows） | 透過 UI Automation 讀取並操作其他程式的視窗，包括 Electron 應用程式；僅在你未使用鍵盤和滑鼠時操作。 |
| **檔案與命令** | 限於你的桌面、文件、下載、圖片、音樂和影片資料夾，以及你授權的資料夾。Word、Excel 和 PowerPoint 文件直接產生為檔案。命令在執行前解析；每輪的檔案變更可復原；在 Windows 上，刪除的檔案移至資源回收筒。 |
| **技能與連接器** | 技能（含 `SKILL.md` 的資料夾）與 MCP 伺服器，均提供經篩選的市集。訊息以 `/name`（技能名稱）開頭時直接啟用該技能。 |
| **設定** | 角色了解應用程式的設定：可列出設定、開啟設定的相應項目並修改。不擴大權限的變更立即生效；金鑰從不顯示。 |
| **排程任務** | 提醒、任務和依週期進行的條件檢查。執行時僅讀取資訊，以及執行建立任務時允許的操作；定期傳送或發佈的任務，僅在你指定的網站、對象和操作類型和文字範圍內執行。 |
| **推薦** | 從公開來源中每次推薦一項內容，依據停留時間而非點擊排序。每張卡片註明推薦原因，支援回饋與復原。 |
| **語言** | 十種介面語言。 |

## 角色

<p align="center"><img src="characters.webp" alt="Mibo · 白龍 · 大肥魚 · 大小姐" width="100%"></p>

<p align="center">Mibo · 白龍 · 大肥魚 · 大小姐</p>

## 安裝

請從[最新版本](https://github.com/wangkant/mibo/releases/latest)頁面下載。安裝程式未經程式碼簽署，首次啟動前系統會顯示警告。

| 系統 | 檔案 | 首次啟動 |
|---|---|---|
| Windows 10 或 11（x64） | `mibo-0.1.0-setup.exe` | 如瀏覽器提示此檔案不常被下載，請選擇「保留」。SmartScreen 顯示「Windows 已保護您的電腦」時，請選擇「其他資訊」，再選擇「仍要執行」。安裝程式僅為目前帳戶安裝，無需系統管理員權限。 |
| macOS（Apple 晶片） | `mibo-0.1.0-macos-arm64.dmg` | 開啟磁碟映像檔，將 `mibo.app` 拖入「應用程式」檔案夾。應用程式未經公證，首次開啟會遭到阻擋：請關閉提示，然後在「系統設定 › 隱私權與安全性」中選擇「強制打開」並確認。 |

新版本以相同方式覆蓋安裝。解除安裝時保留資料資料夾。

### 不使用安裝程式

| | |
|---|---|
| **Windows 免安裝版** | 下載 `mibo-0.1.0-windows-x64.zip`，解壓縮到任意位置後執行 `mibo.exe`。此檔案同樣未經程式碼簽章。 |
| **Scoop**（Windows） | 執行 `scoop bucket add mibo https://github.com/wangkant/scoop-mibo`，然後執行 `scoop install mibo`。 |
| **Homebrew**（macOS，Apple 晶片） | 執行 `brew install --cask wangkant/mibo/mibo`。 |
| **透過 Python 安裝**（3.10–3.14，任何系統） | 執行 `pipx install "mibo[app,web]"` 或 `uv tool install "mibo[app,web]"`，然後執行 `mibo`。 |

### 從原始碼執行（Linux 與開發）

需要 Python 3.10–3.14。

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` 在 macOS 和 Linux 上安裝視窗元件，`web` 安裝外出瀏覽所需的 Playwright。開發時請安裝 `".[dev]"` 並執行 `python -m pytest -q`，詳見[貢獻指南](../../.github/CONTRIBUTING.md)（英文）。

## 首次啟動

1. 依序選擇語言、角色和模型，再選擇感興趣的主題並簡要介紹自己。
2. 選擇模型時，可選擇服務並貼上其金鑰，可透過 OpenRouter 登入使用其免費模型，也可在 Ollama 或 LM Studio 執行時直接選用。
3. 金鑰儲存在系統認證存放區中（Windows 認證管理員、macOS 鑰匙圈、Linux 上的 Secret Service），不寫入任何檔案。系統沒有認證存放區時，金鑰儲存在僅目前帳戶可讀取的 `credentials.json` 中，「設定 › 本機」會註明此情況。

資料集中儲存在一個資料夾中：安裝版為 `~/mibo`，從原始碼執行時為複製的儲存庫本身，也可透過 `mibo --home DIR` 指定。設定儲存在該資料夾的 `settings.json` 中。Mibo 預設在登入時啟動，可在「設定 › 本機」中關閉。

## 隱私與安全

| | |
|---|---|
| **你的模型服務** | 接收你的訊息、相關記憶、回覆所用的網頁和檔案內容，以及交由審查判斷的操作步驟。模型金鑰僅傳送至該服務。提示在首次儲存服務時顯示一次，更換服務後才再次顯示。 |
| **網站** | 外出瀏覽以未登入狀態讀取公開網頁，預設每天三次（「設定 › 外出」）；回覆依需要讀取網頁。登入狀態僅儲存在內建瀏覽器中，也僅在其中使用。 |
| **其他服務** | 回覆需要搜尋時傳送搜尋詞；每天最多一次向 GitHub 傳送版本號以檢查更新；開啟市集時查詢目錄；角色呼叫 MCP 伺服器工具時傳送相應參數。 |
| **每次確認** | 代價較大的步驟在任何模式下每次單獨確認：付款或花費、無法復原的刪除、帳號本身、交出存取權限或私密資訊、具有約束力的提交、復原無法還原的本機變更。先前的同意和排程任務均不涵蓋。進入資源回收筒的刪除無須確認。僅你在聊天框中輸入的訊息可作為同意。 |
| **讀到的內容** | 工具從網頁或本機讀到的內容只是素材，從不是指令。讀取之後，向你未指明的地方傳送內容須確認，照搬其中的命令亦然。下載的程式絕不執行。 |
| **絕不執行** | 代你輸入密碼、驗證碼和付款資訊（均由你本人輸入）；以系統管理員身分執行任何程式；讀取模型金鑰、應用程式設定和內建瀏覽器的設定檔，任何工具都無法開啟它們。 |
| **無人看管** | 僅限外出瀏覽和你建立的排程任務。 |

[安全政策](../../.github/SECURITY.md)（英文）列出了全部資料去向及各類資料的儲存位置。

## 系統需求

| | Windows | macOS | Linux |
|---|---|---|---|
| **安裝方式** | 安裝程式 | 磁碟映像檔 | 從原始碼執行 |
| **系統** | Windows 10 或 11，x64 | Apple 晶片 | Python 3.10–3.14 |
| **內建瀏覽器、其他程式、桌面形象** | 支援 | 不支援 | 不支援 |
| **外出瀏覽** | 系統內建的 Edge | Edge、Chrome 或 Chromium | Edge、Chrome 或 Chromium |
| **模型** | 相容 OpenAI 介面的模型服務及其金鑰，或本機模型服務 | 同左 | 同左 |

## 授權

[Apache License 2.0](../../LICENSE)。第三方程式碼保留其原授權（見 [NOTICE](../../NOTICE)）；角色立繪採用 CC BY-NC-SA 4.0（[說明](../../mibo/static/characters/LICENSE.md)）。另見[免責聲明](../DISCLAIMER.zh-TW.md)和[更新紀錄](../../CHANGELOG.md)（英文）。
