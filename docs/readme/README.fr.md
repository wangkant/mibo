# Mibo

**Un compagnon IA qui vit sur votre bureau : il vous tient compagnie et agit pour vous.**

Un personnage doté d'une apparence et d'un caractère propres converse avec vous, se souvient de vous et vous apporte, une à la fois, des choses qui méritent votre temps. Il ne se limite pas à la conversation : il navigue sur le web, utilise les programmes de votre ordinateur, travaille avec vos fichiers et vos commandes, emploie des compétences et des connecteurs MCP, et exécute des tâches planifiées. Il s'exécute sur votre ordinateur avec le service de modèles de votre choix. Les actions sont vérifiées automatiquement, et une carte ne vous sollicite que lorsqu'une décision vous revient ; les paiements, les suppressions et les modifications de compte la demandent toujours.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![Licence : Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · **Français** · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

<p align="center"><img src="mibo-en.svg" alt="Mibo" width="84%"></p>

## Fonctionnalités

| Domaine | |
|---|---|
| **Conversation** | Un personnage dans une fenêtre et, sous Windows, sous forme de figurine sur le bureau. Personnages fournis ou personnels. Tout service compatible OpenAI, ou Ollama et LM Studio sur votre ordinateur. Le menu du modèle indique l'occupation du contexte et propose Résumer maintenant et Effacer le contexte. |
| **Mémoire** | Faits et projets datés vous concernant, consultables et modifiables dans Paramètres › Mémoire. Les numéros d'identité ou de carte, mots de passe et codes ne sont jamais conservés. Les discussions temporaires ne laissent aucune trace. |
| **Recommandations** | Une trouvaille à la fois, issue de sources publiques, classée selon le temps que vous y passez plutôt que selon les clics. Chaque carte indique sa raison et accepte un avis annulable. |
| **Sorties** | Parcourt les pages publiques en tant que visiteur, sans connexion et dans le respect de robots.txt. Une page est lue en une fois, titres et tableaux compris. La recherche web ne demande aucune clé. |
| **Navigateur intégré** (Windows) | Les liens s'ouvrent à côté de la conversation, avec onglets, onglets privés et téléchargements. Le personnage examine la page et y clique, saisit, choisit, fait glisser et téléverse des fichiers. |
| **Autres programmes** (Windows) | Lit et pilote les fenêtres d'autres programmes via UI Automation, applications Electron comprises, uniquement lorsque vous n'utilisez ni le clavier ni la souris. |
| **Fichiers et commandes** | Limités aux dossiers autorisés. Les commandes sont analysées avant exécution ; les modifications de fichiers de chaque tour peuvent être annulées ; sous Windows, les suppressions vont dans la Corbeille. |
| **Compétences et connecteurs** | Compétences (dossiers `SKILL.md`) et serveurs MCP, chacun avec un catalogue sélectionné. Un message commençant par `/name` (le nom de la compétence) la lance. |
| **Tâches planifiées** | Rappels, tâches et vérifications périodiques. À l'exécution, elles ne font que lire, en plus de ce que vous avez autorisé à leur création. |
| **Langues** | Dix langues d'interface. |

## Personnages

<p align="center"><img src="characters.webp" alt="Mibo · Dragonne Blanche · Gros Poisson · Mademoiselle" width="100%"></p>

<p align="center">Mibo · Dragonne Blanche · Gros Poisson · Mademoiselle</p>

## Installation

Téléchargez-le depuis la [dernière version](https://github.com/wangkant/mibo/releases/latest). Les programmes d'installation ne sont pas signés, aussi le système affiche-t-il un avertissement avant le premier lancement.

| Système | Fichier | Premier lancement |
|---|---|---|
| Windows 10 ou 11 (x64) | `mibo-0.1.0-setup.exe` | Si le navigateur signale le fichier, choisissez **Conserver**. Lorsque SmartScreen affiche « Windows a protégé votre ordinateur », choisissez **Informations complémentaires**, puis **Exécuter quand même**. L'installation se fait pour votre compte seul, sans droits d'administrateur. |
| macOS (Apple silicon) | `mibo-0.1.0-macos-arm64.dmg` | Ouvrez l'image disque et faites glisser `mibo.app` dans Applications. La première ouverture est bloquée, car l'application n'est pas notarisée : fermez le message, puis choisissez **Ouvrir quand même** dans Réglages Système › Confidentialité et sécurité, et confirmez. |

Une nouvelle version s'installe de la même manière, par-dessus l'ancienne. La désinstallation conserve le dossier de données.

### Sans l'installateur

| | |
|---|---|
| **Windows, version portable** | Téléchargez `mibo-0.1.0-windows-x64.zip`, décompressez-le où vous voulez et lancez `mibo.exe`. Ce fichier n'est pas signé non plus. |
| **Avec Python** (3.10–3.14, tout système) | Exécutez `pipx install "mibo[app,web]"` ou `uv tool install "mibo[app,web]"`, puis `mibo`. |

### Depuis les sources (Linux et développement)

Nécessite Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` ajoute la bibliothèque de fenêtres sous macOS et Linux ; `web` ajoute Playwright pour les sorties. Pour le développement, installez `".[dev]"` et lancez `python -m pytest -q` ; voir [CONTRIBUTING](../../.github/CONTRIBUTING.md) (en anglais).

## Premier lancement

1. Choisissez une langue, un personnage et un modèle, puis les sujets qui vous intéressent et quelques mots sur vous.
2. Pour le modèle, choisissez un service et collez sa clé, connectez-vous avec OpenRouter pour ses modèles gratuits, ou choisissez Ollama ou LM Studio s'ils sont lancés.
3. La clé est conservée dans le magasin d'identifiants du système (Gestionnaire d'identification Windows, trousseau macOS, Secret Service sous Linux), jamais dans un fichier. Sur un système qui n'en a pas, elle est conservée dans `credentials.json`, lisible par votre seul compte, et Paramètres › Cet ordinateur le signale.

Les données restent dans un seul dossier : `~/mibo` pour une copie installée, le clone lui-même depuis les sources, ou le dossier indiqué par `mibo --home DIR`. Les paramètres y sont conservés dans `settings.json`. Mibo se lance par défaut à l'ouverture de session ; Paramètres › Cet ordinateur permet de le désactiver.

## Confidentialité et sécurité

| | |
|---|---|
| **Votre service de modèles** | Reçoit vos messages, la mémoire utile, les pages et fichiers utilisés pour une réponse, et les étapes soumises à la vérification. Votre clé n'est envoyée qu'à lui. |
| **Sites web** | Les sorties lisent des pages publiques sans connexion, trois par jour par défaut (Paramètres › Sorties) ; une réponse lit les pages dont elle a besoin. Vos connexions restent dans le navigateur intégré et ne servent que là. |
| **Autres services** | Une requête de recherche lorsqu'une réponse cherche ; le numéro de version envoyé à GitHub au plus une fois par jour ; des consultations de catalogue à l'ouverture d'une boutique ; ce que le personnage transmet aux outils d'un serveur MCP. |
| **Demande toujours** | Payer ou acheter, supprimer, modifier la sécurité ou les accès d'un compte, à chaque fois et dans tous les modes. Toute action sur les sites de banque, de paiement, de santé et de messagerie. |
| **Jamais** | Lire ou saisir des mots de passe, données de paiement ou codes de vérification ; exécuter quoi que ce soit en administrateur ; modifier les paramètres de sécurité. |
| **Sans surveillance** | Uniquement les sorties et les tâches planifiées que vous créez. |

[SECURITY](../../.github/SECURITY.md) (en anglais) liste toutes les destinations et l'emplacement de chaque type de données.

## Configuration requise

| | Windows | macOS | Linux |
|---|---|---|---|
| **Installation** | Programme d'installation | Image disque | Depuis les sources |
| **Système** | Windows 10 ou 11, x64 | Apple silicon | Python 3.10–3.14 |
| **Navigateur intégré, autres programmes, figurine** | Oui | Non | Non |
| **Sorties** | Edge, déjà installé | Edge, Chrome ou Chromium | Edge, Chrome ou Chromium |
| **Modèle** | Un service compatible OpenAI avec votre clé, ou un serveur de modèles local | Idem | Idem |

## Licence

[Apache License 2.0](../../LICENSE). Le code tiers conserve sa propre licence ([NOTICE](../../NOTICE)) ; les portraits des personnages sont sous CC BY-NC-SA 4.0 ([détails](../../mibo/static/characters/LICENSE.md)). Voir l'[avertissement](../DISCLAIMER.fr.md) et le [journal des modifications](../../CHANGELOG.md) (en anglais).
