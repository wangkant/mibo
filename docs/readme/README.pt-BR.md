# Mibo

**Um agente de IA pessoal que vive no seu próprio computador: diga o que você precisa e ele resolve na web, nos seus arquivos e nos seus outros programas.**

O Mibo roda no seu computador com o serviço de modelos que você escolher. Não há máquina na nuvem no meio: seus logins e arquivos ficam no seu computador, e o que é enviado ao modelo chega apenas ao serviço que você escolheu. Uma tarefa que você passa é levada até o fim e relatada, e ele também pode agir de forma agendada. Só pergunta antes de uma ação que lhe custa algo ou não pode ser desfeita, ou que você não pediu; códigos de verificação, senhas e dados de pagamento são sempre digitados por você. Ele também é um personagem com nome, aparência e memória de você.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Versão](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![Licença: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · **Português (Brasil)** · [Русский](README.ru.md)

<p align="center"><img src="mibo-en.svg" alt="Mibo" width="84%"></p>

## Recursos

| Área | |
|---|---|
| **Conversa** | Um personagem em uma janela e, no Windows, como figura na área de trabalho. Personagens incluídos ou criados por você. Qualquer serviço compatível com OpenAI, ou Ollama e LM Studio no seu computador. O menu do modelo mostra quanto do contexto está ocupado e oferece Resumir agora e Limpar contexto. |
| **Memória** | Fatos e planos sobre você, com data, visíveis e editáveis em Configurações › Memória. Números de documentos ou de cartão, senhas e códigos nunca são armazenados. Conversas temporárias não deixam registro. |
| **Passeios** | Percorre páginas públicas como visitante, sem login e respeitando o robots.txt. Cada página é lida de uma vez, com títulos e tabelas. A pesquisa na web não exige chave. |
| **Navegador integrado** (Windows) | Os links abrem ao lado da conversa, com abas, abas privadas e downloads. O personagem examina a página e clica, digita, escolhe, arrasta e envia arquivos nela. |
| **Mensagens** | Ao ser perguntado sobre suas mensagens, o personagem lê os sites em que você entrou e informa o que há de novo. Esse passo só lê: as páginas vão para uma chamada ao modelo sem ferramentas. |
| **Outros programas** (Windows) | Lê e opera janelas de outros programas por meio do UI Automation, inclusive aplicativos Electron, apenas enquanto você não usa o teclado e o mouse. |
| **Arquivos e comandos** | Somente na sua Área de Trabalho, Documentos, Downloads, Imagens, Músicas e Vídeos, e nas pastas que você autorizar. Documentos do Word, Excel e PowerPoint são escritos como arquivos. Os comandos são lidos antes de rodar; as alterações de arquivos de cada turno podem ser desfeitas; no Windows, o que é excluído vai para a Lixeira. |
| **Habilidades e conectores** | Habilidades (pastas com `SKILL.md`) e servidores MCP, cada um com um catálogo selecionado. Uma mensagem que começa com `/name` (o nome da habilidade) a inicia. |
| **Configurações** | O personagem conhece as configurações do aplicativo: lista, abre as Configurações em um item e altera um. Uma alteração que não amplia nada é feita na hora; as chaves nunca são mostradas. |
| **Tarefas agendadas** | Lembretes, tarefas e verificações periódicas. Na execução, apenas leem, além do que você permitiu ao criá-las; um pedido recorrente de enviar ou publicar age somente no site, para o destinatário e no tipo de ação e com o texto que você indicou. |
| **Recomendações** | Uma descoberta de cada vez, de fontes públicas, ordenada pelo tempo que você dedica e não por cliques. Cada cartão informa o motivo e aceita avaliações que podem ser desfeitas. |
| **Idiomas** | Dez idiomas de interface. |

## Personagens

<p align="center"><img src="characters.webp" alt="Mibo · Dragoa Branca · Peixão · Senhorita" width="100%"></p>

<p align="center">Mibo · Dragoa Branca · Peixão · Senhorita</p>

## Instalação

Baixe da [versão mais recente](https://github.com/wangkant/mibo/releases/latest). Os instaladores não têm assinatura de código, por isso o sistema exibe um aviso antes da primeira execução.

| Sistema | Arquivo | Primeira execução |
|---|---|---|
| Windows 10 ou 11 (x64) | `mibo-0.2.0-setup.exe` | Se o navegador alertar sobre o arquivo, escolha **Manter**. Quando o SmartScreen mostrar "O Windows protegeu o computador", escolha **Mais informações** e depois **Executar assim mesmo**. A instalação é feita só para a sua conta, sem permissões de administrador. |
| macOS (Apple silicon) | `mibo-0.2.0-macos-arm64.dmg` | Abra a imagem de disco e arraste `mibo.app` para Aplicativos. A primeira abertura é bloqueada porque o aplicativo não é notarizado: feche a mensagem e, em Ajustes do Sistema › Privacidade e Segurança, escolha **Abrir Mesmo Assim** e confirme. |

Uma nova versão é instalada da mesma forma, por cima da anterior. A desinstalação mantém a pasta de dados.

### Sem o instalador

| | |
|---|---|
| **Windows, versão portátil** | Baixe `mibo-0.2.0-windows-x64.zip`, descompacte em qualquer pasta e execute `mibo.exe`. O arquivo também não é assinado. |
| **Scoop** (Windows) | Execute `scoop bucket add mibo https://github.com/wangkant/scoop-mibo` e, em seguida, `scoop install mibo`. |
| **Homebrew** (macOS, Apple silicon) | Execute `brew install --cask wangkant/mibo/mibo`. |
| **Com Python** (3.10–3.14, qualquer sistema) | Execute `pipx install "mibo[app,web]"` ou `uv tool install "mibo[app,web]"` e, em seguida, `mibo`. |

### A partir do código-fonte (Linux e desenvolvimento)

Requer Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` adiciona o componente de janelas no macOS e no Linux; `web` adiciona o Playwright para os passeios. Para desenvolver, instale `".[dev]"` e execute `python -m pytest -q`; consulte o [CONTRIBUTING](../../.github/CONTRIBUTING.md) (em inglês).

## Primeira execução

1. Escolha um idioma, um personagem e um modelo; depois, os temas de que você gosta e algumas palavras sobre você.
2. Para o modelo, escolha um serviço e cole a chave dele, entre com o OpenRouter para usar os modelos gratuitos dele, ou escolha o Ollama ou o LM Studio se estiverem em execução.
3. A chave fica no armazenamento de credenciais do sistema (Gerenciador de Credenciais do Windows, Chaves do macOS, Secret Service no Linux), nunca em um arquivo. Em um sistema sem esse armazenamento, ela fica em `credentials.json`, legível apenas pela sua conta, e Configurações › Este computador informa isso.

Os dados ficam em uma única pasta: `~/mibo` em uma cópia instalada, o próprio clone quando executado a partir do código-fonte, ou a pasta indicada com `mibo --home DIR`. As configurações ficam ali, em `settings.json`. O Mibo inicia ao entrar no sistema por padrão; Configurações › Este computador desativa isso.

## Privacidade e segurança

| | |
|---|---|
| **Seu serviço de modelos** | Recebe suas mensagens, a memória relevante, as páginas e arquivos usados em uma resposta e os passos que a revisão avalia. Sua chave é enviada somente a ele. Um aviso informa isso uma única vez, ao salvar um serviço pela primeira vez, e só volta a aparecer se o serviço mudar. |
| **Sites** | Os passeios leem páginas públicas sem login, três por dia por padrão (Configurações › Passeios); uma resposta lê as páginas de que precisa. Seus logins ficam no navegador integrado e só são usados ali. |
| **Outros serviços** | Uma consulta de pesquisa quando uma resposta pesquisa; o número da versão enviado ao GitHub no máximo uma vez por dia; consultas ao catálogo quando você abre uma loja; o que o personagem passa às ferramentas de um servidor MCP. |
| **Sempre pergunta** | Um passo custoso é perguntado toda vez e separadamente, em qualquer modo: pagar ou gastar, uma exclusão que nada restaura, a própria conta, entregar acesso ou dados privados, um envio vinculante, uma alteração neste computador que o desfazer não consegue reverter. Nenhum sim anterior nem tarefa agendada o cobre. Uma exclusão que vai para a Lixeira não é perguntada. Só a sua própria mensagem digitada na conversa conta como sim. |
| **Conteúdo lido** | O que uma ferramenta lê da web ou deste computador é material, nunca uma instrução. Depois de lê-lo, enviar algo a um lugar que você não indicou é perguntado, assim como um comando copiado palavra por palavra dele. Um programa baixado nunca é executado. |
| **Nunca** | Digitar por você senhas, códigos ou dados de pagamento, que você sempre digita; executar algo como administrador; ler as chaves do modelo, as configurações do aplicativo ou o perfil do navegador integrado, que nenhuma ferramenta pode abrir. |
| **Sem supervisão** | Apenas os passeios e as tarefas agendadas que você criar. |

O [SECURITY](../../.github/SECURITY.md) (em inglês) lista todos os destinos e onde cada tipo de dado fica guardado.

## Requisitos

| | Windows | macOS | Linux |
|---|---|---|---|
| **Instalação** | Instalador | Imagem de disco | Código-fonte |
| **Sistema** | Windows 10 ou 11, x64 | Apple silicon | Python 3.10–3.14 |
| **Navegador integrado, outros programas, figura na área de trabalho** | Sim | Não | Não |
| **Passeios** | Edge, já instalado | Edge, Chrome ou Chromium | Edge, Chrome ou Chromium |
| **Modelo** | Um serviço compatível com OpenAI com a sua chave, ou um servidor de modelos local | Igual | Igual |

## Licença

[Apache License 2.0](../../LICENSE). O código de terceiros mantém a própria licença ([NOTICE](../../NOTICE)); os retratos dos personagens estão sob CC BY-NC-SA 4.0 ([detalhes](../../mibo/static/characters/LICENSE.md)). Consulte o [aviso legal](../DISCLAIMER.pt-BR.md) e o [registro de alterações](../../CHANGELOG.md) (em inglês).
