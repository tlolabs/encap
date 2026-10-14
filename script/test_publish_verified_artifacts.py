#!/usr/bin/env python3
"""Regression checks for independent, source-bound direct-download releases."""
import json
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import publish_verified_artifacts as publisher

SHA = "a" * 40
VERSION = "2.0.5"


class PublicationTests(unittest.TestCase):
    def test_main_is_prerelease_and_matching_tag_is_stable(self):
        self.assertEqual(publisher.publication_identity("refs/heads/main", SHA, VERSION),
                         (f"dev-v{VERSION}-{SHA}", True))
        self.assertEqual(publisher.publication_identity("refs/tags/v2.0.5", SHA, VERSION),
                         ("v2.0.5", False))
        for ref in ("refs/heads/feature", "refs/tags/v2.0.4", "refs/pull/1/merge"):
            with self.assertRaises(ValueError):
                publisher.publication_identity(ref, SHA, VERSION)

    def mac_package(self, root, *, target="macos-arm64", bundle_version=VERSION, with_ffmpeg=True):
        path = root / f"EnCap-{VERSION}-{target}.zip"
        base = "EnCap.app/Contents/"
        identity = dict(application_id="com.tlolabs.encap", repository="tlolabs/encap",
                        version=VERSION, channel="stable", target=target, public_key="")
        info = dict(CFBundleIdentifier="com.tlolabs.encap", CFBundleVersion=bundle_version,
                    CFBundleShortVersionString=bundle_version)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(base + "Info.plist", plistlib.dumps(info))
            archive.writestr(base + "Resources/update-config.json", json.dumps(identity))
            for name in ("EnCap", "encap-engine", "ffprobe"):
                archive.writestr(base + "MacOS/" + name, b"binary")
            if with_ffmpeg:
                archive.writestr(base + "MacOS/ffmpeg", b"binary")
        return path

    def test_macos_package_identity_and_completeness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.mac_package(root)
            publisher.verify_package(package, VERSION, "macos-arm64")
            with self.assertRaisesRegex(ValueError, "Expected exactly"):
                publisher.verify_package(package, VERSION, "macos-intel")
            package = self.mac_package(root, bundle_version="2.0.4")
            with self.assertRaisesRegex(ValueError, "wrong macOS identity"):
                publisher.verify_package(package, VERSION, "macos-arm64")
            package = self.mac_package(root, with_ffmpeg=False)
            with self.assertRaisesRegex(ValueError, "incomplete macOS"):
                publisher.verify_package(package, VERSION, "macos-arm64")

    def test_linux_requires_type_two_appimage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / f"EnCap-{VERSION}-linux-arm64.AppImage"
            path.write_bytes(b"\x7fELF" + b"\0" * 4 + b"AI\x02")
            publisher.verify_package(path, VERSION, "linux-arm64")
            path.write_bytes(b"\x7fELF" + b"\0" * 7)
            with self.assertRaisesRegex(ValueError, "type 2 AppImage"):
                publisher.verify_package(path, VERSION, "linux-arm64")

    @patch.object(publisher, "release_info", return_value={"isPrerelease": True, "assets": []})
    @patch.object(publisher, "run")
    def test_stable_release_cannot_use_prerelease(self, run, _release_info):
        with self.assertRaisesRegex(RuntimeError, "wrong channel"):
            publisher.ensure_release("v2.0.5", SHA, False)
        run.assert_not_called()

    @patch.object(publisher, "release_info", return_value={"isPrerelease": True, "assets": []})
    @patch.object(publisher, "run")
    def test_draft_development_release_creates_source_tag_first(self, run, _release_info):
        run.side_effect = [SimpleNamespace(returncode=1, stdout=""),
                           SimpleNamespace(returncode=0, stdout=""),
                           SimpleNamespace(returncode=0, stdout=json.dumps({"object": {"sha": SHA}})),
                           SimpleNamespace(returncode=0, stdout=json.dumps({"object": {"sha": SHA}}))]
        tag = f"dev-v{VERSION}-{SHA}"
        publisher.ensure_release(tag, SHA, True)
        self.assertEqual(run.call_args_list[1].args[:4],
                         ("gh", "api", "-X", "POST"))
        self.assertIn(f"ref=refs/tags/{tag}", run.call_args_list[1].args)
        self.assertIn(f"sha={SHA}", run.call_args_list[1].args)

    @patch.object(publisher, "same_remote_asset", return_value=False)
    def test_existing_asset_cannot_be_replaced(self, _same_remote):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package.zip"
            package.write_bytes(b"good bytes")
            with self.assertRaisesRegex(RuntimeError, "Refusing to replace"):
                publisher.upload_verified("v2.0.5", package, {package.name})

    @patch.object(publisher, "verify_authenticated_feed", return_value=False)
    @patch.object(publisher, "upload_verified")
    @patch.object(publisher, "ensure_release")
    @patch.object(publisher, "run")
    def test_feedless_stable_publication_keeps_latest_false(self, run, ensure_release, _upload, _verify_feed):
        ensure_release.return_value = {"isPrerelease": False, "assets": []}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.mac_package(root)
            publisher.publish(f"refs/tags/v{VERSION}", SHA, "macos-arm64", root, source_version=VERSION)
            edit_calls = [call for call in run.call_args_list if call.args[:3] == ("gh", "release", "edit")]
            self.assertEqual(len(edit_calls), 1)
            self.assertIn("--latest=false", edit_calls[0].args)

    @patch.object(publisher, "verify_authenticated_feed", return_value=True)
    @patch.object(publisher, "upload_verified")
    @patch.object(publisher, "ensure_release")
    @patch.object(publisher, "run")
    def test_authenticated_feed_publication_promotes_latest(self, run, ensure_release, _upload, _verify_feed):
        ensure_release.return_value = {"isPrerelease": False, "assets": []}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.mac_package(root)
            publisher.publish(f"refs/tags/v{VERSION}", SHA, "macos-arm64", root, source_version=VERSION)
            edit_calls = [call for call in run.call_args_list if call.args[:3] == ("gh", "release", "edit")]
            self.assertEqual(len(edit_calls), 1)
            self.assertIn("--latest=true", edit_calls[0].args)

    @patch.object(publisher, "verify_authenticated_feed", return_value=False)
    @patch.object(publisher, "release_info", return_value={"isPrerelease": False, "assets": []})
    @patch.object(publisher, "run")
    def test_invalid_feed_promotion_fails_closed(self, run, _release_info, _verify_feed):
        with self.assertRaisesRegex(RuntimeError, "does not satisfy authenticated update feed"):
            publisher.promote_feed(f"v{VERSION}")
        run.assert_not_called()

    @patch.object(publisher, "verify_authenticated_feed", return_value=True)
    @patch.object(publisher, "release_info", return_value={"isPrerelease": False, "assets": []})
    @patch.object(publisher, "run")
    def test_valid_feed_promotion_sets_latest(self, run, _release_info, _verify_feed):
        publisher.promote_feed(f"v{VERSION}")
        run.assert_called_once_with("gh", "release", "edit", f"v{VERSION}", "--repo", publisher.REPOSITORY,
                                    "--draft=false", "--latest=true")


if __name__ == "__main__":
    unittest.main()

