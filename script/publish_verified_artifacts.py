#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish one package from a successful target job as a direct download."""
import argparse
import hashlib
import json
import plistlib
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "tlolabs/encap"
TARGETS = {
    "macos-arm64": "zip", "macos-intel": "zip",
    "windows-x64": "zip", "windows-arm64": "zip",
    "linux-x64": "AppImage", "linux-arm64": "AppImage",
}


def run(*args, check=True, capture=False):
    return subprocess.run(args, cwd=ROOT, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publication_identity(ref, sha, version):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected the exact verified source commit SHA")
    if ref == "refs/heads/main":
        return f"dev-v{version}-{sha}", True
    if ref == f"refs/tags/v{version}":
        return f"v{version}", False
    raise ValueError(f"Ref {ref!r} is not eligible for publication")


def verify_package(path, version, target):
    expected = f"EnCap-{version}-{target}.{TARGETS[target]}"
    if (path.name != expected or not path.is_file()
            or not 0 < path.stat().st_size <= 2 * 1024**3):
        raise ValueError(f"Expected exactly {expected}")
    if target.startswith("linux-"):
        with path.open("rb") as stream:
            header = stream.read(11)
        if header[:4] != b"\x7fELF" or header[8:11] != b"AI\x02":
            raise ValueError(f"{path.name}: not a type 2 AppImage")
    else:
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or archive.testzip():
                raise ValueError(f"{path.name}: invalid ZIP")
            names = set(archive.namelist())
            if target.startswith("macos-"):
                root = "EnCap.app/Contents/"
                required = {root + name for name in
                            ("Info.plist", "MacOS/EnCap", "MacOS/encap-engine",
                             "MacOS/ffmpeg", "MacOS/ffprobe",
                             "Resources/update-config.json")}
                if not required <= names:
                    raise ValueError(f"{path.name}: incomplete macOS application")
                info = plistlib.loads(archive.read(root + "Info.plist"))
                if (info.get("CFBundleIdentifier") != "com.tlolabs.encap"
                        or info.get("CFBundleVersion") != version
                        or info.get("CFBundleShortVersionString") != version):
                    raise ValueError(f"{path.name}: wrong macOS identity")
                config = json.loads(archive.read(root + "Resources/update-config.json"))
            else:
                required = {"EnCap.exe", "encap-engine.exe", "ffmpeg.exe",
                            "ffprobe.exe", "update-config.json"}
                if not required <= names:
                    raise ValueError(f"{path.name}: incomplete Windows application")
                config = json.loads(archive.read("update-config.json"))
            if any(config.get(key) != value for key, value in {
                "application_id": "com.tlolabs.encap",
                "repository": REPOSITORY,
                "version": version,
                "channel": "stable",
                "target": target,
            }.items()):
                raise ValueError(f"{path.name}: wrong packaged update identity")


def release_info(tag):
    result = run("gh", "release", "view", tag, "--repo", REPOSITORY,
                 "--json", "isDraft,isPrerelease,assets", check=False, capture=True)
    return json.loads(result.stdout) if result.returncode == 0 else None


def same_remote_asset(tag, filename, expected_hash):
    with tempfile.TemporaryDirectory(prefix="encap-release-") as temporary:
        result = run("gh", "release", "download", tag, "--repo", REPOSITORY,
                     "--pattern", filename, "--dir", temporary, check=False)
        downloaded = Path(temporary) / filename
        return result.returncode == 0 and downloaded.is_file() and sha256(downloaded) == expected_hash


def ensure_release(tag, sha, prerelease):
    if prerelease:
        tag_ref = run("gh", "api", f"repos/{REPOSITORY}/git/ref/tags/{tag}",
                      check=False, capture=True)
        if tag_ref.returncode == 0 and json.loads(tag_ref.stdout)["object"]["sha"] != sha:
            raise RuntimeError(f"Development tag {tag} points to another revision")
    info = release_info(tag)
    if info is None:
        args = ["gh", "release", "create", tag, "--repo", REPOSITORY,
                "--draft", "--title", tag, "--generate-notes"]
        if prerelease:
            args += ["--target", sha, "--prerelease", "--latest=false"]
        else:
            args += ["--verify-tag"]
        # Other independently finishing platforms may create the same release first.
        run(*args, check=False)
        info = release_info(tag)
    if info is None or info["isPrerelease"] != prerelease:
        raise RuntimeError(f"Release {tag} is missing or has the wrong channel")
    if prerelease:
        tag_ref = run("gh", "api", f"repos/{REPOSITORY}/git/ref/tags/{tag}",
                      capture=True)
        if json.loads(tag_ref.stdout)["object"]["sha"] != sha:
            raise RuntimeError(f"Development tag {tag} does not point to verified source")
    return info


def upload_verified(tag, path, existing):
    digest = sha256(path)
    if path.name in existing:
        if not same_remote_asset(tag, path.name, digest):
            raise RuntimeError(f"Refusing to replace different release asset {path.name}")
        print(f"Already published unchanged: {path.name}")
        return
    # A concurrent platform publisher can upload first. Accept only identical bytes.
    run("gh", "release", "upload", tag, str(path), "--repo", REPOSITORY, check=False)
    if not same_remote_asset(tag, path.name, digest):
        raise RuntimeError(f"Release asset {path.name} did not verify byte for byte")
    print(f"Verified uploaded asset: {path.name} sha256={digest}")


def publish(ref, sha, target, directory, source_version=None):
    if target not in TARGETS:
        raise ValueError(f"Unsupported target {target}")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected a Git object SHA for the source revision")
    if source_version is None:
        # Annotated stable tags may provide a tag object; bind packages to its commit.
        sha = run("git", "rev-parse", f"{sha}^{{commit}}", capture=True).stdout.strip()
        head = run("git", "rev-parse", "HEAD", capture=True).stdout.strip()
        if head != sha:
            raise ValueError(f"Publisher checkout {head} differs from verified build {sha}")
        version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    else:
        # workflow_run recovery executes trusted main-branch publisher code. Its
        # caller reads this data from Cargo.toml at the completed run's SHA.
        version = source_version
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Expected a stable Cargo SemVer version")
    tag, prerelease = publication_identity(ref, sha, version)
    path = directory / f"EnCap-{version}-{target}.{TARGETS[target]}"
    if {item.name for item in directory.iterdir()} != {path.name}:
        raise ValueError(f"Expected one verified {target} artifact in {directory}")
    verify_package(path, version, target)
    digest = sha256(path)
    checksum = directory / f"{path.name}.sha256"
    checksum.write_text(f"{digest}  {path.name}\n")
    info = ensure_release(tag, sha, prerelease)
    existing = {asset["name"] for asset in info["assets"]}
    upload_verified(tag, path, existing)
    upload_verified(tag, checksum, existing)
    run("gh", "release", "edit", tag, "--repo", REPOSITORY,
        "--draft=false", f"--latest={'false' if prerelease else 'true'}")
    print(f"Published {target} to {tag}")
    return tag


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-version")
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("artifact_directory", type=Path)
    args = parser.parse_args()
    try:
        publish(args.source_ref, args.source_sha, args.target, args.artifact_directory,
                args.source_version)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Release publication failed: {error}", file=sys.stderr)
        raise SystemExit(1)
