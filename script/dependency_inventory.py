#!/usr/bin/env python3
"""Generate a deterministic dependency inventory or release SPDX SBOM."""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "docs" / "dependency-inventory.json"


def rust_packages():
    result = subprocess.check_output(
        ["cargo", "metadata", "--locked", "--format-version", "1"],
        cwd=ROOT,
        text=True,
    )
    metadata = json.loads(result)
    packages = []
    for package in metadata["packages"]:
        source = package.get("source")
        if source is None:
            source = "workspace"
        packages.append(
            {
                "ecosystem": "cargo",
                "name": package["name"],
                "version": package["version"],
                "source": source,
                "license": package.get("license") or "NOASSERTION",
            }
        )
    return packages


def swift_packages():
    resolved = json.loads(
        (ROOT / "helpers/whisperkit_transcriber/Package.resolved").read_text()
    )
    pins = resolved.get("pins", resolved.get("object", {}).get("pins", []))
    packages = []
    for pin in pins:
        state = pin["state"]
        packages.append(
            {
                "ecosystem": "swift",
                "name": pin.get("identity", pin.get("package")),
                "version": state.get("version") or state["revision"],
                "source": pin.get("location", pin.get("repositoryURL", "NOASSERTION")),
                "revision": state["revision"],
                "license": "NOASSERTION",
            }
        )
    return packages


def runtime_packages():
    spec = json.loads((ROOT / "runtime/ffmpeg/dependency.json").read_text())
    packages = [
        {
            "ecosystem": "source-runtime",
            "name": "ffmpeg",
            "version": spec["source"]["version"],
            "source": spec["source"]["url"],
            "sha256": spec["source"]["sha256"],
            "license": "GPL-2.0-or-later",
        }
    ]
    for name, item in spec["external_libraries"].items():
        packages.append(
            {
                "ecosystem": "source-runtime",
                "name": name,
                "version": item["version"],
                "source": item["url"],
                "sha256": item["sha256"],
                "license": item["license"],
            }
        )
    return packages


def other_packages():
    windows = (ROOT / "windows/EnCap/EnCap.csproj").read_text()
    import re

    match = re.search(
        r'<PackageReference Include="Microsoft.WindowsAppSDK" Version="([^"]+)"',
        windows,
    )
    assert match, "Windows App SDK package reference is missing"
    return [
        {
            "ecosystem": "nuget",
            "name": "Microsoft.WindowsAppSDK",
            "version": match.group(1),
            "source": "https://www.nuget.org/packages/Microsoft.WindowsAppSDK",
            "license": "NOASSERTION",
        },
        {
            "ecosystem": "source-runtime",
            "name": "whisper.cpp",
            "version": "v1.9.1",
            "source": "https://github.com/ggml-org/whisper.cpp",
            "revision": "f049fff95a089aa9969deb009cdd4892b3e74916",
            "license": "MIT",
        },
        {
            "ecosystem": "source-runtime",
            "name": "Sparkle",
            "version": "2.9.6",
            "source": "https://github.com/sparkle-project/Sparkle",
            "license": "MIT",
        },
    ]


def inventory():
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"][
        "package"
    ]["version"]
    packages = rust_packages() + swift_packages() + runtime_packages() + other_packages()
    packages.sort(key=lambda item: (item["ecosystem"], item["name"], item["version"]))
    return {
        "schema": 1,
        "project": "EnCap",
        "version": version,
        "inputs": [
            "Cargo.lock",
            "helpers/whisperkit_transcriber/Package.resolved",
            "runtime/ffmpeg/dependency.json",
            "windows/EnCap/EnCap.csproj",
        ],
        "packages": packages,
        "limitations": [
            "Swift pin licenses need verification against exact upstream source.",
            "NuGet transitive and Linux system dependencies depend on release build resolution.",
            "Optional user-downloaded speech models are not distributed in release packages.",
        ],
    }


def spdx(data):
    packages = []
    relationships = []
    for item in data["packages"]:
        key = "|".join(
            [item["ecosystem"], item["name"], item["version"], item["source"]]
        )
        identifier = "SPDXRef-Package-" + hashlib.sha256(key.encode()).hexdigest()[:20]
        packages.append(
            {
                "name": item["name"],
                "SPDXID": identifier,
                "versionInfo": item["version"],
                "downloadLocation": item["source"]
                if item["source"].startswith("https://")
                else "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": item["license"],
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:{item['ecosystem']}/{item['name']}@{item['version']}",
                    }
                ],
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": identifier,
                "relationshipType": "DESCRIBES",
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"encap-{data['version']}-dependencies",
        "documentNamespace": f"https://github.com/tlolabs/encap/sbom/{data['version']}/{hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}",
        "creationInfo": {
            "creators": ["Tool: EnCap dependency_inventory.py"],
            "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "packages": packages,
        "relationships": relationships,
    }


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--spdx", type=pathlib.Path)
    args = parser.parse_args()
    data = inventory()
    rendered = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.write:
        INVENTORY.write_text(rendered)
    elif args.check:
        if not INVENTORY.exists() or INVENTORY.read_text() != rendered:
            sys.exit("Dependency inventory drift; run script/dependency_inventory.py --write")
    else:
        args.spdx.write_text(json.dumps(spdx(data), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
