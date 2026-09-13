#!/usr/bin/env python3
"""Create signed cross-platform metadata and Sparkle appcasts for a release."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SPARKLE_NAMESPACE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ElementTree.register_namespace("sparkle", SPARKLE_NAMESPACE)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_appcast(
    output: Path,
    *,
    version: str,
    tag: str,
    asset_url: str,
    signature: str,
    length: int,
) -> None:
    rss = ElementTree.Element("rss", {"version": "2.0"})
    channel = ElementTree.SubElement(rss, "channel")
    ElementTree.SubElement(channel, "title").text = "EnCap updates"
    ElementTree.SubElement(channel, "link").text = "https://github.com/tlolabs/encap"
    ElementTree.SubElement(channel, "description").text = "EnCap stable releases"
    item = ElementTree.SubElement(channel, "item")
    ElementTree.SubElement(item, "title").text = f"EnCap {version}"
    ElementTree.SubElement(item, "link").text = f"https://github.com/tlolabs/encap/releases/tag/{tag}"
    ElementTree.SubElement(item, f"{{{SPARKLE_NAMESPACE}}}version").text = version
    ElementTree.SubElement(item, f"{{{SPARKLE_NAMESPACE}}}shortVersionString").text = version
    ElementTree.SubElement(item, f"{{{SPARKLE_NAMESPACE}}}minimumSystemVersion").text = "13.0.0"
    ElementTree.SubElement(item, "pubDate").text = format_datetime(datetime.now(timezone.utc))
    ElementTree.SubElement(
        item,
        "enclosure",
        {
            "url": asset_url,
            f"{{{SPARKLE_NAMESPACE}}}edSignature": signature,
            "length": str(length),
            "type": "application/octet-stream",
        },
    )
    ElementTree.indent(rss)
    ElementTree.ElementTree(rss).write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes-file", type=Path)
    args = parser.parse_args()

    if args.tag != f"v{args.version}":
        raise SystemExit(f"Tag {args.tag} must exactly match package version v{args.version}.")
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", args.version) is None:
        raise SystemExit("Release versions must contain 2 to 4 numeric components.")
    seed_value = os.environ.get("ENCAP_UPDATE_PRIVATE_KEY", "").strip()
    public_value = os.environ.get("ENCAP_UPDATE_PUBLIC_KEY", "").strip()
    if not seed_value or not public_value:
        raise SystemExit("ENCAP_UPDATE_PRIVATE_KEY and ENCAP_UPDATE_PUBLIC_KEY are required.")
    seed = base64.b64decode(seed_value, validate=True)
    if len(seed) != 32:
        raise SystemExit("ENCAP_UPDATE_PRIVATE_KEY must be a base64-encoded 32-byte seed.")
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    derived_public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    if base64.b64encode(derived_public).decode("ascii") != public_value:
        raise SystemExit("The configured update private and public keys do not match.")

    base_url = f"https://github.com/tlolabs/encap/releases/download/{args.tag}"
    asset_specs = {
        "macos-intel": (f"EnCap-{args.version}-macos-intel.dmg", "dmg"),
        "macos-arm64": (f"EnCap-{args.version}-macos-arm64.dmg", "dmg"),
        "windows-x64": (f"EnCap-{args.version}-windows-x64.zip", "zip"),
        "windows-arm64": (f"EnCap-{args.version}-windows-arm64.zip", "zip"),
        "linux-x64": (f"EnCap-{args.version}-linux-x64.tar.gz", "tar.gz"),
    }
    notes = ""
    if args.notes_file and args.notes_file.exists():
        notes = args.notes_file.read_text(encoding="utf-8").strip()
    payload = {
        "schema_version": 1,
        "version": args.version,
        "release_url": f"https://github.com/tlolabs/encap/releases/tag/{args.tag}",
        "notes": notes,
        "assets": {},
    }
    for platform_name, (filename, archive_kind) in asset_specs.items():
        asset = args.assets_dir / filename
        if not asset.is_file():
            raise SystemExit(f"Required release asset is missing: {asset}")
        payload["assets"][platform_name] = {
            "url": f"{base_url}/{filename}",
            "sha256": digest(asset),
            "size": asset.stat().st_size,
            "archive": archive_kind,
        }
        if platform_name.startswith("macos-"):
            sparkle_signature = base64.b64encode(
                private_key.sign(asset.read_bytes())
            ).decode("ascii")
            write_appcast(
                args.assets_dir / f"appcast-{platform_name}.xml",
                version=args.version,
                tag=args.tag,
                asset_url=f"{base_url}/{filename}",
                signature=sparkle_signature,
                length=asset.stat().st_size,
            )

    signature = private_key.sign(canonical(payload))
    manifest = {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    (args.assets_dir / "latest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
