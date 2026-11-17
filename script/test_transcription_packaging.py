#!/usr/bin/env python3
"""Offline diagnostics for resource staging and honest qualification results."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qualify_transcription
import stage_avid_transcriber


class StagingTests(unittest.TestCase):
    def setUp(self):
        code = patch.object(stage_avid_transcriber, "code_identity", return_value="c" * 64)
        code.start()
        self.addCleanup(code.stop)
        def relocation(executable, payload):
            (payload/"Frameworks").mkdir()
            return {"libraries": []}
        relocation_patch = patch.object(stage_avid_transcriber,"relocate_module",side_effect=relocation)
        relocation_patch.start();self.addCleanup(relocation_patch.stop)

    def products(self, root, *, catalog=True, metal=True):
        binary = root / "products"
        binary.mkdir()
        (binary / "libEnCAPTranscription.dylib").write_bytes(b"test linked library")
        if catalog:
            resource = binary / "core.bundle"
            resource.mkdir()
            (resource / "models.json").write_bytes(b"shared catalog")
        if metal:
            resource = binary / "mlx.bundle"
            resource.mkdir()
            (resource / "default.metallib").write_bytes(b"compiled Metal")
        return binary

    @patch.object(stage_avid_transcriber.subprocess, "check_output")
    def test_modified_pinned_sdk_source_is_not_treated_as_frozen_resolution(self, check_output):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkouts = root / "checkouts"
            (checkouts / "sdk").mkdir(parents=True)
            resolved = root / "Package.resolved"
            resolved.write_text(json.dumps({"pins": [{"identity": "sdk", "location": "https://example.test/sdk", "state": {"revision": "a" * 40}}]}))
            check_output.side_effect = ["a" * 40 + "\n", " M Sources/Provider.swift\n"]
            destination = root / "licenses"
            with self.assertRaisesRegex(ValueError, "modified or untracked inputs"):
                stage_avid_transcriber.stage_licenses(checkouts, resolved, destination)
            self.assertFalse(destination.exists())

    @patch.object(stage_avid_transcriber.subprocess, "run")
    def test_staging_retains_catalog_metal_and_manifest_without_models(self, run):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "package with spaces/EnCAPTranscription.framework"
            report = stage_avid_transcriber.stage(self.products(root), destination)
            self.assertEqual((destination / "Versions/A/Resources/core.bundle/models.json").read_bytes(), b"shared catalog")
            self.assertEqual((destination / "Versions/A/Resources/mlx.bundle/default.metallib").read_bytes(), b"compiled Metal")
            self.assertFalse(report["model_weights_bundled"])
            self.assertEqual(json.loads((destination.parent / "EnCAPTranscription-metadata/encap-transcription-resources.json").read_text()), report)
            self.assertEqual(run.call_args.args[0][2], "--probe-library")
            self.assertEqual(Path(run.call_args.args[0][3]).name, "EnCAPTranscription")
            self.assertEqual(run.call_args.kwargs["env"]["PATH"], "")

    @patch.object(stage_avid_transcriber.subprocess, "run")
    def test_signature_binding_preserves_source_code_and_rejects_changed_resources(self, _run):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            destination=root/"EnCAPTranscription.framework"
            stage_avid_transcriber.stage(self.products(root),destination)
            library=destination/"Versions/A/EnCAPTranscription"
            library.write_bytes(library.read_bytes()+b"simulated signature")
            signed=stage_avid_transcriber.bind_signature(destination)
            self.assertEqual(signed["files"][library.name]["size"],library.stat().st_size)
            with patch.object(stage_avid_transcriber,"code_identity",return_value="d"*64):
                with self.assertRaisesRegex(ValueError,"code differs"):
                    stage_avid_transcriber.bind_signature(destination)
            (destination/"Versions/A/Resources/core.bundle/models.json").write_bytes(b"changed catalog")
            with self.assertRaisesRegex(ValueError,"resource changed"):
                stage_avid_transcriber.bind_signature(destination)

    @patch.object(stage_avid_transcriber.subprocess, "run")
    def test_stage_does_not_replace_unowned_user_directory(self, _run):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "user models/EnCAPTranscription.framework"
            destination.mkdir(parents=True)
            (destination / "weights.bin").write_bytes(b"user-owned")
            with self.assertRaisesRegex(ValueError, "unowned staging directory"):
                stage_avid_transcriber.stage(self.products(root), destination)
            self.assertEqual((destination / "weights.bin").read_bytes(), b"user-owned")

    def test_missing_metal_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "MLX Metal resources are missing"):
                stage_avid_transcriber.stage(self.products(root, metal=False), root / "EnCAPTranscription.framework")
            self.assertFalse((root / "EnCAPTranscription.framework").exists())

    def test_missing_catalog_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Shared AVID catalog resource is missing"):
                stage_avid_transcriber.stage(self.products(root, catalog=False), root / "EnCAPTranscription.framework")

    @patch.object(qualify_transcription, "command", return_value={"available": False, "reason": "shared-engine port or explicit owner support-policy decision"})
    def test_absent_helper_records_unavailable_without_claiming_inference(self, command):
        with tempfile.TemporaryDirectory() as temporary:
            report = qualify_transcription.qualify(Path(temporary) / "encap-engine", "parakeet-tdt-v3")
            self.assertEqual(report["status"], "unavailable")
            self.assertIn("support-policy decision", report["reason"])
            command.assert_called_once()

    @patch.object(qualify_transcription, "command", side_effect=[{"available": True}, [], [{"id": "parakeet-tdt-v3", "installed": False}]])
    def test_missing_model_is_not_run_and_does_not_acquire_weights(self, command):
        with tempfile.TemporaryDirectory() as temporary:
            engine = Path(temporary) / "encap-engine"
            (engine.parent / "EnCAPTranscription.framework/Versions/A").mkdir(parents=True)
            (engine.parent / "EnCAPTranscription.framework/Versions/A/EnCAPTranscription").write_bytes(b"test linked library")
            report = qualify_transcription.qualify(engine, "parakeet-tdt-v3")
            self.assertEqual(report["status"], "not_run")
            self.assertIn("not installed", report["reason"])
            self.assertEqual([call.args[1] for call in command.call_args_list], ["transcription-status", "providers", "models"])

    @patch.object(qualify_transcription, "command", return_value={"available": True})
    def test_provider_cannot_be_advertised_without_shared_helper(self, _command):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "advertised as available without"):
                qualify_transcription.qualify(Path(temporary) / "encap-engine", "parakeet-tdt-v3")


if __name__ == "__main__":
    unittest.main()
