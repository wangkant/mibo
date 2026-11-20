# Builds dist\mibo-<version>-setup.exe from a clean checkout:
# a venv of its own here (.venv), mibo and PyInstaller in it, the
# frozen folder (PyInstaller), then the installer (Inno Setup 6).
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
# -Python names the interpreter for the venv (default: python on PATH).
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here "..\..")).Path
$venv = Join-Path $here ".venv"
$py = Join-Path $venv "Scripts\python.exe"

function Run($program) {
    & $program @args
    if ($LASTEXITCODE) { throw "$program $args failed ($LASTEXITCODE)" }
}

# The version is pyproject.toml's, as the wheel has it.
$version = (Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value

if (-not (Test-Path $py)) { Run $Python -m venv $venv }
Run $py -m pip install --quiet --upgrade pip
# Installed, not editable: the wheel's mibo/_bundled is what the build reads.
# app brings nothing more on Windows; web is Playwright, which drives the browser already there.
Run $py -m pip install --quiet --upgrade "$root[app,web]" "pyinstaller>=6.10,<7"

Push-Location $here
try {
    # Outside the checkout, so the installed copy is the one frozen.
    Run $py -m PyInstaller --noconfirm --clean --distpath (Join-Path $here "dist") --workpath (Join-Path $here "build") mibo.spec

    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    foreach ($folder in "$env:LOCALAPPDATA\Programs\Inno Setup 6", "${env:ProgramFiles(x86)}\Inno Setup 6", "$env:ProgramFiles\Inno Setup 6") {
        if (-not $iscc -and (Test-Path "$folder\ISCC.exe")) { $iscc = "$folder\ISCC.exe" }
    }
    if (-not $iscc) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Run winget install --id JRSoftware.InnoSetup --exact --scope user --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
            $iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        } else {
            # GitHub's Windows runners have Chocolatey, not always winget.
            Run choco install innosetup -y --no-progress
            $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        }
    }
    # Not quiet: ISCC's warnings (an unknown message name, say) only show here.
    Run $iscc "/DAppVersion=$version" mibo.iss
} finally {
    Pop-Location
}
Write-Host "dist\mibo-$version-setup.exe"
