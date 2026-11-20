# Mibo

Um companheiro de área de trabalho. Um personagem conversa com você, lembra de você, recomenda uma coisa de cada vez e age por você na web, em outros programas e nos seus arquivos. Toda ação com efeito aguarda a sua aprovação.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![Licença: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · **Português (Brasil)** · [Русский](README.ru.md)

O Mibo roda localmente com o modelo que você escolher e guarda seus dados em uma única pasta no seu computador. É voltado para o Windows 10 e 11.

> **Status:** pré-lançamento. Ainda não há instalador publicado; execute-o a partir do código-fonte.

## Recursos

| | |
|---|---|
| **Conversa** | Um personagem, em uma janela e como figura na área de trabalho. Personagens incluídos ou criados por você. Qualquer serviço de modelos compatível com OpenAI, com a sua chave. |
| **Memória** | Fatos e planos sobre você, com data, visíveis e editáveis em Configurações. Identificadores sensíveis (documentos, números de cartão, senhas, códigos) nunca são armazenados. |
| **Recomendações** | Um item de cada vez, de fontes públicas, ordenado pelo tempo que você dedica e não por cliques. Cada cartão informa o motivo e aceita avaliações que podem ser desfeitas. |
| **Web** | Lê páginas públicas como visitante e respeita o robots.txt. Um navegador integrado mantém a conversa ao lado da página e a opera quando solicitado. |
| **Programas** (Windows) | Encontra e opera outros programas por meio do UI Automation, com consentimento por programa e nunca enquanto você digita. |
| **Arquivos e comandos** | Limitados às pastas que você autorizar. Os comandos são analisados antes de rodar; o que é excluído vai para a Lixeira; as alterações de arquivos de cada turno podem ser desfeitas. |
| **Extensões** | Skills (pastas com `SKILL.md`) e conectores MCP, cada um com um catálogo selecionado. Os tokens dos conectores ficam no armazenamento de credenciais do sistema. |
| **Também** | Tarefas agendadas, busca em conversas anteriores, dez idiomas de interface. |

## Segurança

- Senhas, dados de pagamento e códigos de verificação nunca são lidos nem digitados.
- Pagamentos, exclusões e alterações de segurança da conta sempre exigem confirmação.
- Nada roda sem supervisão, exceto as tarefas agendadas que você criar, que fora do que você autorizou apenas leem.
- Logins e cookies ficam no seu computador. Sua chave do modelo é enviada apenas ao serviço que você escolheu.

## Início rápido

Requer Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

Na primeira execução, são solicitados um idioma, um personagem e uma chave do modelo. Executado a partir de um clone, o Mibo guarda os dados no próprio clone (ignorados pelo git); uma cópia instalada usa `~/mibo`. `mibo --home DIR` escolhe outra pasta.

No macOS e no Linux, instale com `python -m pip install -e ".[app]"`. O controle de programas e o navegador integrado são exclusivos do Windows.

## Desenvolvimento

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

A CI executa os testes no Linux (Python 3.10–3.14) e no Windows e verifica se o wheel gerado se instala em um ambiente limpo. Consulte o [CONTRIBUTING](../../.github/CONTRIBUTING.md).

## Licença

[Apache License 2.0](../../LICENSE). O código de terceiros mantém a própria licença ([NOTICE](../../NOTICE)); os retratos dos personagens estão sob CC BY-NC-SA 4.0 ([detalhes](../../mibo/static/characters/LICENSE.md)). Consulte o [aviso legal](../DISCLAIMER.pt-BR.md).
