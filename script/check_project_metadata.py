#!/usr/bin/env python3
"""Check the authoritative version and platform support matrix against build files."""

import json
import pathlib
import re
import tomllib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
matrix = json.loads((ROOT / "docs/support-matrix.json").read_text())["targets"]
cargo = tomllib.loads((ROOT / "Cargo.toml").read_text())
version = cargo["workspace"]["package"]["version"]
assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), version

windows = ET.parse(ROOT / "windows/EnCap/EnCap.csproj").getroot()
value = lambda name: windows.findtext(f".//{name}")
assert value("Version") == version
assert value("TargetPlatformMinVersion") == matrix["windows"]["minimum_build"]
assert matrix["windows"]["minimum_build"] in value("TargetFramework")

meson = (ROOT / "linux/EnCap/meson.build").read_text()
assert f"version: '{version}'" in meson
assert f">={matrix['linux']['gtk_minimum']}" in meson
assert f">={matrix['linux']['libadwaita_minimum']}" in meson

project = (ROOT / "macos/EnCap.xcodeproj/project.pbxproj").read_text()
assert project.count(f"MARKETING_VERSION = {version};") == 2
assert project.count(
    f"MACOSX_DEPLOYMENT_TARGET = {matrix['macos']['minimum_os']};"
) == 2
package = (ROOT / "macos/Package.swift").read_text()
assert f".macOS(.v{matrix['macos']['minimum_os'].split('.')[0]})" in package
plist = ET.parse(ROOT / "macos/EnCap/Resources/Info.plist").getroot()
entries = list(plist.find("dict"))
keys = {entries[i].text: entries[i + 1].text for i in range(0, len(entries) - 1, 2)}
assert keys["LSMinimumSystemVersion"] == matrix["macos"]["minimum_os"]

recipe = json.loads((ROOT / "runtime/ffmpeg/dependency.json").read_text())["targets"]
for target in ("macos-arm64", "macos-x86_64"):
    assert recipe[target]["minimum_os"] == matrix["macos"]["minimum_os"]
for target in ("windows-x86_64", "windows-arm64"):
    assert recipe[target]["minimum_os"] == matrix["windows"]["minimum_os"]
for target in ("linux-x86_64", "linux-arm64"):
    assert recipe[target]["minimum_os"] == matrix["linux"]["validated_baseline"]

workflow = (ROOT / ".github/workflows/build-platforms.yml").read_text()
assert f'MACOSX_DEPLOYMENT_TARGET: "{matrix["macos"]["minimum_os"]}"' in workflow
assert "ubuntu-24.04" in workflow
readme = (ROOT / "README.md").read_text()
for platform, architectures in (
    ("macOS", matrix["macos"]["architectures"]),
    ("Windows", matrix["windows"]["architectures"]),
    ("Linux", matrix["linux"]["architectures"]),
):
    for architecture in architectures:
        label = "ARM64" if architecture == "arm64" else "x64"
        assert f"{platform} ({label})" in readme
print(f"Project version {version} and support matrix agree.")
