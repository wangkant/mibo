# PyInstaller: personagent as one folder with a program and no console.
# build.ps1 runs it on Windows; the release workflow runs it on macOS too,
# where the folder becomes personagent.app. It freezes the installed copy
# (pip install ".[app,web]"), so persona_agent/_bundled is there.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import persona_agent

MACOS = sys.platform == "darwin"
package = Path(persona_agent.__file__).resolve().parent
static = package / "static"

# The package's own files (pages, locales, portraits); _bundled is added whole
# below, its .py files with it: they are copied out (the AstrBot plugin), not imported.
datas = [d for d in collect_data_files("persona_agent") if "_bundled" not in Path(d[1]).parts]
for folder, dirs, files in os.walk(package / "_bundled"):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for name in files:
        datas.append((os.path.join(folder, name), str(Path("persona_agent") / Path(folder).relative_to(package))))

# Imported by name: the commands, the panels, the platforms, the chat languages;
# uvicorn's protocols and ddgs's engines the same way.
hiddenimports = (collect_submodules("persona_agent") + collect_submodules("uvicorn")
                 + collect_submodules("ddgs"))

# uv, which installs AstrBot here (astrbot_install.py): the build has no Python to make a venv with.
from uv import find_uv_bin

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    binaries=[(find_uv_bin(), ".")],
    datas=datas,
    hiddenimports=hiddenimports,
    # Test and build tools a dependency may name; nothing at run time imports them.
    excludes=["pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="personagent",
    console=False,
    icon=str(static / ("app.png" if MACOS else "app.ico")),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="personagent", upx=False)

if MACOS:
    app = BUNDLE(
        coll,
        name="personagent.app",
        icon=str(static / "app.png"),
        bundle_identifier="com.github.wangkant.personagent",
        info_plist={
            "CFBundleName": "personagent",
            "CFBundleShortVersionString": persona_agent.__version__,
            "CFBundleVersion": persona_agent.__version__,
            "NSHighResolutionCapable": True,
        },
    )
