#!/usr/bin/env python3
"""Offline checks for the real transcription catalog and its generator."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name("update_transcription_catalog.py")
spec = importlib.util.spec_from_file_location("transcription_catalog", SOURCE)
catalog_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog_module)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(catalog_module.DEFAULT_OUTPUT.read_text())

    def test_committed_manifest_has_every_runtime_component(self):
        catalog_module.validate_catalog(self.catalog)
        self.assertEqual(len(self.catalog["models"]), 5)
        for model in self.catalog["models"]:
            self.assertGreater(sum(file["sizeBytes"] for file in model["artifacts"]), 500_000_000)
        qwen = next(model for model in self.catalog["models"] if model["id"].startswith("qwen3-asr"))
        aligner = next(model for model in self.catalog["models"] if model["role"] == "aligner")
        self.assertEqual(len(qwen["recognitionLanguages"]), 30)
        self.assertEqual(len(aligner["timingLanguages"]), 11)
        self.assertEqual(qwen["timingLanguages"], [])

    def test_rejects_missing_offline_tokenizer(self):
        model = self.catalog["models"][0]
        model["artifacts"] = [file for file in model["artifacts"] if file["path"] != "tokenizer/tokenizer.json"]
        with self.assertRaisesRegex(ValueError, "Missing required"):
            catalog_module.validate_catalog(self.catalog)

    def test_rejects_unpinned_auxiliary_download(self):
        model = self.catalog["models"][0]
        artifact = next(file for file in model["artifacts"] if "repository" in file)
        artifact["revision"] = "main"
        with self.assertRaisesRegex(ValueError, "Unpinned auxiliary"):
            catalog_module.validate_catalog(self.catalog)

    def test_rejects_traversal_duplicate_hash_and_size_errors(self):
        mutations = [
            lambda file: file.update(path="../config.json"),
            lambda file: file.update(path="tokenizer/../config.json"),
            lambda file: file.update(path="config.json?download=true"),
            lambda file: file.update(sha256="a" * 63),
            lambda file: file.update(sizeBytes=-1),
            lambda file: file.update(sizeBytes=True),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(self.catalog)
            mutate(changed["models"][0]["artifacts"][0])
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                catalog_module.validate_catalog(changed)
        self.catalog["models"][0]["artifacts"].append(self.catalog["models"][0]["artifacts"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate/unsafe"):
            catalog_module.validate_catalog(self.catalog)

    def test_small_file_hash_is_bound_to_git_blob(self):
        payload = b'{"test":true}\n'
        record = {
            "rfilename": "config.json",
            "size": len(payload),
            "blobId": hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest(),
        }
        repo = "mlx-community/Qwen3-ASR-1.7B-4bit"
        with patch.object(catalog_module, "read_url", return_value=payload):
            artifact = catalog_module.artifact_for(repo, record, "config.json", repo)
        self.assertEqual(artifact["sha256"], hashlib.sha256(payload).hexdigest())
        with patch.object(catalog_module, "read_url", return_value=b'{"test":fals}\n'):
            with self.assertRaisesRegex(ValueError, "Git blob mismatch"):
                catalog_module.artifact_for(repo, record, "config.json", repo)

    def test_lfs_hash_requires_matching_size(self):
        repo = "mlx-community/Qwen3-ASR-1.7B-4bit"
        record = {"rfilename": "model.safetensors", "size": 100, "lfs": {"size": 99, "sha256": "a" * 64}}
        with self.assertRaisesRegex(ValueError, "Invalid LFS"):
            catalog_module.artifact_for(repo, record, record["rfilename"], repo)

    def test_private_or_gated_sources_cannot_enter_catalog(self):
        repo = "mlx-community/Qwen3-ASR-1.7B-4bit"
        for metadata in [
            {"sha": catalog_module.SOURCES[repo], "private": True, "gated": False},
            {"sha": catalog_module.SOURCES[repo], "private": False, "gated": "auto"},
            {"sha": "main", "private": False, "gated": False},
        ]:
            with self.subTest(metadata=metadata), patch.object(catalog_module, "read_url", return_value=json.dumps(metadata).encode()):
                with self.assertRaisesRegex(ValueError, "public, ungated"):
                    catalog_module.load_metadata(repo)


if __name__ == "__main__":
    unittest.main()
