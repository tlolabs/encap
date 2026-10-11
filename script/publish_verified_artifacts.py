#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish only target packages that passed native build and smoke verification."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, check=True, capture=False):
    return subprocess.run(
        args, cwd=ROOT, check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(path, version):
    match = re.fullmatch(
        rf"EnCap-{re.escape(version)}-(macos-(?:arm64|intel)|windows-(?:x64|arm64)|linux-(?:x64|arm64))\.(zip|AppImage)",
        path.name,
    )
    if not match:
        raise ValueError(f"Unexpected package name: {path.name}")
    target, extension = match.groups()
    if extension == "zip":
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"{path.name}: corrupt ZIP member {bad_member}")
            if not archive.namelist():
                raise ValueError(f"{path.name}: empty ZIP archive")
    else:
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError(f"{path.name}: not an ELF AppImage")
    if path.stat().st_size == 0:
        raise ValueError(f"{path.name}: empty package")
    return target


def release_info(tag):
    result = run("gh", "release", "view", tag, "--json", "isDraft,isPrerelease,assets", check=False, capture=True)
    if result.returncode:
        return None
    return json.loads(result.stdout)


def same_remote_asset(tag, filename, expected_hash):
    with tempfile.TemporaryDirectory(prefix="encap-release-") as temporary:
        result = run(
            "gh", "release", "download", tag, "--pattern", filename,
            "--dir", temporary, check=False,
        )
        downloaded = Path(temporary) / filename
        if result.returncode or not downloaded.is_file():
            return False
        return sha256(downloaded) == expected_hash


def publish(tag, directory):
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    if tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} does not match workspace version v{version}")

    package_name = re.compile(
        rf"EnCap-{re.escape(version)}-(?:macos-(?:arm64|intel)|windows-(?:x64|arm64)|linux-(?:x64|arm64))\.(?:zip|AppImage)"
    )
    packages = sorted(
        (path for path in directory.iterdir() if path.is_file() and package_name.fullmatch(path.name)),
        key=lambda path: path.name,
    )
    verified = []
    for path in packages:
        target = verify_package(path, version)
        verified.append((path, target, sha256(path)))
    if not verified:
        print("No verified platform artifacts were uploaded by this run; nothing to publish.")
        return 0

    info = release_info(tag)
    if info and info["isPrerelease"]:
        raise ValueError(f"Refusing to add stable packages to prerelease {tag}")
    if info is None:
        run("gh", "release", "create", tag, "--verify-tag", "--draft", "--title", tag, "--generate-notes")
        info = release_info(tag)
        if info is None:
            raise RuntimeError(f"Could not read newly created draft release {tag}")

    existing = {asset["name"] for asset in info["assets"]}
    published = []
    for path, target, digest in verified:
        if path.name in existing:
            if same_remote_asset(tag, path.name, digest):
                print(f"Already published unchanged: {path.name}")
                published.append(target)
            else:
                print(f"Refusing to overwrite different release asset: {path.name}", file=sys.stderr)
            continue
        result = run("gh", "release", "upload", tag, str(path), check=False)
        if result.returncode:
            print(f"Could not upload {path.name}; continuing with other platforms.", file=sys.stderr)
            continue
        if not same_remote_asset(tag, path.name, digest):
            print(f"Uploaded asset failed byte-for-byte verification: {path.name}", file=sys.stderr)
            continue
        existing.add(path.name)
        published.append(target)
        print(f"Verified uploaded asset: {path.name} sha256={digest}")

    if published:
        run("gh", "release", "edit", tag, "--draft=false", "--latest=true")
        print("Published verified platforms: " + ", ".join(sorted(set(published))))
    else:
        raise RuntimeError(f"No verified packages could be published for {tag}; draft release retained")
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("Usage: publish_verified_artifacts.py TAG ARTIFACT_DIRECTORY")
        raise SystemExit(publish(sys.argv[1], Path(sys.argv[2])))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Release publication failed: {error}", file=sys.stderr)
        raise SystemExit(1)
