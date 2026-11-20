# Mibo

Ein Desktop-Begleiter. Ein Charakter unterhält sich mit Ihnen, merkt sich, was Sie betrifft, empfiehlt jeweils eine Sache und handelt für Sie im Web, in anderen Programmen und in Ihren Dateien. Jede Aktion mit Wirkung wartet auf Ihre Zustimmung.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![Lizenz: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · **Deutsch** · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

Mibo läuft lokal mit einem Modell Ihrer Wahl und speichert seine Daten in einem einzigen Ordner auf Ihrem Computer. Zielplattform sind Windows 10 und 11.

> **Status:** Vorabversion. Ein Installationsprogramm ist noch nicht veröffentlicht; starten Sie Mibo aus dem Quellcode.

## Funktionen

| | |
|---|---|
| **Unterhaltung** | Ein Charakter, im Fenster und als Figur auf dem Desktop. Mitgelieferte oder eigene Charaktere. Jeder OpenAI-kompatible Modelldienst, mit Ihrem Schlüssel. |
| **Gedächtnis** | Datierte Fakten und Pläne über Sie, in den Einstellungen einsehbar und bearbeitbar. Sensible Kennungen (Ausweis- und Kartennummern, Passwörter, Codes) werden nie gespeichert. |
| **Empfehlungen** | Jeweils ein Eintrag aus öffentlichen Quellen, gereiht nach der Verweildauer statt nach Klicks. Jede Karte nennt ihren Grund und nimmt Rückmeldungen an, die sich rückgängig machen lassen. |
| **Web** | Liest öffentliche Seiten als Besucher und beachtet robots.txt. Ein integrierter Browser zeigt die Unterhaltung neben der Seite und bedient die Seite auf Anfrage. |
| **Programme** (Windows) | Findet und bedient andere Programme über UI Automation, mit Zustimmung je Programm und nie, während Sie tippen. |
| **Dateien und Befehle** | Auf freigegebene Ordner beschränkt. Befehle werden vor der Ausführung analysiert; Gelöschtes landet im Papierkorb; die Dateiänderungen jedes Durchgangs lassen sich rückgängig machen. |
| **Erweiterungen** | Skills (Ordner mit `SKILL.md`) und MCP-Konnektoren, jeweils mit einem kuratierten Katalog. Konnektor-Token liegen im Anmeldeinformationsspeicher des Systems. |
| **Außerdem** | Geplante Aufgaben, Suche in früheren Unterhaltungen, zehn Oberflächensprachen. |

## Sicherheit

- Passwörter, Zahlungsdaten und Bestätigungscodes werden nie gelesen oder eingegeben.
- Zahlungen, Löschungen und Änderungen an der Kontosicherheit erfordern immer eine Bestätigung.
- Unbeaufsichtigt läuft nur, was Sie als geplante Aufgabe anlegen; außerhalb des Erlaubten liest eine solche Aufgabe nur.
- Anmeldungen und Cookies bleiben auf Ihrem Computer. Ihr Modellschlüssel geht nur an den gewählten Modelldienst.

## Schnellstart

Erfordert Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

Beim ersten Start werden eine Sprache, ein Charakter und ein Modellschlüssel abgefragt. Aus einem Klon gestartet, liegen die Daten im Klon (von git ignoriert); eine installierte Kopie verwendet `~/mibo`. `mibo --home DIR` wählt einen anderen Ordner.

Unter macOS und Linux installieren Sie mit `python -m pip install -e ".[app]"`. Programmsteuerung und integrierter Browser sind nur unter Windows verfügbar.

## Entwicklung

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

Die CI führt die Tests unter Linux (Python 3.10–3.14) und Windows aus und prüft, ob sich das gebaute Wheel in einer sauberen Umgebung installieren lässt. Siehe [CONTRIBUTING](../../.github/CONTRIBUTING.md).

## Lizenz

[Apache License 2.0](../../LICENSE). Code Dritter behält seine eigene Lizenz ([NOTICE](../../NOTICE)); die Charakterporträts stehen unter CC BY-NC-SA 4.0 ([Details](../../mibo/static/characters/LICENSE.md)). Siehe auch den [Haftungsausschluss](../DISCLAIMER.de.md).
