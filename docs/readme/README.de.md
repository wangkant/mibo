# Mibo

**Ein persönlicher KI-Agent, der auf Ihrem eigenen Computer lebt: Sagen Sie ihm, was Sie brauchen, und er erledigt es im Web, in Ihren Dateien und in Ihren anderen Programmen.**

Mibo läuft auf Ihrem Computer mit einem Modelldienst Ihrer Wahl. Es gibt keinen Cloud-Rechner dazwischen: Ihre Anmeldungen und Dateien bleiben auf Ihrem Computer, und was an das Modell gesendet wird, erreicht nur den von Ihnen gewählten Dienst. Eine Aufgabe, die Sie ihm geben, führt es bis zum Ende aus und meldet das Ergebnis; es kann auch nach Zeitplan handeln. Es fragt nur vor einer Handlung, die Sie etwas kostet oder sich nicht rückgängig machen lässt, oder die Sie nicht verlangt haben; Bestätigungscodes, Passwörter und Zahlungsdaten geben immer Sie selbst ein. Es ist außerdem eine Figur mit Namen, Aussehen und Erinnerung an Sie.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![Lizenz: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · **Deutsch** · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

<p align="center"><img src="mibo-en.svg" alt="Mibo" width="84%"></p>

## Funktionen

| Bereich | |
|---|---|
| **Unterhaltung** | Eine Figur im Fenster und unter Windows auch auf dem Desktop. Mitgelieferte oder eigene Figuren. Jeder OpenAI-kompatible Dienst oder Ollama und LM Studio auf Ihrem Computer. Das Modellmenü zeigt, wie voll der Kontext ist, und bietet „Jetzt zusammenfassen“ und „Kontext leeren“. |
| **Gedächtnis** | Datierte Fakten und Pläne über Sie, einsehbar und bearbeitbar unter Einstellungen › Gedächtnis. Ausweis- und Kartennummern, Passwörter und Codes werden nie gespeichert. Temporäre Chats hinterlassen keine Aufzeichnung. |
| **Ausflüge** | Besucht öffentliche Seiten als Gast, ohne Anmeldung und unter Beachtung von robots.txt. Eine Seite wird in einem Zug gelesen, mit Überschriften und Tabellen. Die Websuche braucht keinen Schlüssel. |
| **Integrierter Browser** (Windows) | Links öffnen sich neben der Unterhaltung, mit Tabs, privaten Tabs und Downloads. Die Figur sieht sich die Seite an und klickt, tippt, wählt aus, zieht und lädt Dateien hoch. |
| **Nachrichten** | Auf die Frage nach Ihren Nachrichten liest die Figur die Seiten, bei denen Sie angemeldet sind, und berichtet, was neu ist. Dieser Schritt liest nur: Die Seiten gehen an einen Modellaufruf ohne Werkzeuge. |
| **Andere Programme** (Windows) | Liest und bedient Fenster anderer Programme über UI Automation, auch Electron-Apps, und nur, solange Sie Tastatur und Maus ruhen lassen. |
| **Dateien und Befehle** | Ihr Benutzerordner und Ihre anderen Laufwerke, ohne vorherige Freigabe; Orte mit Passwörtern, Schlüsseln, Browserprofilen oder Daten anderer Programme werden nie gelesen, und ein Ordner, den Sie in den Einstellungen auf Nur ansehen stellen oder zurücknehmen, bleibt so. Eine Änderung an einem Ort, von dem aus etwas von selbst startet (Autostart, der Ordner eines Programms oder von Windows, ein Ordner im PATH, Git-Hooks, die Startdatei einer Shell), wird jedes Mal erfragt, und ein Programm oder eine Verknüpfung aus dem Web wird nie gestartet. Word-, Excel- und PowerPoint-Dokumente werden als Dateien geschrieben. Befehle werden vor der Ausführung gelesen; die Dateiänderungen jedes Durchgangs lassen sich rückgängig machen; unter Windows landet Gelöschtes im Papierkorb. |
| **Skills und Connectoren** | Skills (Ordner mit `SKILL.md`) und MCP-Server, jeweils mit einem kuratierten Katalog. Eine Nachricht, die mit `/name` (dem Namen des Skills) beginnt, startet ihn. |
| **Einstellungen** | Die Figur kennt die Einstellungen der App: Sie listet sie auf, öffnet die Einstellungen an einem Eintrag und ändert einen. Eine Änderung, die nichts erweitert, wird sofort vorgenommen; Schlüssel werden nie angezeigt. |
| **Geplante Aufgaben** | Erinnerungen, Aufgaben und regelmäßige Prüfungen. Bei der Ausführung wird nur gelesen, dazu kommt, was Sie beim Anlegen erlaubt haben; ein wiederkehrender Auftrag zum Senden oder Veröffentlichen handelt nur auf der genannten Seite, für den genannten Empfänger und in der genannten Art und mit dem genannten Text. |
| **Empfehlungen** | Jeweils ein Fund aus öffentlichen Quellen, gereiht nach der Verweildauer statt nach Klicks. Jede Karte nennt ihren Grund und nimmt Rückmeldungen an, die sich rückgängig machen lassen. |
| **Sprachen** | Zehn Oberflächensprachen. |

## Charaktere

<p align="center"><img src="characters.webp" alt="Mibo · Weiße Drachin · Dicker Fisch · Mylady" width="100%"></p>

<p align="center">Mibo · Weiße Drachin · Dicker Fisch · Mylady</p>

## Installation

Laden Sie Mibo aus der [neuesten Version](https://github.com/wangkant/mibo/releases/latest) herunter. Die Installationsdateien sind nicht codesigniert; deshalb warnt das System vor dem ersten Start.

| System | Datei | Erster Start |
|---|---|---|
| Windows 10 oder 11 (x64) | `mibo-0.2.0-setup.exe` | Warnt der Browser vor der Datei, wählen Sie **Beibehalten**. Zeigt SmartScreen „Der Computer wurde durch Windows geschützt“, wählen Sie **Weitere Informationen** und dann **Trotzdem ausführen**. Die Installation erfolgt nur für Ihr Konto und ohne Administratorrechte. |
| macOS (Apple Silicon) | `mibo-0.2.0-macos-arm64.dmg` | Öffnen Sie das Image und ziehen Sie `mibo.app` in den Ordner „Programme“. Das erste Öffnen wird blockiert, weil die App nicht notarisiert ist: Schließen Sie die Meldung und wählen Sie dann unter Systemeinstellungen › Datenschutz & Sicherheit **Dennoch öffnen** und bestätigen Sie. |

Eine neue Version wird auf dieselbe Weise über die alte installiert. Die installierte Windows-App kann sich auch selbst aktualisieren: Unter Einstellungen › Info bietet sie die neue Version an, prüft den Download anhand der Prüfsummen der Version, installiert sie mit denselben Optionen über die alte und startet neu. Beim Deinstallieren bleibt der Datenordner erhalten.

### Ohne Installationsprogramm

| | |
|---|---|
| **Windows, portable Version** | Laden Sie `mibo-0.2.0-windows-x64.zip` herunter, entpacken Sie die Datei an einem beliebigen Ort und starten Sie `mibo.exe`. Auch diese Datei ist nicht signiert. |
| **Scoop** (Windows) | Führen Sie `scoop bucket add mibo https://github.com/wangkant/scoop-mibo` und anschließend `scoop install mibo` aus. |
| **Homebrew** (macOS, Apple Silicon) | Führen Sie `brew install --cask wangkant/mibo/mibo` aus. |
| **Mit Python** (3.10–3.14, jedes System) | Führen Sie `pipx install "mibo[app,web]"` oder `uv tool install "mibo[app,web]"` aus und starten Sie anschließend `mibo`. |

### Aus dem Quellcode (Linux und Entwicklung)

Erfordert Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` ergänzt unter macOS und Linux das Fenster-Toolkit, `web` ergänzt Playwright für Ausflüge. Für die Entwicklung installieren Sie `".[dev]"` und führen `python -m pytest -q` aus; siehe [CONTRIBUTING](../../.github/CONTRIBUTING.md) (Englisch).

## Erster Start

1. Wählen Sie eine Sprache, eine Figur und ein Modell, danach Themen, die Sie interessieren, und ein paar Worte über sich.
2. Für das Modell wählen Sie einen Dienst und fügen seinen Schlüssel ein, melden sich bei OpenRouter für dessen kostenlose Modelle an oder wählen Ollama oder LM Studio, sofern sie laufen.
3. Der Schlüssel liegt im Anmeldeinformationsspeicher des Systems (Windows-Anmeldeinformationsverwaltung, macOS-Schlüsselbund, Secret Service unter Linux), nie in einer Datei. Fehlt ein solcher Speicher, liegt er in `credentials.json`, nur für Ihr Konto lesbar, und Einstellungen › Dieser Computer weist darauf hin.

Die Daten liegen in einem einzigen Ordner: `~/mibo` bei einer installierten Kopie, der Klon selbst beim Start aus dem Quellcode oder der mit `mibo --home DIR` angegebene Ordner. Die Einstellungen liegen dort in `settings.json`. Mibo startet standardmäßig bei der Anmeldung; unter Einstellungen › Dieser Computer lässt sich das abschalten.

## Datenschutz und Sicherheit

| | |
|---|---|
| **Ihr Modelldienst** | Erhält Ihre Nachrichten, relevante Erinnerungen, die für eine Antwort genutzten Seiten und Dateien sowie die Schritte, die die Prüfung beurteilt. Ihr Schlüssel geht nur an diesen Dienst. Ein Hinweis darauf erscheint einmal, wenn ein Dienst zum ersten Mal gespeichert wird, und erst wieder, wenn der Dienst wechselt. |
| **Websites** | Ausflüge lesen öffentliche Seiten ohne Anmeldung, standardmäßig dreimal am Tag (Einstellungen › Ausflüge); eine Antwort liest die Seiten, die sie braucht. Ihre Anmeldungen bleiben im integrierten Browser und werden nur dort verwendet. |
| **Andere Dienste** | Eine Suchanfrage, wenn eine Antwort sucht; die Versionsnummer an GitHub höchstens einmal am Tag; Katalogabfragen, wenn Sie einen Katalog öffnen; was die Figur an die Werkzeuge eines MCP-Servers übergibt. |
| **Fragt immer** | Ein kostspieliger Schritt wird in jedem Modus jedes Mal und einzeln erfragt: Bezahlen oder Geld ausgeben, ein Löschen, das nichts wiederherstellt, das Konto selbst, die Weitergabe von Zugang oder privaten Angaben, eine bindende Übermittlung, eine Änderung an diesem Computer, die sich nicht rückgängig machen lässt. Kein früheres Ja und keine geplante Aufgabe deckt ihn ab. Ein Löschen in den Papierkorb wird nicht erfragt. Ein solcher Schritt wird auf einer Karte erfragt, deren Schaltfläche die Aktion benennt; nur Ihre eigene, im Chat getippte Nachricht oder Ihr Klick auf dieser Karte gilt als Ja. |
| **Gelesene Inhalte** | Was ein Werkzeug aus dem Web oder von diesem Computer liest, ist Material und nie eine Anweisung. Danach wird das Senden an einen nicht genannten Ort erfragt, ebenso ein daraus wörtlich übernommener Befehl. Ein heruntergeladenes Programm wird nie ausgeführt. |
| **Nie** | Passwörter, Codes oder Zahlungsdaten für Sie eingeben (das tun Sie stets selbst); etwas als Administrator ausführen; Modellschlüssel, die Einstellungen der App oder das Profil des integrierten Browsers lesen, was kein Werkzeug kann. |
| **Befehle** | Unter Windows läuft jeder Befehl zusätzlich unter Grenzen, die Windows selbst durchsetzt: keine Administratorrechte, kein Zugriff auf die eigenen Dateien der App, kein Verlassen der Gruppe, in der seine Programme laufen, keine Zwischenablage; ein Befehl, der als nur lesend eingestuft ist, kann keine Datei und keine Einstellung ändern. Browserprofile, Passwortmanager, Wallets und Chat-Apps sind für jeden Befehl gesperrt, SSH- und Cloud-Schlüssel nur für Befehle mit Netzwerkzugriff offen, und kein Befehl kann in Autostart-Ordner, Shell-Profile oder Run-Schlüssel schreiben; Programme, die Sie selbst öffnen, sind nicht betroffen, und eine Deinstallation stellt jede Berechtigung wieder her. Eine optionale Einrichtung mit Administratorzustimmung hält außerdem Befehle ohne Netzwerkzugriff vom Netzwerk fern und hindert jeden Befehl daran, eine geplante Aufgabe anzulegen. Ihre übrigen Dateien schützen die Prüfung vor dem Start und Ihre Zustimmung. |
| **Unbeaufsichtigt** | Nur Ausflüge und die geplanten Aufgaben, die Sie anlegen. |

[SECURITY](../../.github/SECURITY.md) (Englisch) führt alle Ziele auf und wo welche Daten liegen.

## Systemvoraussetzungen

| | Windows | macOS | Linux |
|---|---|---|---|
| **Installation** | Installationsprogramm | Disk-Image | Aus dem Quellcode |
| **System** | Windows 10 oder 11, x64 | Apple Silicon | Python 3.10–3.14 |
| **Integrierter Browser, andere Programme, Desktop-Figur** | Ja | Nein | Nein |
| **Ausflüge** | Edge, bereits installiert | Edge, Chrome oder Chromium | Edge, Chrome oder Chromium |
| **Modell** | Ein OpenAI-kompatibler Dienst mit Ihrem Schlüssel oder ein lokaler Modellserver | Ebenso | Ebenso |

## Lizenz

[Apache License 2.0](../../LICENSE). Code Dritter behält seine eigene Lizenz ([NOTICE](../../NOTICE)); die Porträts der Figuren stehen unter CC BY-NC-SA 4.0 ([Details](../../mibo/static/characters/LICENSE.md)). Siehe auch den [Haftungsausschluss](../DISCLAIMER.de.md) und das [Änderungsprotokoll](../../CHANGELOG.md) (Englisch).
