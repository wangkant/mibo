# Mibo

Un compagnon de bureau. Un personnage converse avec vous, se souvient de vous, vous recommande une chose à la fois et agit pour vous sur le web, dans d'autres programmes et dans vos fichiers. Toute action ayant un effet attend votre accord.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![Licence : Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · **Français** · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

Mibo s'exécute en local avec le modèle que vous fournissez et conserve ses données dans un seul dossier de votre ordinateur. Il cible Windows 10 et 11.

> **État :** préversion. Aucun programme d'installation n'est encore publié ; exécutez-le depuis les sources.

## Fonctionnalités

| | |
|---|---|
| **Conversation** | Un personnage, dans une fenêtre et sous forme de figurine sur le bureau. Personnages fournis ou personnels. Tout service de modèles compatible OpenAI, avec votre clé. |
| **Mémoire** | Faits et projets datés vous concernant, consultables et modifiables dans les Réglages. Les identifiants sensibles (pièces d'identité, numéros de carte, mots de passe, codes) ne sont jamais conservés. |
| **Recommandations** | Un élément à la fois, issu de sources publiques, classé selon le temps que vous y passez plutôt que selon les clics. Chaque carte indique sa raison et accepte un avis annulable. |
| **Web** | Lit les pages publiques en tant que visiteur et respecte robots.txt. Un navigateur intégré garde la conversation à côté de la page et agit sur la page à la demande. |
| **Programmes** (Windows) | Trouve et pilote d'autres programmes via UI Automation, avec un accord par programme et jamais pendant que vous tapez. |
| **Fichiers et commandes** | Limités aux dossiers que vous autorisez. Les commandes sont analysées avant exécution ; les suppressions vont dans la Corbeille ; les modifications de fichiers de chaque tour peuvent être annulées. |
| **Extensions** | Skills (dossiers `SKILL.md`) et connecteurs MCP, chacun avec un catalogue sélectionné. Les jetons des connecteurs sont conservés dans le magasin d'identifiants du système. |
| **Également** | Tâches planifiées, recherche dans les conversations passées, dix langues d'interface. |

## Sécurité

- Les mots de passe, données de paiement et codes de vérification ne sont jamais lus ni saisis.
- Les paiements, les suppressions et les modifications touchant la sécurité d'un compte exigent toujours une confirmation.
- Rien ne s'exécute sans surveillance, hormis les tâches planifiées que vous créez, qui se limitent à la lecture au-delà de ce que vous avez autorisé.
- Les connexions et les cookies restent sur votre ordinateur. Votre clé de modèle n'est envoyée qu'au service de modèles choisi.

## Démarrage rapide

Nécessite Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

Au premier lancement, choisissez une langue, un personnage et saisissez une clé de modèle. Exécuté depuis un clone, Mibo conserve ses données dans le clone (ignorées par git) ; une copie installée utilise `~/mibo`. `mibo --home DIR` désigne un autre dossier.

Sous macOS et Linux, installez avec `python -m pip install -e ".[app]"`. Le pilotage des programmes et le navigateur intégré sont réservés à Windows.

## Développement

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

La CI exécute les tests sous Linux (Python 3.10–3.14) et Windows, et vérifie qu'un wheel construit s'installe dans un environnement propre. Voir [CONTRIBUTING](../../.github/CONTRIBUTING.md).

## Licence

[Apache License 2.0](../../LICENSE). Le code tiers conserve sa propre licence ([NOTICE](../../NOTICE)) ; les portraits des personnages sont sous CC BY-NC-SA 4.0 ([détails](../../mibo/static/characters/LICENSE.md)). Voir l'[avertissement](../DISCLAIMER.fr.md).
