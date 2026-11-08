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
    def products(self, root, *, catalog=True, metal=True):
        binary = root / "products"
        binary.mkdir()
        (binary / "avid-transcriber").write_bytes(b"test executable")
        if catalog:
            resource = binary / "core.bundle"
            resource.mkdir()
            (resource / "models.json").write_bytes(b"shared catalog")
        if metal:
            resource = binary / "mlx.bundle"
            resource.mkdir()
            (resource / "default.metallib").write_bytes(b"compiled Metal")
        return binary

    @patch.object(stage_avid_transcriber.subprocess, "run")
    def test_staging_retains_catalog_metal_and_manifest_without_models(self, run):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "package with spaces"
            report = stage_avid_transcriber.stage(self.products(root), destination)
            self.assertEqual((destination / "core.bundle/models.json").read_bytes(), b"shared catalog")
            self.assertEqual((destination / "mlx.bundle/default.metallib").read_bytes(), b"compiled Metal")
            self.assertFalse(report["model_weights_bundled"])
            self.assertEqual(json.loads((destination / "avid-transcriber-resources.json").read_text()), report)
            self.assertEqual(Path(run.call_args.args[0][0]).name, "avid-transcriber")
            self.assertEqual(run.call_args.args[0][1], "models")
            self.assertEqual(run.call_args.kwargs["env"]["PATH"], "")

    @patch.object(stage_avid_transcriber.subprocess, "run")
    def test_stage_does_not_replace_unowned_user_directory(self, _run):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "user models"
            destination.mkdir()
            (destination / "weights.bin").write_bytes(b"user-owned")
            with self.assertRaisesRegex(ValueError, "unowned staging directory"):
                stage_avid_transcriber.stage(self.products(root), destination)
            self.assertEqual((destination / "weights.bin").read_bytes(), b"user-owned")

    def test_missing_metal_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "MLX Metal resources are missing"):
                stage_avid_transcriber.stage(self.products(root, metal=False), root / "package")
            self.assertFalse((root / "package").exists())

    def test_missing_catalog_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Shared AVID catalog resource is missing"):
                stage_avid_transcriber.stage(self.products(root, catalog=False), root / "package")

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
            (engine.parent / "avid-transcriber").write_bytes(b"test helper")
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
