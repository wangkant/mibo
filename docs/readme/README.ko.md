# Mibo

**데스크톱에 사는 AI 컴패니언. 곁에 있어 주고, 일도 처리합니다.**

고유한 모습과 성격을 지닌 캐릭터가 사용자와 대화하고, 사용자를 기억하며, 볼 만한 것을 한 번에 하나씩 전합니다. 대화에 그치지 않습니다. 웹을 탐색하고, 컴퓨터의 다른 프로그램을 조작하고, 파일과 명령을 다루고, 스킬과 MCP 커넥터를 사용하며, 예약된 작업을 실행합니다. 사용자의 컴퓨터에서 사용자가 고른 모델 서비스로 실행됩니다. 작업은 자동으로 검토되며, 사용자의 결정이 필요할 때만 채팅에서 묻습니다. 동의하면 그 작업은 끝까지 실행됩니다. 결제, 삭제, 계정 변경은 따로 확인합니다.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![릴리스](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![라이선스: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · **한국어** · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

<p align="center"><img src="mibo-en.svg" alt="Mibo" width="84%"></p>

## 기능

| 영역 | |
|---|---|
| **대화** | 한 캐릭터가 창에 나타나며, Windows에서는 데스크톱 위의 모습으로도 나타납니다. 기본 캐릭터나 직접 만든 캐릭터를 사용할 수 있습니다. OpenAI 호환 모델 서비스와 컴퓨터에서 실행 중인 Ollama, LM Studio를 지원합니다. 모델 메뉴에 컨텍스트 사용량이 표시되며 '지금 요약'과 '컨텍스트 비우기'를 제공합니다. |
| **기억** | 사용자에 관한 사실과 계획을 날짜와 함께 기록하며, '설정 › 기억'에서 확인하고 수정할 수 있습니다. 신분증 번호, 카드 번호, 비밀번호, 인증 코드는 저장하지 않습니다. 임시 채팅은 기록을 남기지 않습니다. |
| **추천** | 공개된 출처에서 한 번에 하나씩 추천하며, 클릭 수가 아니라 머문 시간으로 순위를 정합니다. 각 카드에는 추천 이유가 표시되고, 피드백과 실행 취소를 지원합니다. |
| **외출** | 공개 페이지를 로그인하지 않은 방문자로서 둘러보며 robots.txt를 따릅니다. 페이지는 제목과 표를 유지한 채 한 번에 읽습니다. 웹 검색에는 키가 필요하지 않습니다. |
| **내장 브라우저**(Windows) | 링크가 대화 옆에서 열리며 탭, 비공개 탭, 다운로드를 지원합니다. 캐릭터가 페이지를 살펴보고 클릭, 입력, 선택, 드래그, 파일 업로드를 수행합니다. |
| **다른 프로그램**(Windows) | UI Automation으로 다른 프로그램의 창을 읽고 조작합니다. Electron 앱도 지원하며, 사용자가 키보드와 마우스를 사용하지 않을 때만 조작합니다. |
| **파일과 명령** | 사용자 자신의 바탕 화면, 문서, 다운로드, 사진, 음악, 동영상 폴더와 허용한 폴더로 제한됩니다. 명령은 실행 전에 분석되고, 각 턴의 파일 변경은 되돌릴 수 있습니다. Windows에서는 삭제한 파일이 휴지통으로 이동합니다. |
| **스킬과 커넥터** | 스킬(`SKILL.md`가 있는 폴더)과 MCP 서버. 각각 엄선된 마켓을 제공합니다. 메시지를 `/name`(스킬 이름)으로 시작하면 해당 스킬을 바로 사용합니다. |
| **예약 작업** | 알림, 작업, 주기적인 조건 확인. 실행 중에는 읽기와 작업을 만들 때 허용한 작업만 수행합니다. |
| **언어** | 10개 인터페이스 언어. |

## 캐릭터

<p align="center"><img src="characters.webp" alt="Mibo · 백룡 · 뚱보 물고기 · 아가씨" width="100%"></p>

<p align="center">Mibo · 백룡 · 뚱보 물고기 · 아가씨</p>

## 설치

[최신 릴리스](https://github.com/wangkant/mibo/releases/latest)에서 내려받으십시오. 설치 파일에 코드 서명이 없으므로 처음 실행하기 전에 시스템이 경고를 표시합니다.

| 시스템 | 파일 | 처음 실행 |
|---|---|---|
| Windows 10 또는 11(x64) | `mibo-0.1.0-setup.exe` | 브라우저가 파일에 대해 경고하면 '유지'를 선택합니다. SmartScreen에 'Windows의 PC 보호'가 표시되면 '추가 정보'를 선택한 다음 '실행'을 선택합니다. 현재 계정에만 설치되며 관리자 권한이 필요하지 않습니다. |
| macOS(Apple 실리콘) | `mibo-0.1.0-macos-arm64.dmg` | 디스크 이미지를 열고 `mibo.app`을 '응용 프로그램' 폴더로 끌어 옵니다. 앱이 공증되지 않았으므로 처음에는 열리지 않습니다. 메시지를 닫은 다음 '시스템 설정 › 개인정보 보호 및 보안'에서 '그래도 열기'를 선택하고 확인합니다. |

새 릴리스도 같은 방법으로 덮어써서 설치합니다. 제거해도 데이터 폴더는 남습니다.

### 설치 프로그램 없이 사용

| | |
|---|---|
| **Windows 포터블 버전** | `mibo-0.1.0-windows-x64.zip`을 내려받아 원하는 위치에 압축을 풀고 `mibo.exe`를 실행합니다. 이 파일도 코드 서명되어 있지 않습니다. |
| **Scoop**(Windows) | `scoop bucket add mibo https://github.com/wangkant/scoop-mibo`를 실행한 다음 `scoop install mibo`를 실행합니다. |
| **Homebrew**(macOS, Apple 실리콘) | `brew install --cask wangkant/mibo/mibo`를 실행합니다. |
| **Python으로 설치**(3.10–3.14, 모든 시스템) | `pipx install "mibo[app,web]"` 또는 `uv tool install "mibo[app,web]"`를 실행한 다음 `mibo`를 실행합니다. |

### 소스에서 실행(Linux와 개발)

Python 3.10–3.14가 필요합니다.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app`은 macOS와 Linux에서 창 구성 요소를, `web`은 외출에 쓰는 Playwright를 추가합니다. 개발하려면 `".[dev]"`를 설치하고 `python -m pytest -q`를 실행하십시오. 자세한 내용은 [CONTRIBUTING](../../.github/CONTRIBUTING.md)(영어)을 참고하십시오.

## 처음 시작

1. 언어, 캐릭터, 모델을 고른 다음 관심 있는 주제와 간단한 자기소개를 입력합니다.
2. 모델은 서비스를 고르고 키를 붙여 넣거나, OpenRouter에 로그인해 무료 모델을 쓰거나, 실행 중인 Ollama 또는 LM Studio를 선택합니다.
3. 키는 시스템 자격 증명 저장소(Windows 자격 증명 관리자, macOS 키체인, Linux의 Secret Service)에 보관되며 파일에는 기록되지 않습니다. 자격 증명 저장소가 없는 시스템에서는 현재 계정만 읽을 수 있는 `credentials.json`에 보관되며, '설정 › 이 컴퓨터'에 그 사실이 표시됩니다.

데이터는 폴더 하나에 모아 저장합니다. 설치본은 `~/mibo`, 소스에서 실행하면 클론한 폴더 자체, 또는 `mibo --home DIR`로 지정한 폴더입니다. 설정은 그 폴더의 `settings.json`에 저장됩니다. Mibo는 기본적으로 로그인 시 시작하며, '설정 › 이 컴퓨터'에서 끌 수 있습니다.

## 개인 정보와 안전

| | |
|---|---|
| **모델 서비스** | 메시지, 관련 기억, 답변에 쓰는 페이지와 파일 내용, 검토가 판단하는 작업 단계를 받습니다. 키는 이 서비스로만 전송됩니다. |
| **웹사이트** | 외출은 로그인하지 않고 공개 페이지를 읽으며, 기본값은 하루 세 번입니다('설정 › 외출'). 답변에 필요한 페이지도 읽습니다. 로그인 정보는 내장 브라우저에만 남고 그 안에서만 사용됩니다. |
| **기타 서비스** | 답변에 검색이 필요할 때의 검색어, 하루 최대 한 번 GitHub로 보내는 버전 번호, 마켓을 열 때의 목록 조회, MCP 서버 도구에 전달하는 내용. |
| **항상 확인** | 결제나 구매, 삭제, 계정 보안이나 접근 권한 변경은 어떤 모드에서든 확인하며, 다른 종류의 단계에 대한 동의는 여기에 적용되지 않습니다. 은행, 결제, 의료, 메일 사이트에서는 모든 작업을 확인합니다. 채팅 입력란에 사용자가 직접 입력한 메시지만 동의로 봅니다. |
| **하지 않는 일** | 비밀번호, 결제 정보, 인증 코드를 읽거나 입력하는 일. 관리자 권한으로 실행하는 일. 보안 설정을 바꾸는 일. |
| **무인 실행** | 외출과 사용자가 만든 예약 작업뿐입니다. |

모든 전송 대상과 데이터별 보관 위치는 [SECURITY](../../.github/SECURITY.md)(영어)에 정리되어 있습니다.

## 요구 사항

| | Windows | macOS | Linux |
|---|---|---|---|
| **설치** | 설치 프로그램 | 디스크 이미지 | 소스에서 실행 |
| **시스템** | Windows 10 또는 11, x64 | Apple 실리콘 | Python 3.10–3.14 |
| **내장 브라우저, 다른 프로그램, 데스크톱 모습** | 지원 | 미지원 | 미지원 |
| **외출** | 기본 설치된 Edge | Edge, Chrome 또는 Chromium | Edge, Chrome 또는 Chromium |
| **모델** | OpenAI 호환 모델 서비스와 키, 또는 로컬 모델 서버 | 동일 | 동일 |

## 라이선스

[Apache License 2.0](../../LICENSE). 제3자 코드는 각자의 라이선스를 따릅니다([NOTICE](../../NOTICE)). 캐릭터 일러스트는 CC BY-NC-SA 4.0입니다([자세히](../../mibo/static/characters/LICENSE.md)). [면책 조항](../DISCLAIMER.ko.md)과 [변경 기록](../../CHANGELOG.md)(영어)도 참고하십시오.
