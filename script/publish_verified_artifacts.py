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
        tag_endpoint = f"repos/{REPOSITORY}/git/ref/tags/{tag}"
        tag_ref = run("gh", "api", tag_endpoint, check=False, capture=True)
        if tag_ref.returncode != 0:
            # A draft release does not create its tag until publication. Create
            # it first so concurrent platform publishers share one source ref.
            run("gh", "api", "-X", "POST", f"repos/{REPOSITORY}/git/refs",
                "-f", f"ref=refs/tags/{tag}", "-f", f"sha={sha}",
                check=False, capture=True)
            tag_ref = run("gh", "api", tag_endpoint, capture=True)
        if json.loads(tag_ref.stdout)["object"]["sha"] != sha:
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


import os
import xml.etree.ElementTree as ET


def fetch_remote_text(tag, filename):
    with tempfile.TemporaryDirectory(prefix="encap-release-") as temporary:
        result = run("gh", "release", "download", tag, "--repo", REPOSITORY,
                     "--pattern", filename, "--dir", temporary, check=False)
        downloaded = Path(temporary) / filename
        if result.returncode == 0 and downloaded.is_file():
            return downloaded.read_text(encoding="utf-8")
    return None


def verify_authenticated_feed(tag, info, version, public_key_bytes=None):
    """Verify that the release contains authentic signed update metadata matching its assets."""
    if not info or not info.get("assets"):
        return False
    remote_assets = {a["name"]: a for a in info["assets"]}
    if "update-manifest.json" not in remote_assets:
        return False

    manifest_text = fetch_remote_text(tag, "update-manifest.json")
    if not manifest_text:
        return False

    try:
        envelope = json.loads(manifest_text)
        if not isinstance(envelope, dict) or "payload" not in envelope or "signature" not in envelope:
            return False
        import base64
        payload_raw = base64.b64decode(envelope["payload"], validate=True)
        sig_bytes = base64.b64decode(envelope["signature"], validate=True)

        if public_key_bytes is None:
            raw_key = os.environ.get("ENCAP_UPDATE_PUBLIC_KEY")
            if raw_key:
                public_key_bytes = base64.b64decode(raw_key.strip(), validate=True)
            elif (ROOT / "runtime/updater-public-key.txt").is_file():
                public_key_bytes = base64.b64decode((ROOT / "runtime/updater-public-key.txt").read_text().strip(), validate=True)

        if not public_key_bytes or len(public_key_bytes) != 32:
            return False

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(sig_bytes, payload_raw)
        except Exception:
            return False

        payload = json.loads(payload_raw.decode("utf-8"))
        if (payload.get("schema") != 2
                or payload.get("application_id") != "com.tlolabs.encap"
                or payload.get("repository") != REPOSITORY
                or payload.get("version") != version
                or payload.get("tag") != f"v{version}"
                or payload.get("channel") != "stable"
                or payload.get("draft")
                or payload.get("prerelease")
                or not payload.get("assets")):
            return False

        for target_name, asset in payload["assets"].items():
            fname = asset.get("filename")
            if not fname or fname not in remote_assets:
                return False
            if "size" in remote_assets[fname] and remote_assets[fname]["size"] != asset.get("size"):
                return False
            if asset.get("platform") == "macos":
                appcast_name = f"appcast-{target_name}.xml"
                if appcast_name not in remote_assets:
                    return False
                appcast_text = fetch_remote_text(tag, appcast_name)
                if not appcast_text:
                    return False
                tree = ET.fromstring(appcast_text)
                SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
                enclosure = tree.find(".//enclosure")
                if (enclosure is None
                        or enclosure.attrib.get("url") != asset.get("url")
                        or int(enclosure.attrib.get("length", 0)) != asset.get("size")
                        or tree.find(f".//{{{SPARKLE}}}version") is None
                        or tree.find(f".//{{{SPARKLE}}}version").text != version):
                    return False
                sig = enclosure.attrib.get(f"{{{SPARKLE}}}edSignature")
                if not sig:
                    return False
        return True
    except Exception:
        return False


