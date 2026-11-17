#!/usr/bin/env python3
"""Regression checks for independent, source-bound direct-download releases."""
import json
import hashlib
import io
import plistlib
import tempfile
import tarfile
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
            runtime_files = {"MacOS/avid-transcriber": b"helper", "Resources/core.bundle/models.json": b"catalog", "Resources/mlx.bundle/default.metallib": b"metal"}
            report = dict(schema=1, target=target, status="passed", engine_sha256=hashlib.sha256(b"binary").hexdigest(),
                          runtime_files={name: hashlib.sha256(value).hexdigest() for name, value in runtime_files.items()})
            archive.writestr(base + "Resources/transcription-qualification.json", json.dumps(report))
            for name, value in runtime_files.items():
                archive.writestr(base + name, value)
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

    def linked_mac_package(self, root, *, source_sha=SHA, source_version=VERSION):
        path = root / f'EnCap-{VERSION}-macos-arm64.zip'
        prefix = 'EnCap.app/Contents/'
        manifest = ('[workspace.package]\nversion = "' + source_version + '"\n').encode()
        receipt = {'sdk': {'target': 'macos-arm64'},
                   'source': {'head': source_sha, 'files': {'Cargo.toml': hashlib.sha256(manifest).hexdigest()}}}
        source_bytes = io.BytesIO()
        with tarfile.open(fileobj=source_bytes, mode='w:gz') as sources:
            member = tarfile.TarInfo('Cargo.toml')
            member.size = len(manifest)
            sources.addfile(member, io.BytesIO(manifest))
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(prefix + 'Info.plist', plistlib.dumps({
                'CFBundleIdentifier': 'com.tlolabs.encap', 'CFBundleVersion': VERSION,
                'CFBundleShortVersionString': VERSION}))
            archive.writestr(prefix + 'Resources/update-config.json', json.dumps({
                'application_id': 'com.tlolabs.encap', 'repository': 'tlolabs/encap',
                'version': VERSION, 'channel': 'stable', 'target': 'macos-arm64'}))
            for name in ('EnCap', 'ffmpeg', 'ffprobe'):
                archive.writestr(prefix + 'MacOS/' + name, b'fixture')
            archive.writestr(prefix + 'Frameworks/libencap_app.dylib', b'fixture library')
            archive.writestr(prefix + 'Resources/EnCAPLinked/build-receipt.json', json.dumps(receipt))
            archive.writestr(prefix + 'Resources/EnCAPLinked/corresponding-source/encap-source.tar.gz', source_bytes.getvalue())
        return path

    def test_linked_package_requires_complete_qualification_without_an_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.linked_mac_package(Path(temporary))
            with patch('linked_runtime.verify_stage', side_effect=ValueError('migration is unqualified')) as verify:
                with self.assertRaisesRegex(ValueError, 'migration is unqualified'):
                    publisher.verify_package(package, VERSION, 'macos-arm64')
            self.assertTrue(verify.call_args.args[0].require_qualified)
            with patch('linked_runtime.verify_stage') as verify:
                receipt = publisher.verify_package(package, VERSION, 'macos-arm64')
            self.assertEqual(receipt['source']['head'], SHA)
            self.assertTrue(verify.call_args.args[0].require_qualified)

    def test_linked_source_version_and_commit_are_bound_before_any_release_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.linked_mac_package(root, source_version='0.0.1')
            with patch('linked_runtime.verify_stage'):
                with self.assertRaisesRegex(ValueError, 'version/source identity mismatch'):
                    publisher.verify_package(package, VERSION, 'macos-arm64')
            self.linked_mac_package(root, source_sha='b' * 40)
            with patch('linked_runtime.verify_stage'), patch.object(publisher, 'run') as external:
                with self.assertRaisesRegex(ValueError, 'another verified commit'):
                    publisher.publish(f'refs/tags/v{VERSION}', SHA, 'macos-arm64', root, source_version=VERSION)
            external.assert_not_called()

    def test_duplicate_linked_metadata_is_rejected_before_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.linked_mac_package(Path(temporary))
            with zipfile.ZipFile(package, 'a') as archive:
                archive.writestr('EnCap.app/Contents/Resources/EnCAPLinked/build-receipt.json', '{}')
            with patch('linked_runtime.verify_stage') as verify:
                with self.assertRaisesRegex(ValueError, 'Duplicate or oversized'):
                    publisher.verify_package(package, VERSION, 'macos-arm64')
            verify.assert_not_called()

    def test_linked_transcription_report_binds_versioned_framework_and_swift_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.linked_mac_package(Path(temporary))
            base = 'EnCap.app/Contents/'
            framework = 'Frameworks/EnCAPTranscription.framework/Versions/A/'
            files = {framework + 'EnCAPTranscription': b'framework code',
                     'Resources/EnCAPTranscription/encap-transcription-resources.json': b'build receipt',
                     'Resources/EnCAPTranscription/encap-transcription-signed.json': b'signed binding',
                     framework + 'Resources/AVIDTranscription.bundle/models.json': b'catalog',
                     framework + 'Resources/default.metallib': b'metal',
                     framework + 'Frameworks/libswiftCompatibilitySpan.dylib': b'swift runtime'}
            report = {'schema': 1, 'target': 'macos-arm64', 'status': 'passed',
                      'application_sha256': hashlib.sha256(b'fixture').hexdigest(),
                      'runtime_files': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
            with zipfile.ZipFile(package, 'a') as archive:
                archive.writestr(base + 'Resources/transcription-qualification.json', json.dumps(report))
                for name, value in files.items():
                    archive.writestr(base + name, value)
            publisher.verify_transcription_qualification(package, 'macos-arm64')
            with zipfile.ZipFile(package, 'a') as archive:
                archive.writestr(base + framework + 'Frameworks/libswiftCompatibilitySpan.dylib', b'changed runtime')
            with self.assertRaisesRegex(ValueError, 'runtime resource changed'):
                publisher.verify_transcription_qualification(package, 'macos-arm64')
            with zipfile.ZipFile(package, 'a') as archive:
                archive.writestr(base + framework + 'Frameworks/libswiftCompatibilitySpan.dylib', b'swift runtime')
            publisher.verify_transcription_qualification(package, 'macos-arm64')
            with zipfile.ZipFile(package, 'a') as archive:
                archive.writestr(base + 'Resources/EnCAPTranscription/encap-transcription-signed.json', b'changed binding')
            with self.assertRaisesRegex(ValueError, 'runtime resource changed'):
                publisher.verify_transcription_qualification(package, 'macos-arm64')

    def test_transcription_qualification_is_bound_to_actual_packaged_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.mac_package(Path(temporary))
            publisher.verify_transcription_qualification(package, "macos-arm64")
            with zipfile.ZipFile(package, "a") as archive:
                archive.writestr("EnCap.app/Contents/MacOS/avid-transcriber", b"changed helper")
            with self.assertRaisesRegex(ValueError, "runtime resource changed"):
                publisher.verify_transcription_qualification(package, "macos-arm64")

    def test_unavailable_transcription_does_not_publish_that_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.mac_package(Path(temporary), target="macos-intel")
            with zipfile.ZipFile(package, "a") as archive:
                archive.writestr("EnCap.app/Contents/Resources/transcription-qualification.json",
                                 json.dumps(dict(schema=1, status="unavailable", reason="shared Intel port pending")))
            with self.assertRaisesRegex(ValueError, "not verified.*Intel port pending"):
                publisher.verify_transcription_qualification(package, "macos-intel")
            with self.assertRaisesRegex(ValueError, "Linux shared transcription is unverified"):
                publisher.verify_transcription_qualification(Path(temporary) / "unused.AppImage", "linux-arm64")

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

    @patch.object(publisher, "release_info", return_value={"isPrerelease": False, "assets": []})
    @patch.object(publisher, "run")
    def test_stable_tag_must_match_verified_source(self, run, _release_info):
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(
            {"object": {"type": "commit", "sha": "b" * 40}}))
        with self.assertRaisesRegex(RuntimeError, "does not point to verified source"):
            publisher.ensure_release(f"v{VERSION}", SHA, False)
        self.assertTrue(all(call.args[:2] == ("gh", "api") for call in run.call_args_list))

    @patch.object(publisher, "release_info", return_value={"isPrerelease": False, "assets": []})
    @patch.object(publisher, "run")
    def test_stable_annotated_tag_resolves_to_verified_commit(self, run, _release_info):
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout=json.dumps({"object": {"type": "tag", "sha": "c" * 40}})),
            SimpleNamespace(returncode=0, stdout=json.dumps({"object": {"type": "commit", "sha": SHA}})),
        ]
        publisher.ensure_release(f"v{VERSION}", SHA, False)
        self.assertEqual(run.call_count, 2)
        self.assertIn("git/tags/" + "c" * 40, run.call_args.args[2])

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

