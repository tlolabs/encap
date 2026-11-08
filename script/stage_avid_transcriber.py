#!/usr/bin/env python3
"""Stage a built AVID adapter with all SwiftPM resources; never download weights."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile


def stage_licenses(checkouts: Path, resolved: Path, destination: Path):
    pins = json.loads(resolved.read_text())["pins"]
    checkouts_by_name = {path.name.lower(): path for path in checkouts.iterdir() if path.is_dir()}
    records = []
    for pin in pins:
        identity = pin["identity"]
        checkout = checkouts_by_name.get(identity.lower())
        if checkout is None:
            raise ValueError("Missing pinned SDK checkout for license staging: " + identity)
        revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        if revision != pin["state"]["revision"]:
            raise ValueError("SDK checkout revision differs from frozen resolution: " + identity)
        licenses = []
        for path in sorted(checkout.rglob("*")):
            relative = path.relative_to(checkout)
            if not path.is_file() or any(part.startswith(".") for part in relative.parts):
                continue
            if not re.search(r"license|licence|notice|^copying", path.name, re.IGNORECASE):
                continue
            if path.name in ("license_header_template", "licenseignore") or path.suffix in (".py", ".swift", ".sh"):
                continue
            target = destination / identity / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            licenses.append({"path": (Path(identity) / relative).as_posix(),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if not licenses:
            raise ValueError("No license text found for resolved SDK: " + identity)
        records.append({"identity": identity, "repository": pin["location"], "revision": revision, "files": licenses})
    (destination / "resolved-sdk-licenses.json").write_text(json.dumps({"schema": 1, "dependencies": records}, indent=2) + "\n")
    return records


def stage(binary_directory: Path, destination: Path, checkouts=None, resolved=None):
    binary_directory = binary_directory.resolve(strict=True)
    destination = destination.resolve()
    helper = binary_directory / "avid-transcriber"
    if not helper.is_file():
        raise ValueError("Built avid-transcriber is missing")
    resources = sorted(binary_directory.glob("*.bundle"))
    models = [p for bundle in resources for p in bundle.rglob("models.json")]
    metal = [p for bundle in resources for p in bundle.rglob("*.metallib")]
    if not models:
        raise ValueError("Shared AVID catalog resource is missing; do not ship this helper")
    if not metal:
        raise ValueError("MLX Metal resources are missing; use the swiftbuild build system")
    # Never overwrite a non-owned source/model folder supplied by accident.
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and any(destination.iterdir()):
        marker = destination / "avid-transcriber-resources.json"
        if not marker.is_file() or json.loads(marker.read_text()).get("scope") != "avid_transcription_staging":
            raise ValueError("Refusing to replace an unowned staging directory")
    owned = tempfile.TemporaryDirectory(prefix=".encap-avid-stage-", dir=destination.parent)
    final_destination = destination
    destination = Path(owned.name) / "runtime"
    # Build products are copied, never symlinked to a mutable checkout/build tree.
    destination.mkdir()
    shutil.copy2(helper, destination / helper.name)
    for resource in resources:
        shutil.copytree(resource, destination / resource.name, dirs_exist_ok=True)
    if checkouts is not None and resolved is not None:
        stage_licenses(checkouts, resolved, destination / "AVIDTranscriptionLicenses")
    for dylib in binary_directory.glob("*.dylib"):
        shutil.copy2(dylib, destination / dylib.name)
    files = [p for p in destination.rglob("*") if p.is_file()]
    report = {"schema": 1, "scope": "avid_transcription_staging", "platform": "macos-arm64",
              "minimum_macos": "14.0", "model_weights_bundled": False,
              "snapshot_sha256": "a302200860bde5c47cd4aeabacefedefa30e6112248302925164589ce9f45937",
              "files": [{"path": p.relative_to(destination).as_posix(),
                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "size": p.stat().st_size}
                        for p in sorted(files)]}
    (destination / "avid-transcriber-resources.json").write_text(json.dumps(report, indent=2) + "\n")
    # Relocation test: run the staged binary with an empty PATH. Inference is a
    # separate qualification step and cannot be inferred from successful listing.
    subprocess.run([str(destination / helper.name), "models"], check=True,
                   stdout=subprocess.DEVNULL, env={"PATH": "", "HOME": str(Path.home())})
    if final_destination.exists():
        final_destination.rename(Path(owned.name) / "previous-runtime")
    destination.rename(final_destination)
    owned.cleanup()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-directory", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    args = parser.parse_args()
    stage(args.binary_directory, args.destination, args.checkouts, args.resolved)
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
