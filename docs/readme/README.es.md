# Mibo

Un compañero de escritorio. Un personaje conversa con usted, le recuerda, le recomienda una cosa cada vez y actúa en su nombre en la web, en otros programas y en sus archivos. Toda acción con efectos espera su aprobación.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-0969da?style=flat-square)](https://www.python.org/downloads/)
[![Licencia: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · **Español** · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

Mibo se ejecuta en local con el modelo que usted aporte y guarda sus datos en una sola carpeta de su equipo. Está pensado para Windows 10 y 11.

> **Estado:** versión preliminar. Aún no hay instalador publicado; ejecútelo desde el código fuente.

## Funciones

| | |
|---|---|
| **Conversación** | Un personaje, en una ventana y como figura en el escritorio. Personajes incluidos o propios. Cualquier servicio de modelos compatible con OpenAI, con su propia clave. |
| **Memoria** | Hechos y planes sobre usted, con fecha, visibles y editables en Ajustes. Nunca se guardan identificadores sensibles (documentos de identidad, números de tarjeta, contraseñas, códigos). |
| **Recomendaciones** | Un elemento cada vez, de fuentes públicas, ordenado por el tiempo que usted dedica y no por los clics. Cada tarjeta indica su motivo y admite valoraciones que se pueden deshacer. |
| **Web** | Lee páginas públicas como visitante y respeta robots.txt. Un navegador integrado mantiene la conversación junto a la página y la maneja cuando se le pide. |
| **Programas** (Windows) | Encuentra y maneja otros programas mediante UI Automation, con consentimiento por programa y nunca mientras usted escribe. |
| **Archivos y comandos** | Limitado a las carpetas que usted autorice. Los comandos se analizan antes de ejecutarse; lo eliminado va a la Papelera de reciclaje; los cambios de archivos de cada turno se pueden deshacer. |
| **Extensiones** | Skills (carpetas con `SKILL.md`) y conectores MCP, cada uno con un catálogo seleccionado. Los tokens de los conectores se guardan en el almacén de credenciales del sistema. |
| **Además** | Tareas programadas, búsqueda en conversaciones anteriores, diez idiomas de interfaz. |

## Seguridad

- Nunca lee ni escribe contraseñas, datos de pago ni códigos de verificación.
- Los pagos, las eliminaciones y los cambios de seguridad de cuentas siempre requieren confirmación.
- Nada se ejecuta sin supervisión salvo las tareas programadas que usted cree, que fuera de lo autorizado solo leen.
- Las sesiones y las cookies permanecen en su equipo. Su clave del modelo solo se envía al servicio que usted eligió.

## Inicio rápido

Requiere Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e .
mibo
```

En el primer inicio se piden un idioma, un personaje y una clave del modelo. Si se ejecuta desde un clon, los datos se guardan en el propio clon (ignorados por git); una copia instalada usa `~/mibo`. `mibo --home DIR` elige otra carpeta.

En macOS y Linux, instálelo con `python -m pip install -e ".[app]"`. El control de programas y el navegador integrado solo están disponibles en Windows.

## Desarrollo

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check . --select F401,F811,F821,F841
```

La CI ejecuta las pruebas en Linux (Python 3.10–3.14) y Windows, y comprueba que el wheel generado se instala en un entorno limpio. Consulte [CONTRIBUTING](../../.github/CONTRIBUTING.md).

## Licencia

[Apache License 2.0](../../LICENSE). El código de terceros conserva su propia licencia ([NOTICE](../../NOTICE)); los retratos de los personajes están bajo CC BY-NC-SA 4.0 ([detalles](../../mibo/static/characters/LICENSE.md)). Consulte el [aviso legal](../DISCLAIMER.es.md).