def promote_feed(tag, version=None, public_key_bytes=None):
    """Promote an eligible release to latest only when its authenticated feeds satisfy contract."""
    info = release_info(tag)
    if not info:
        raise RuntimeError(f"Release {tag} was not found on remote repository")
    if version is None:
        if not tag.startswith("v"):
            raise ValueError(f"Tag {tag} is not a version tag")
        version = tag[1:]
    if not verify_authenticated_feed(tag, info, version, public_key_bytes):
        raise RuntimeError(f"Release {tag} does not satisfy authenticated update feed requirements")
    run("gh", "release", "edit", tag, "--repo", REPOSITORY,
        "--draft=false", "--latest=true")
    print(f"Successfully promoted {tag} to latest authenticated update release.")
    return True


def prepare_distribution_record(path, version, target, sha):
    """Associate package with source commit, Qt/FFmpeg provenance and license notices."""
    digest = sha256(path)
    record = {
        "schema": 1,
        "application": "EnCap",
        "version": version,
        "target": target,
        "source_commit": sha,
        "package_filename": path.name,
        "package_sha256": digest,
        "package_size": path.stat().st_size,
        "notices": [
            "THIRD_PARTY_NOTICES.md",
            "LICENSE",
            "desktop/vendor/miniaudio.LICENSE",
            "docs/qt-licensing.md"
        ],
        "corresponding_sources": {
            "encap_source_commit": sha,
            "miniaudio": {
                "upstream_version": "0.11.23",
                "pristine_sha256": "7e4f3f13c8fe66df2080ac3dd12a89193e3c2463cb7f067c798abd7331cd8ee6",
                "vendored_sha256": "e5cb323cec7932d068a225d7c84f8b895caa7027b6b052fe0085e825c323a730",
                "local_patches": "Overflow hardening in sample/frame allocation and buffer parsing"
            }
        }
    }
    provenance_path = path.parent / f"{path.name}.provenance.json"
    provenance_path.write_text(json.dumps(record, indent=2) + "\n")
    return provenance_path


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
    if not path.is_file():
        raise ValueError(f"Expected verified {target} artifact {path.name} in {directory}")
    verify_package(path, version, target)
    digest = sha256(path)
    checksum = directory / f"{path.name}.sha256"
    checksum.write_text(f"{digest}  {path.name}\n")
    provenance = prepare_distribution_record(path, version, target, sha)
    info = ensure_release(tag, sha, prerelease)
    existing = {asset["name"] for asset in info["assets"]}
    upload_verified(tag, path, existing)
    upload_verified(tag, checksum, existing)
    upload_verified(tag, provenance, existing)
    info = release_info(tag) or info
    promoted = False if prerelease else verify_authenticated_feed(tag, info, version)
    run("gh", "release", "edit", tag, "--repo", REPOSITORY,
        "--draft=false", f"--latest={'true' if promoted else 'false'}")
    print(f"Published {target} to {tag} (latest_promoted={promoted})")
    return tag


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref")
    parser.add_argument("--source-sha")
    parser.add_argument("--source-version")
    parser.add_argument("--target", choices=sorted(TARGETS))
    parser.add_argument("--promote-feed", action="store_true", help="Promote qualified release to latest")
    parser.add_argument("--tag")
    parser.add_argument("artifact_directory", nargs="?", type=Path)
    args = parser.parse_args()
    try:
        if args.promote_feed:
            if not args.tag:
                parser.error("--promote-feed requires --tag")
            promote_feed(args.tag, args.source_version)
        else:
            if not (args.source_ref and args.source_sha and args.target and args.artifact_directory):
                parser.error("--source-ref, --source-sha, --target, and artifact_directory required for publish")
            publish(args.source_ref, args.source_sha, args.target, args.artifact_directory,
                    args.source_version)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Release publication failed: {error}", file=sys.stderr)
        raise SystemExit(1)
