# Mibo

デスクトップコンパニオンアプリです。ひとりのキャラクターが会話し、利用者のことを記憶し、一度にひとつずつおすすめを届け、ウェブ、他のプログラム、ファイルで利用者に代わって操作します。影響を伴う操作は、すべて利用者の承認を待ってから実行されます。

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![ライセンス：Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · **日本語** · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

Mibo は利用者が用意したモデルを使ってローカルで動作し、データをコンピューター上のひとつのフォルダーに保存します。対象は Windows 10 と 11 です。

> **状態：** プレリリース。インストーラーはまだ公開されていないため、ソースから実行してください。

## 機能

| | |
|---|---|
| **会話** | ひとりのキャラクターが、ウィンドウとデスクトップ上の姿で登場します。内蔵キャラクターまたは独自のキャラクターを使用できます。OpenAI 互換のモデルサービスであれば、利用者自身の API キーで利用できます。 |
| **記憶** | 利用者に関する事実と予定を日付付きで記録し、設定で確認・編集できます。身分証番号、カード番号、パスワード、認証コードなどの機微な識別情報は保存しません。 |
| **おすすめ** | 公開された情報源から一度にひとつずつ届け、クリック数ではなく閲覧時間で順位を決めます。各カードには理由が示され、フィードバックと取り消しに対応します。 |
| **ウェブ** | 公開ページを訪問者として読み、robots.txt に従います。内蔵ブラウザーではページの横に会話が表示され、依頼に応じてページを操作します。 |
| **プログラム**（Windows） | UI Automation で他のプログラムを見つけて操作します。プログラムごとに許可を求め、利用者が入力している間は操作しません。 |
| **ファイルとコマンド** | 許可したフォルダーに限られます。コマンドは実行前に解析され、削除したファイルはごみ箱に移り、各ターンのファイル変更は元に戻せます。 |
| **拡張機能** | スキル（`SKILL.md` を含むフォルダー）と MCP コネクタ。それぞれ厳選されたマーケットがあります。コネクタのトークンはシステムの資格情報ストアに保存されます。 |
| **その他** | スケジュールされたタスク、過去の会話の検索、10 か国語のインターフェース。 |

## 安全性

- パスワード、支払い情報、認証コードを読み取ったり入力したりすることはありません。
- 支払い、削除、アカウントのセキュリティに関わる変更には、毎回確認が必要です。
- 利用者が作成したスケジュールタスクを除き、無人で実行されることはありません。スケジュールタスクも、許可した範囲を超える部分は読み取りのみです。
- サインイン情報と Cookie はコンピューター内にとどまります。モデルの API キーは、利用者が選んだモデルサービスにのみ送信されます。

## クイックスタート

Python 3.10–3.14 が必要です。

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

初回起動時に、言語、キャラクター、モデルの API キーを設定します。クローンから実行した場合、データはクローン内に保存されます（.gitignore 対象）。インストール版では `~/mibo` に保存されます。`mibo --home DIR` で別のフォルダーを指定できます。

macOS と Linux では `python -m pip install -e ".[app]"` でインストールしてください。プログラム操作と内蔵ブラウザーは Windows 専用です。

## 開発

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI は Linux（Python 3.10–3.14）と Windows でテストを実行し、ビルドした wheel がクリーンな環境にインストールできることを確認します。詳しくは [CONTRIBUTING](../../.github/CONTRIBUTING.md) を参照してください。

## ライセンス

[Apache License 2.0](../../LICENSE)。第三者のコードはそれぞれのライセンスに従います（[NOTICE](../../NOTICE)）。キャラクターの立ち絵は CC BY-NC-SA 4.0 です（[詳細](../../mibo/static/characters/LICENSE.md)）。[免責事項](../DISCLAIMER.ja.md)も参照してください。
