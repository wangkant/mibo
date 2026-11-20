# Mibo

데스크톱 컴패니언 앱입니다. 한 캐릭터가 사용자와 대화하고, 사용자를 기억하고, 한 번에 하나씩 추천하며, 웹과 다른 프로그램, 파일에서 사용자를 대신해 작업합니다. 실제 영향이 있는 모든 작업은 사용자의 승인을 기다립니다.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![라이선스: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · **한국어** · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

Mibo는 사용자가 준비한 모델로 로컬에서 실행되며, 데이터를 컴퓨터의 폴더 하나에 저장합니다. 지원 대상은 Windows 10과 11입니다.

> **상태:** 사전 출시. 아직 설치 프로그램이 공개되지 않았으므로 소스에서 실행하십시오.

## 기능

| | |
|---|---|
| **대화** | 한 캐릭터가 창과 데스크톱 위의 모습으로 나타납니다. 기본 캐릭터나 직접 만든 캐릭터를 사용할 수 있습니다. OpenAI 호환 모델 서비스라면 사용자의 API 키로 사용할 수 있습니다. |
| **기억** | 사용자에 관한 사실과 계획을 날짜와 함께 기록하며, 설정에서 확인하고 수정할 수 있습니다. 신분증 번호, 카드 번호, 비밀번호, 인증 코드 같은 민감한 식별 정보는 저장하지 않습니다. |
| **추천** | 공개된 출처에서 한 번에 하나씩 추천하며, 클릭 수가 아니라 머문 시간으로 순위를 정합니다. 각 카드에는 추천 이유가 표시되고, 피드백과 실행 취소를 지원합니다. |
| **웹** | 공개 페이지를 방문자로서 읽으며 robots.txt를 따릅니다. 내장 브라우저에서는 페이지 옆에 대화가 표시되고, 요청에 따라 페이지를 조작합니다. |
| **프로그램**(Windows) | UI Automation으로 다른 프로그램을 찾아 조작합니다. 프로그램마다 허락을 받으며, 사용자가 입력하는 동안에는 조작하지 않습니다. |
| **파일과 명령** | 허용한 폴더로 제한됩니다. 명령은 실행 전에 분석되고, 삭제한 파일은 휴지통으로 이동하며, 각 턴의 파일 변경은 되돌릴 수 있습니다. |
| **확장** | 스킬(`SKILL.md`가 있는 폴더)과 MCP 커넥터. 각각 엄선된 마켓을 제공합니다. 커넥터 토큰은 시스템 자격 증명 저장소에 보관됩니다. |
| **기타** | 예약 작업, 지난 대화 검색, 10개 인터페이스 언어. |

## 보안

- 비밀번호, 결제 정보, 인증 코드를 읽거나 입력하지 않습니다.
- 결제, 삭제, 계정 보안 관련 변경은 매번 확인을 받습니다.
- 사용자가 만든 예약 작업을 제외하고는 무인으로 실행되지 않으며, 예약 작업도 허용한 범위 밖에서는 읽기만 합니다.
- 로그인 정보와 쿠키는 컴퓨터에만 저장됩니다. 모델 API 키는 사용자가 선택한 모델 서비스로만 전송됩니다.

## 빠른 시작

Python 3.10–3.14가 필요합니다.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

처음 실행하면 언어, 캐릭터, 모델 API 키를 설정합니다. 클론에서 실행하면 데이터는 클론 안에 저장되고(.gitignore 대상), 설치본은 `~/mibo`를 사용합니다. `mibo --home DIR`로 다른 폴더를 지정할 수 있습니다.

macOS와 Linux에서는 `python -m pip install -e ".[app]"`로 설치하십시오. 프로그램 조작과 내장 브라우저는 Windows에서만 지원됩니다.

## 개발

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

CI는 Linux(Python 3.10–3.14)와 Windows에서 테스트를 실행하고, 빌드한 wheel이 깨끗한 환경에 설치되는지 확인합니다. 자세한 내용은 [CONTRIBUTING](../../.github/CONTRIBUTING.md)을 참고하십시오.

## 라이선스

[Apache License 2.0](../../LICENSE). 제3자 코드는 각자의 라이선스를 따릅니다([NOTICE](../../NOTICE)). 캐릭터 일러스트는 CC BY-NC-SA 4.0입니다([자세히](../../mibo/static/characters/LICENSE.md)). [면책 조항](../DISCLAIMER.ko.md)도 참고하십시오.
