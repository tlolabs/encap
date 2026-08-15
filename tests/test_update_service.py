from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from encap.update_service import (
    UpdateError,
    canonical_manifest_payload,
    current_platform_key,
    is_newer_version,
    parse_update_manifest,
    prepare_update,
)

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ModuleNotFoundError:  # pragma: no cover - dependency install is tested in CI
    Ed25519PrivateKey = None


@unittest.skipIf(Ed25519PrivateKey is None, "cryptography is not installed")
class UpdateServiceTest(unittest.TestCase):
    def signed_manifest(self) -> tuple[bytes, str]:
        private_key = Ed25519PrivateKey.generate()
        public_key = base64.b64encode(
            private_key.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        payload = {
            "schema_version": 1,
            "version": "1.2.0",
            "release_url": "https://github.com/tlolabs/encap/releases/tag/v1.2.0",
            "notes": "A secure update",
            "assets": {
                "windows-x64": {
                    "url": "https://github.com/tlolabs/encap/releases/download/v1.2.0/EnCap-1.2.0-windows-x64.zip",
                    "sha256": "a" * 64,
                    "size": 42,
                    "archive": "zip",
                }
            },
        }
        signature = private_key.sign(canonical_manifest_payload(payload))
        document = {
            "payload": payload,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
        return json.dumps(document).encode("utf-8"), public_key

    def test_signed_manifest_selects_exact_platform_asset(self) -> None:
        manifest, public_key = self.signed_manifest()

        release = parse_update_manifest(
            manifest,
            public_key=public_key,
            platform_key="windows-x64",
        )

        self.assertEqual(release.version, "1.2.0")
        self.assertEqual(release.asset.platform, "windows-x64")
        self.assertEqual(release.asset.archive, "zip")

    def test_modified_manifest_is_rejected(self) -> None:
        manifest, public_key = self.signed_manifest()
        document = json.loads(manifest)
        document["payload"]["version"] = "9.9.9"

        with self.assertRaisesRegex(UpdateError, "signature is invalid"):
            parse_update_manifest(
                json.dumps(document),
                public_key=public_key,
                platform_key="windows-x64",
            )

    def test_update_asset_must_stay_in_expected_github_repository(self) -> None:
        manifest, public_key = self.signed_manifest()
        document = json.loads(manifest)
        document["payload"]["assets"]["windows-x64"]["url"] = (
            "https://example.com/fake.zip"
        )
        private_key = Ed25519PrivateKey.generate()
        public_key = base64.b64encode(
            private_key.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        document["signature"] = base64.b64encode(
            private_key.sign(canonical_manifest_payload(document["payload"]))
        ).decode("ascii")

        with self.assertRaisesRegex(UpdateError, "outside the trusted GitHub repository"):
            parse_update_manifest(
                json.dumps(document),
                public_key=public_key,
                platform_key="windows-x64",
            )

    def test_prepare_update_rejects_path_traversal(self) -> None:
        manifest, public_key = self.signed_manifest()
        release = parse_update_manifest(
            manifest,
            public_key=public_key,
            platform_key="windows-x64",
        )
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            target = root / "EnCap"
            target.mkdir()
            (target / ("EnCap.exe" if sys.platform == "win32" else "EnCap")).write_bytes(b"old")
            archive = root / "update.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape", b"bad")

            with self.assertRaisesRegex(UpdateError, "unsafe path"):
                prepare_update(release, archive, target_dir=target)

    def test_version_and_platform_mapping(self) -> None:
        self.assertTrue(is_newer_version("1.10.0", "1.9.9"))
        self.assertFalse(is_newer_version("1.2.0", "1.2.0"))
        self.assertEqual(current_platform_key("Windows", "AMD64"), "windows-x64")
        self.assertEqual(current_platform_key("Darwin", "arm64"), "macos-arm64")
        with self.assertRaisesRegex(UpdateError, "Invalid application version"):
            is_newer_version("../../bad", "1.2.0")

    def test_release_metadata_signs_manifest_and_sparkle_appcasts(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        seed = private_key.private_bytes_raw()
        public_key_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        private_value = base64.b64encode(seed).decode("ascii")
        public_value = base64.b64encode(public_key_bytes).decode("ascii")

        script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_release_metadata.py"
        spec = importlib.util.spec_from_file_location("build_release_metadata", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        metadata_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(metadata_module)

        with tempfile.TemporaryDirectory() as directory_name:
            assets_dir = Path(directory_name)
            filenames = [
                "EnCap-1.2.0-macos-intel.dmg",
                "EnCap-1.2.0-macos-arm64.dmg",
                "EnCap-1.2.0-windows-x64.zip",
                "EnCap-1.2.0-linux-x64.tar.gz",
            ]
            for index, filename in enumerate(filenames):
                (assets_dir / filename).write_bytes(f"asset-{index}".encode("ascii"))

            with patch.dict(
                os.environ,
                {
                    "ENCAP_UPDATE_PRIVATE_KEY": private_value,
                    "ENCAP_UPDATE_PUBLIC_KEY": public_value,
                },
            ), patch.object(
                sys,
                "argv",
                [
                    str(script_path),
                    "--assets-dir",
                    str(assets_dir),
                    "--version",
                    "1.2.0",
                    "--tag",
                    "v1.2.0",
                ],
            ):
                self.assertEqual(metadata_module.main(), 0)

            release = parse_update_manifest(
                (assets_dir / "latest.json").read_bytes(),
                public_key=public_value,
                platform_key="linux-x64",
            )
            self.assertEqual(release.version, "1.2.0")

            appcast = ElementTree.parse(assets_dir / "appcast-macos-arm64.xml")
            enclosure = appcast.find("./channel/item/enclosure")
            self.assertIsNotNone(enclosure)
            signature = enclosure.attrib[
                "{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature"
            ]
            private_key.public_key().verify(
                base64.b64decode(signature),
                (assets_dir / "EnCap-1.2.0-macos-arm64.dmg").read_bytes(),
            )
