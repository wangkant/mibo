# Mibo

**Un agente de IA personal que vive en su propio equipo: dígale lo que necesita y lo resuelve en la web, en sus archivos y en sus otros programas.**

Mibo se ejecuta en su equipo con el servicio de modelos que usted elija. No hay ningún equipo en la nube de por medio: sus sesiones iniciadas y sus archivos permanecen en su equipo, y lo que se envía al modelo llega solo al servicio que usted eligió. Una tarea que usted le encarga se lleva hasta el final y se le informa del resultado, y también puede actuar según un horario. Solo pregunta antes de una acción que le cuesta algo o no se puede deshacer, o que usted no pidió; los códigos de verificación, las contraseñas y los datos de pago los introduce siempre usted. Además, es un personaje con nombre, aspecto y memoria de usted.

[![CI](https://img.shields.io/github/actions/workflow/status/wangkant/mibo/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/wangkant/mibo/actions/workflows/ci.yml)
[![Versión](https://img.shields.io/github/v/release/wangkant/mibo?style=flat-square&label=Release)](https://github.com/wangkant/mibo/releases/latest)
[![Licencia: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-0969da?style=flat-square)](../../LICENSE)

[English](../../README.md) · [简体中文](../../README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · **Español** · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (Brasil)](README.pt-BR.md) · [Русский](README.ru.md)

<p align="center"><img src="mibo-en.svg" alt="Mibo" width="84%"></p>

## Funciones

| Área | |
|---|---|
| **Conversación** | Un personaje en una ventana y, en Windows, como figura en el escritorio. Personajes incluidos o propios. Cualquier servicio compatible con OpenAI, u Ollama y LM Studio en su equipo. El menú del modelo muestra cuánto contexto está ocupado y ofrece Resumir ahora y Borrar contexto. |
| **Memoria** | Hechos y planes sobre usted, con fecha, visibles y editables en Configuración › Memoria. Nunca se guardan números de identidad o de tarjeta, contraseñas ni códigos. Los chats temporales no dejan registro. |
| **Salidas** | Recorre páginas públicas como visitante, sin iniciar sesión y respetando robots.txt. Lee cada página de una vez, con sus títulos y tablas. La búsqueda web no requiere clave. |
| **Navegador integrado** (Windows) | Los enlaces se abren junto a la conversación, con pestañas, pestañas privadas y descargas. El personaje examina la página y hace clic, escribe, elige, arrastra y sube archivos en ella. |
| **Mensajes** | Al preguntarle por sus mensajes, el personaje lee los sitios en los que usted inició sesión e informa de lo nuevo. Ese paso solo lee: las páginas van a una llamada al modelo sin herramientas. |
| **Otros programas** (Windows) | Lee y maneja ventanas de otros programas mediante UI Automation, también aplicaciones Electron, y solo mientras usted no usa el teclado ni el ratón. |
| **Archivos y comandos** | Su carpeta de usuario y sus otros discos, sin autorizar carpetas antes; los lugares con contraseñas, claves, perfiles del navegador o datos de otros programas nunca se leen, y una carpeta que usted marque como solo ver o retire en Ajustes queda así. Los documentos de Word, Excel y PowerPoint se escriben como archivos. Los comandos se analizan antes de ejecutarse; los cambios de archivos de cada turno se pueden deshacer; en Windows, lo eliminado va a la Papelera de reciclaje. |
| **Habilidades y conectores** | Habilidades (carpetas con `SKILL.md`) y servidores MCP, cada uno con un catálogo seleccionado. Un mensaje que empieza por `/name` (el nombre de la habilidad) la activa. |
| **Configuración** | El personaje conoce la configuración de la aplicación: la enumera, abre Configuración en un apartado y cambia uno. Un cambio que no amplía nada se hace de inmediato; las claves nunca se muestran. |
| **Tareas programadas** | Recordatorios, tareas y comprobaciones periódicas. Al ejecutarse solo leen, además de lo que usted permitió al crearlas; un encargo periódico de enviar o publicar actúa solo en el sitio, para el destinatario y con el tipo de acción y el texto que usted indicó. |
| **Recomendaciones** | Un hallazgo cada vez, de fuentes públicas, ordenado por el tiempo que usted le dedica y no por los clics. Cada tarjeta indica su motivo y admite valoraciones que se pueden deshacer. |
| **Idiomas** | Diez idiomas de interfaz. |

## Personajes

<p align="center"><img src="characters.webp" alt="Mibo · Dragona Blanca · Pez Gordo · Señorita" width="100%"></p>

<p align="center">Mibo · Dragona Blanca · Pez Gordo · Señorita</p>

## Instalación

Descárguelo de la [última versión](https://github.com/wangkant/mibo/releases/latest). Los instaladores no tienen firma de código, por lo que el sistema muestra una advertencia antes del primer inicio.

| Sistema | Archivo | Primer inicio |
|---|---|---|
| Windows 10 u 11 (x64) | `mibo-0.2.0-setup.exe` | Si el navegador advierte sobre el archivo, elija **Conservar**. Cuando SmartScreen muestre «Windows protegió su PC», elija **Más información** y después **Ejecutar de todas formas**. Se instala solo para su cuenta y no requiere permisos de administrador. |
| macOS (Apple silicon) | `mibo-0.2.0-macos-arm64.dmg` | Abra la imagen de disco y arrastre `mibo.app` a Aplicaciones. La primera apertura se bloquea porque la aplicación no está notarizada: cierre el mensaje y, en Ajustes del Sistema › Privacidad y seguridad, elija **Abrir igualmente** y confirme. |

Las versiones nuevas se instalan igual, sobre la anterior. La app instalada en Windows también puede actualizarse sola: Configuración › Acerca de ofrece la versión nueva, comprueba la descarga con las sumas de verificación de la versión, la instala sobre la anterior con las mismas opciones y vuelve a abrirse. Al desinstalar se conserva la carpeta de datos.

### Sin el instalador

| | |
|---|---|
| **Windows, versión portátil** | Descargue `mibo-0.2.0-windows-x64.zip`, descomprímalo en cualquier carpeta y ejecute `mibo.exe`. Tampoco está firmado. |
| **Scoop** (Windows) | Ejecute `scoop bucket add mibo https://github.com/wangkant/scoop-mibo` y, a continuación, `scoop install mibo`. |
| **Homebrew** (macOS, Apple silicon) | Ejecute `brew install --cask wangkant/mibo/mibo`. |
| **Con Python** (3.10–3.14, cualquier sistema) | Ejecute `pipx install "mibo[app,web]"` o `uv tool install "mibo[app,web]"` y, a continuación, `mibo`. |

### Desde el código fuente (Linux y desarrollo)

Requiere Python 3.10–3.14.

```bash
git clone https://github.com/wangkant/mibo
cd mibo
python -m pip install -e ".[app,web]"
mibo
```

`app` añade el componente de ventanas en macOS y Linux; `web` añade Playwright para las salidas. Para desarrollar, instale `".[dev]"` y ejecute `python -m pytest -q`; consulte [CONTRIBUTING](../../.github/CONTRIBUTING.md) (en inglés).

## Primer inicio

1. Elija un idioma, un personaje y un modelo; después, los temas que le interesan y unas palabras sobre usted.
2. Para el modelo, elija un servicio y pegue su clave, inicie sesión con OpenRouter para usar sus modelos gratuitos, o elija Ollama o LM Studio si están en marcha.
3. La clave se guarda en el almacén de credenciales del sistema (Administrador de credenciales de Windows, llavero de macOS, Secret Service en Linux), nunca en un archivo. En un sistema sin almacén, se guarda en `credentials.json`, legible solo por su cuenta, y Configuración › Este equipo lo indica.

Los datos se guardan en una sola carpeta: `~/mibo` en una copia instalada, el propio clon si se ejecuta desde el código fuente, o la carpeta indicada con `mibo --home DIR`. La configuración se guarda allí, en `settings.json`. Mibo se inicia al iniciar sesión de forma predeterminada; Configuración › Este equipo lo desactiva.

## Privacidad y seguridad

| | |
|---|---|
| **Su servicio de modelos** | Recibe sus mensajes, la memoria pertinente, las páginas y archivos usados para una respuesta y los pasos que juzga la revisión. Su clave solo se envía a este servicio. Un aviso lo dice una sola vez, al guardar un servicio por primera vez, y solo vuelve a mostrarse si el servicio cambia. |
| **Sitios web** | Las salidas leen páginas públicas sin iniciar sesión, tres al día de forma predeterminada (Configuración › Salidas); una respuesta lee las páginas que necesita. Sus sesiones permanecen en el navegador integrado y solo se usan allí. |
| **Otros servicios** | Una consulta de búsqueda cuando una respuesta busca; el número de versión a GitHub como máximo una vez al día; consultas al catálogo cuando abre un mercado; lo que el personaje pasa a las herramientas de un servidor MCP. |
| **Siempre pregunta** | Un paso costoso se pregunta cada vez y por separado, en cualquier modo: pagar o gastar, una eliminación que nada restaura, la propia cuenta, entregar acceso o datos privados, un envío vinculante, un cambio en este equipo que deshacer no puede revertir. Ningún sí anterior ni tarea programada lo cubre. Una eliminación que va a la Papelera no se pregunta. Un paso así se pregunta en una tarjeta cuyo botón nombra la acción; solo su propio mensaje escrito en el chat o su pulsación en esa tarjeta cuenta como un sí. |
| **Contenido leído** | Lo que una herramienta lee de la web o de este equipo es material, nunca una instrucción. Tras leerlo, se pregunta antes de enviar algo a un lugar que usted no indicó, y también antes de un comando copiado al pie de la letra. Un programa descargado nunca se ejecuta. |
| **Nunca** | Escribir por usted contraseñas, códigos o datos de pago, que siempre introduce usted; ejecutar nada como administrador; leer las claves del modelo, la configuración de la aplicación o el perfil del navegador integrado, que ninguna herramienta puede abrir. |
| **Comandos** | En Windows, cada comando se ejecuta además bajo límites que impone el propio Windows: sin derechos de administrador, sin acceso a los archivos propios de la aplicación, sin salir del grupo en el que se ejecutan sus programas, sin portapapeles; un comando clasificado como de solo lectura no puede cambiar ningún archivo ni ajuste. Estos límites no impiden que un comando lea sus demás archivos o llegue a la red; de eso se ocupan el análisis previo y su consentimiento. |
| **Sin supervisión** | Solo las salidas y las tareas programadas que usted cree. |

[SECURITY](../../.github/SECURITY.md) (en inglés) enumera todos los destinos y dónde se guarda cada tipo de dato.

## Requisitos

| | Windows | macOS | Linux |
|---|---|---|---|
| **Instalación** | Instalador | Imagen de disco | Código fuente |
| **Sistema** | Windows 10 u 11, x64 | Apple silicon | Python 3.10–3.14 |
| **Navegador integrado, otros programas, figura de escritorio** | Sí | No | No |
| **Salidas** | Edge, ya instalado | Edge, Chrome o Chromium | Edge, Chrome o Chromium |
| **Modelo** | Un servicio compatible con OpenAI con su clave, o un servidor de modelos local | Igual | Igual |

## Licencia

[Apache License 2.0](../../LICENSE). El código de terceros conserva su propia licencia ([NOTICE](../../NOTICE)); los retratos de los personajes están bajo CC BY-NC-SA 4.0 ([detalles](../../mibo/static/characters/LICENSE.md)). Consulte el [aviso legal](../DISCLAIMER.es.md) y el [registro de cambios](../../CHANGELOG.md) (en inglés).
