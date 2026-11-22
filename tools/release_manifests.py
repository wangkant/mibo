"""Write the package managers' manifests for a published release from its SHA256SUMS.txt.

    python tools/release_manifests.py 0.1.0 --sums SHA256SUMS.txt --out manifests/

It writes, under --out:
    scoop/mibo.json                      a Scoop bucket's manifest (the Windows zip)
    homebrew/Casks/mibo.rb               a Homebrew tap's cask (the macOS disk image)
    winget/manifests/w/wangkant/Mibo/<version>/   the three files winget-pkgs takes (the Windows installer)

The files of a release are named as .github/workflows/release.yml names them, and their addresses are the GitHub
Release's. Nothing is fetched and nothing is published here: the files are copied to where each manager reads them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = "https://github.com/wangkant/mibo"
IDENTIFIER = "wangkant.Mibo"
PUBLISHER = "Qiankang Wang"
SHORT = "An AI companion on your desktop that talks with you, remembers you and acts for you"
LICENSE = "Apache-2.0"
UNSIGNED = ("Mibo is not signed yet. The first time, right-click mibo.app and choose Open, or allow it in "
            "System Settings > Privacy & Security.")


def sums(text: str) -> dict[str, str]:
    """{file name: sha256} of a SHA256SUMS file's lines."""
    found = {}
    for line in text.splitlines():
        digest, _, name = line.strip().partition(" ")
        if len(digest) == 64 and name.strip():
            found[name.strip().lstrip("*")] = digest.lower()
    return found


def scoop(version: str, digest: str) -> str:
    asset = f"{REPO}/releases/download/v$version/mibo-$version-windows-x64.zip"
    return json.dumps({
        "version": version,
        "description": SHORT,
        "homepage": REPO,
        "license": {"identifier": LICENSE, "url": f"{REPO}/blob/main/LICENSE"},
        "notes": "Mibo is not signed yet: the first start may show Windows SmartScreen (More info > Run anyway).",
        "architecture": {"64bit": {"url": asset.replace("$version", version), "hash": digest}},
        "extract_dir": "mibo",
        "bin": "mibo.exe",
        "shortcuts": [["mibo.exe", "Mibo"]],
        "checkver": {"github": REPO},
        "autoupdate": {"architecture": {"64bit": {"url": asset}}},
    }, indent=4) + "\n"


def cask(version: str, digest: str) -> str:
    return f'''cask "mibo" do
  version "{version}"
  sha256 "{digest}"

  url "{REPO}/releases/download/v#{{version}}/mibo-#{{version}}-macos-arm64.dmg"
  name "Mibo"
  desc "{SHORT}"
  homepage "{REPO}"

  depends_on arch: :arm64

  app "mibo.app"

  caveats <<~EOS
    {UNSIGNED}
  EOS
end
'''


def winget(version: str, digest: str) -> dict[str, str]:
    """winget-pkgs' three files (schema 1.10.0): the version, the installer and the default locale."""
    head = f"PackageIdentifier: {IDENTIFIER}\nPackageVersion: {version}\n"
    return {
        f"{IDENTIFIER}.yaml": (
            "# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.1.10.0.schema.json\n"
            f"{head}DefaultLocale: en-US\nManifestType: version\nManifestVersion: 1.10.0\n"),
        f"{IDENTIFIER}.installer.yaml": (
            "# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.10.0.schema.json\n"
            f"{head}InstallerType: inno\nScope: user\nInstallModes:\n- interactive\n- silent\n- silentWithProgress\n"
            "UpgradeBehavior: install\nInstallers:\n- Architecture: x64\n"
            f"  InstallerUrl: {REPO}/releases/download/v{version}/mibo-{version}-setup.exe\n"
            f"  InstallerSha256: {digest.upper()}\nManifestType: installer\nManifestVersion: 1.10.0\n"),
        f"{IDENTIFIER}.locale.en-US.yaml": (
            "# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.1.10.0.schema.json\n"
            f"{head}PackageLocale: en-US\nPublisher: {PUBLISHER}\nPublisherUrl: https://github.com/wangkant\n"
            f"PublisherSupportUrl: {REPO}/issues\nPackageName: Mibo\nPackageUrl: {REPO}\nLicense: {LICENSE}\n"
            f"LicenseUrl: {REPO}/blob/main/LICENSE\nShortDescription: {SHORT}\nMoniker: mibo\nTags:\n- ai\n"
            f"- assistant\n- companion\n- desktop\nReleaseNotesUrl: {REPO}/releases/tag/v{version}\n"
            "ManifestType: defaultLocale\nManifestVersion: 1.10.0\n"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version")
    parser.add_argument("--sums", required=True, help="the release's SHA256SUMS.txt")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    version = args.version.lstrip("v")
    found = sums(Path(args.sums).read_text(encoding="utf-8"))
    names = {"zip": f"mibo-{version}-windows-x64.zip", "dmg": f"mibo-{version}-macos-arm64.dmg",
             "setup": f"mibo-{version}-setup.exe"}
    missing = [name for name in names.values() if name not in found]
    if missing:
        print(f"SHA256SUMS has no line for: {', '.join(missing)}", file=sys.stderr)
        return 1
    out = Path(args.out)
    files = {out / "scoop" / "mibo.json": scoop(version, found[names["zip"]]),
             out / "homebrew" / "Casks" / "mibo.rb": cask(version, found[names["dmg"]])}
    folder = out / "winget" / "manifests" / "w" / "wangkant" / "Mibo" / version
    files.update({folder / name: text for name, text in winget(version, found[names["setup"]]).items()})
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
