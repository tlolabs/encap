from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import encap.transcription_models as transcription_models
from encap.models import AudioSourceEntry, TranscriptSegment
from encap.transcription_models import (
    SUPERWHISPER_MODEL_FILENAME,
    SUPERWHISPER_MODEL_SIZE,
    SUPERWHISPER_PROVIDER_ID,
    WHISPER_CPP_ENGINE,
    WHISPERKIT_ENGINE,
    ModelDownloadError,
    TranscriptionModelStore,
    TranscriptionProvider,
    WHISPER_MODELS,
    discover_shared_transcription_providers,
)
from encap.transcription_service import (
    APPLE_PROVIDER_ID,
    _transcribe_with_whisperkit,
    _verify_shared_model,
    parse_apple_result,
    parse_whisper_result,
    parse_whisperkit_result,
    transcribe_audio_sources,
)
from encap.wav_tools import EncapError


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._stream = BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def make_application(applications: Path, name: str, bundle_id: str) -> None:
    contents = applications / name / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as info_file:
        plistlib.dump({"CFBundleIdentifier": bundle_id}, info_file)


def make_macwhisper_model(
    home: Path,
    folder_name: str = "openai_whisper-large-v3-v20240930_626MB",
    *,
    sandboxed: bool = True,
) -> tuple[Path, Path]:
    if sandboxed:
        models_root = (
            home
            / "Library"
            / "Containers"
            / "com.goodsnooze.MacWhisper"
            / "Data"
            / "Library"
            / "Application Support"
            / "MacWhisper"
            / "models"
            / "whisperkit"
            / "models"
        )
    else:
        models_root = (
            home
            / "Library"
            / "Application Support"
            / "MacWhisper"
            / "models"
            / "whisperkit"
            / "models"
        )
    model_path = models_root / "argmaxinc" / "whisperkit-coreml" / folder_name
    model_path.mkdir(parents=True)
    model_config = {
        "model_type": "whisper",
        "d_model": 1280,
        "decoder_start_token_id": 50258,
    }
    generation_config = {
        "lang_to_id": {"<|en|>": 50259},
        "task_to_id": {"transcribe": 50359},
        "no_timestamps_token_id": 50364,
    }
    (model_path / "config.json").write_text(
        json.dumps(model_config),
        encoding="utf-8",
    )
    (model_path / "generation_config.json").write_text(
        json.dumps(generation_config),
        encoding="utf-8",
    )
    for component in ("AudioEncoder", "MelSpectrogram", "TextDecoder"):
        component_path = model_path / f"{component}.mlmodelc"
        component_path.mkdir()
        (component_path / "model.mil").write_text("model", encoding="utf-8")
        (component_path / "coremldata.bin").write_bytes(b"coreml")
        (component_path / "metadata.json").write_text("{}", encoding="utf-8")
        weights_path = component_path / "weights"
        weights_path.mkdir()
        (weights_path / "weight.bin").write_bytes(b"weights")
    tokenizer_path = models_root / "openai" / "whisper-large-v3"
    tokenizer_path.mkdir(parents=True, exist_ok=True)
    (tokenizer_path / "tokenizer.json").write_text(
        json.dumps(
            {
                "model": {
                    "type": "BPE",
                    "vocab": {"a": 0, "b": 1},
                    "merges": ["a b"],
                },
                "added_tokens": [],
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    (tokenizer_path / "tokenizer_config.json").write_text(
        json.dumps({"tokenizer_class": "WhisperTokenizer", "added_tokens_decoder": {}}),
        encoding="utf-8",
    )
    (tokenizer_path / "config.json").write_text(
        json.dumps(model_config),
        encoding="utf-8",
    )
    return model_path, tokenizer_path


class TranscriptionModelStoreTest(unittest.TestCase):
    def test_download_verifies_and_selects_model_without_bundling_it(self) -> None:
        payload = b"small test model"
        model = replace(
            WHISPER_MODELS[0],
            filename="test-model.bin",
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        progress: list[tuple[int, int | None]] = []
        with tempfile.TemporaryDirectory() as directory_name:
            store = TranscriptionModelStore(Path(directory_name))
            destination = store.download(
                model,
                progress=lambda current, total: progress.append((current, total)),
                opener=lambda *_args, **_kwargs: FakeResponse(payload),
            )

            self.assertEqual(destination.read_bytes(), payload)
            self.assertTrue(store.is_installed(model))
            self.assertEqual(progress[-1], (len(payload), len(payload)))

            with patch("encap.transcription_models.MODEL_BY_ID", {model.model_id: model}):
                store.set_selected_model(model.model_id)
                self.assertEqual(store.selected_model_id(), model.model_id)
                store.remove(model)
                self.assertFalse(destination.exists())
                self.assertIsNone(store.selected_model_id())

    def test_download_rejects_invalid_sha256_and_removes_partial_file(self) -> None:
        model = replace(
            WHISPER_MODELS[0],
            filename="bad-model.bin",
            sha256="0" * 64,
        )
        with tempfile.TemporaryDirectory() as directory_name:
            store = TranscriptionModelStore(Path(directory_name))
            with self.assertRaisesRegex(ModelDownloadError, "SHA-256"):
                store.download(
                    model,
                    opener=lambda *_args, **_kwargs: FakeResponse(b"not the expected model"),
                )
            self.assertFalse(store.model_path(model).exists())
            self.assertFalse(store.model_path(model).with_suffix(".bin.part").exists())

    def test_download_replaces_a_corrupt_preexisting_model(self) -> None:
        payload = b"replacement model"
        model = replace(
            WHISPER_MODELS[0],
            filename="replacement-model.bin",
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory_name:
            store = TranscriptionModelStore(Path(directory_name))
            destination = store.model_path(model)
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"corrupt model")

            result = store.download(
                model,
                opener=lambda *_args, **_kwargs: FakeResponse(payload),
            )

            self.assertEqual(result.read_bytes(), payload)

    def test_selected_managed_model_is_the_first_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            store = TranscriptionModelStore(
                Path(directory_name),
                platform_name="linux",
            )
            for model in (WHISPER_MODELS[0], WHISPER_MODELS[2]):
                path = store.model_path(model)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"installed")
            store.set_selected_model(WHISPER_MODELS[2].model_id)

            providers = store.available_providers()

            self.assertEqual(providers[0].provider_id, WHISPER_MODELS[2].model_id)

    def test_corrupt_selection_state_does_not_hide_managed_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            store = TranscriptionModelStore(
                Path(directory_name),
                platform_name="linux",
            )
            model = WHISPER_MODELS[0]
            model_path = store.model_path(model)
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"installed")

            for payload in (b"[]", b"null", b"\xffinvalid"):
                with self.subTest(payload=payload):
                    store.state_path.write_bytes(payload)
                    self.assertIsNone(store.selected_model_id())
                    self.assertEqual(
                        store.available_providers()[0].provider_id,
                        model.model_id,
                    )


class SharedTranscriptionProviderTest(unittest.TestCase):
    def test_app_detection_uses_bundle_ids_for_renamed_and_nested_apps(self) -> None:
        cases = (
            ("Renamed Recorder.app", "com.superduper.superwhisper", True),
            ("Setapp/Renamed Recorder.app", "com.superduper.superwhisper", True),
            ("superwhisper.app", "example.wrong.bundle", False),
        )
        for app_name, bundle_id, expected in cases:
            with self.subTest(app_name=app_name, bundle_id=bundle_id):
                with tempfile.TemporaryDirectory() as directory_name:
                    root = Path(directory_name)
                    home = root / "home"
                    applications = root / "Applications"
                    make_application(applications, app_name, bundle_id)
                    super_model = (
                        home
                        / "Library"
                        / "Application Support"
                        / "superwhisper"
                        / SUPERWHISPER_MODEL_FILENAME
                    )
                    super_model.parent.mkdir(parents=True)
                    super_model.write_bytes(b"model")

                    with patch(
                        "encap.transcription_models.SUPERWHISPER_MODEL_SIZE",
                        len(b"model"),
                    ):
                        providers = discover_shared_transcription_providers(
                            home=home,
                            application_dirs=(applications,),
                            whisperkit_available=False,
                            platform_name="darwin",
                            machine="arm64",
                            macos_version="14.0",
                        )

                    self.assertEqual(bool(providers), expected)

    def test_unrelated_app_with_non_object_plist_does_not_break_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(applications, "A Broken.app", "unused")
            broken_plist = applications / "A Broken.app" / "Contents" / "Info.plist"
            with broken_plist.open("wb") as info_file:
                plistlib.dump(["not", "a", "dictionary"], info_file)
            make_application(
                applications,
                "Z Renamed Recorder.app",
                "com.superduper.superwhisper",
            )
            super_model = (
                home
                / "Library"
                / "Application Support"
                / "superwhisper"
                / SUPERWHISPER_MODEL_FILENAME
            )
            super_model.parent.mkdir(parents=True)
            super_model.write_bytes(b"model")

            with patch(
                "encap.transcription_models.SUPERWHISPER_MODEL_SIZE",
                len(b"model"),
            ):
                providers = discover_shared_transcription_providers(
                    home=home,
                    application_dirs=(applications,),
                    whisperkit_available=False,
                    platform_name="darwin",
                    machine="arm64",
                    macos_version="14.0",
                )

            self.assertEqual(providers[0].provider_id, SUPERWHISPER_PROVIDER_ID)

    def test_superwhisper_takes_priority_over_macwhisper_and_managed_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "superwhisper.app",
                "com.superduper.superwhisper",
            )
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            make_macwhisper_model(home)
            super_model = (
                home
                / "Library"
                / "Application Support"
                / "superwhisper"
                / SUPERWHISPER_MODEL_FILENAME
            )
            super_model.parent.mkdir(parents=True)
            super_model.write_bytes(b"model")
            store = TranscriptionModelStore(
                root / "encap-models",
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )
            managed_path = store.model_path(WHISPER_MODELS[0])
            managed_path.parent.mkdir(parents=True)
            managed_path.write_bytes(b"managed")

            with patch(
                "encap.transcription_models.SUPERWHISPER_MODEL_SIZE",
                len(b"model"),
            ), patch(
                "encap.transcription_models.SUPERWHISPER_MODEL_SHA256",
                hashlib.sha256(b"model").hexdigest(),
            ):
                providers = store.available_providers()

            self.assertEqual([provider.provider_id for provider in providers], [SUPERWHISPER_PROVIDER_ID])
            self.assertEqual(providers[0].model_path, super_model)

    def test_runtime_failures_advance_through_shared_sources_then_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "superwhisper.app",
                "com.superduper.superwhisper",
            )
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            make_macwhisper_model(home)
            super_model = (
                home
                / "Library"
                / "Application Support"
                / "superwhisper"
                / SUPERWHISPER_MODEL_FILENAME
            )
            super_model.parent.mkdir(parents=True)
            super_model.write_bytes(b"model")
            store = TranscriptionModelStore(
                root / "encap-models",
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )
            managed_model = WHISPER_MODELS[0]
            managed_path = store.model_path(managed_model)
            managed_path.parent.mkdir(parents=True)
            managed_path.write_bytes(b"managed")

            with patch(
                "encap.transcription_models.SUPERWHISPER_MODEL_SIZE",
                len(b"model"),
            ):
                self.assertEqual(
                    store.available_providers()[0].provider_id,
                    SUPERWHISPER_PROVIDER_ID,
                )
                store.mark_provider_runtime_unusable(SUPERWHISPER_PROVIDER_ID)
                macwhisper_provider = store.available_providers()[0]
                self.assertEqual(
                    macwhisper_provider.provider_id,
                    "macwhisper-large-v3-turbo-compressed",
                )
                store.mark_provider_runtime_unusable(macwhisper_provider.provider_id)
                self.assertEqual(
                    store.available_providers()[0].provider_id,
                    managed_model.model_id,
                )

    def test_corrupt_superwhisper_model_falls_through_to_macwhisper(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "superwhisper.app",
                "com.superduper.superwhisper",
            )
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            make_macwhisper_model(home)
            super_model = (
                home
                / "Library"
                / "Application Support"
                / "superwhisper"
                / SUPERWHISPER_MODEL_FILENAME
            )
            super_model.parent.mkdir(parents=True)
            super_model.write_bytes(b"corrupt")
            store = TranscriptionModelStore(
                root / "encap-models",
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )

            with patch(
                "encap.transcription_models.SUPERWHISPER_MODEL_SIZE",
                len(b"corrupt"),
            ), patch(
                "encap.transcription_models.SUPERWHISPER_MODEL_SHA256",
                "0" * 64,
            ):
                unverified_providers = store.available_providers()
                providers = store.available_providers(verify_integrity=True)
                transcription_models._invalid_shared_models.clear()
                fresh_store = TranscriptionModelStore(
                    store.root,
                    home=home,
                    application_dirs=(applications,),
                    whisperkit_available=True,
                    platform_name="darwin",
                    machine="arm64",
                    macos_version="14.0",
                )
                with patch(
                    "encap.transcription_models.hashlib.sha256",
                    wraps=hashlib.sha256,
                ) as hasher:
                    fresh_providers = fresh_store.available_providers(verify_integrity=True)

            self.assertEqual(
                [provider.provider_id for provider in unverified_providers],
                [SUPERWHISPER_PROVIDER_ID],
            )
            self.assertEqual(
                [provider.provider_id for provider in providers],
                ["macwhisper-large-v3-turbo-compressed"],
            )
            self.assertEqual(
                [provider.provider_id for provider in fresh_providers],
                ["macwhisper-large-v3-turbo-compressed"],
            )
            self.assertEqual(hasher.call_count, 0)
            cache = json.loads(
                (store.root / "shared-model-verification.json").read_text(encoding="utf-8")
            )
            self.assertFalse(cache["providers"][SUPERWHISPER_PROVIDER_ID]["valid"])

    def test_superwhisper_remains_available_on_intel_macos(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "superwhisper.app",
                "com.superduper.superwhisper",
            )
            super_model = (
                home
                / "Library"
                / "Application Support"
                / "superwhisper"
                / SUPERWHISPER_MODEL_FILENAME
            )
            super_model.parent.mkdir(parents=True)
            super_model.write_bytes(b"model")

            with patch("encap.transcription_models.SUPERWHISPER_MODEL_SIZE", len(b"model")):
                providers = discover_shared_transcription_providers(
                    home=home,
                    application_dirs=(applications,),
                    whisperkit_available=False,
                    platform_name="darwin",
                    machine="x86_64",
                    macos_version="13.0",
                )

            self.assertEqual([provider.provider_id for provider in providers], [SUPERWHISPER_PROVIDER_ID])

    def test_missing_superwhisper_model_falls_through_to_macwhisper_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "superwhisper.app",
                "com.superduper.superwhisper",
            )
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            compact_path, tokenizer_path = make_macwhisper_model(home)
            make_macwhisper_model(home, "openai_whisper-large-v3")

            providers = discover_shared_transcription_providers(
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )

            self.assertEqual(
                [provider.provider_id for provider in providers],
                ["macwhisper-large-v3-turbo-compressed", "macwhisper-large-v3"],
            )
            self.assertEqual(providers[0].model_path, compact_path)
            self.assertEqual(providers[0].tokenizer_path, tokenizer_path)

    def test_macwhisper_model_priority_spans_sandboxed_and_regular_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            full_path, _ = make_macwhisper_model(home, "openai_whisper-large-v3")
            compact_path, _ = make_macwhisper_model(home, sandboxed=False)

            providers = discover_shared_transcription_providers(
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )

            self.assertEqual(
                [provider.provider_id for provider in providers],
                ["macwhisper-large-v3-turbo-compressed", "macwhisper-large-v3"],
            )
            self.assertEqual(providers[0].model_path, compact_path)
            self.assertEqual(providers[1].model_path, full_path)

    def test_orphan_files_and_incomplete_macwhisper_models_fall_back_to_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            model_path, _tokenizer_path = make_macwhisper_model(home)
            (model_path / "TextDecoder.mlmodelc" / "weights" / "weight.bin").unlink()
            orphan_super = (
                home
                / "Library"
                / "Application Support"
                / "superwhisper"
                / SUPERWHISPER_MODEL_FILENAME
            )
            orphan_super.parent.mkdir(parents=True)
            orphan_super.write_bytes(b"orphan")
            store = TranscriptionModelStore(
                root / "encap-models",
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )
            managed_path = store.model_path(WHISPER_MODELS[1])
            managed_path.parent.mkdir(parents=True)
            managed_path.write_bytes(b"managed")

            providers = store.available_providers()

            self.assertEqual([provider.provider_id for provider in providers], [WHISPER_MODELS[1].model_id])

    def test_macwhisper_requires_supported_macos_14_and_helper(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            make_macwhisper_model(home)

            cases = (
                ("x86_64", "14.0", True),
                ("arm64", "13.6", True),
                ("arm64", "14.0", False),
                ("powerpc", "14.0", True),
            )
            for machine, version, helper_available in cases:
                with self.subTest(machine=machine, version=version, helper=helper_available):
                    providers = discover_shared_transcription_providers(
                        home=home,
                        application_dirs=(applications,),
                        whisperkit_available=helper_available,
                        platform_name="darwin",
                        machine=machine,
                        macos_version=version,
                    )
                    self.assertEqual(providers, ())

    def test_incomplete_macwhisper_tokenizer_falls_back_to_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            home = root / "home"
            applications = root / "Applications"
            make_application(
                applications,
                "Whisper Transcription.app",
                "com.goodsnooze.MacWhisper",
            )
            _model_path, tokenizer_path = make_macwhisper_model(home)
            (tokenizer_path / "tokenizer_config.json").write_text("{}", encoding="utf-8")
            store = TranscriptionModelStore(
                root / "encap-models",
                home=home,
                application_dirs=(applications,),
                whisperkit_available=True,
                platform_name="darwin",
                machine="arm64",
                macos_version="14.0",
            )
            managed_path = store.model_path(WHISPER_MODELS[0])
            managed_path.parent.mkdir(parents=True)
            managed_path.write_bytes(b"managed")

            providers = store.available_providers()

            self.assertEqual([provider.provider_id for provider in providers], [WHISPER_MODELS[0].model_id])

    def test_shared_model_sha256_is_verified_once_per_file_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            model_path = Path(directory_name) / "model.bin"
            payload = b"verified model"
            model_path.write_bytes(payload)
            provider = TranscriptionProvider(
                provider_id="shared-test",
                name="Shared Test",
                engine=WHISPER_CPP_ENGINE,
                source_name="Test App",
                model_path=model_path,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            with patch("encap.transcription_models.hashlib.sha256", wraps=hashlib.sha256) as hasher:
                _verify_shared_model(provider)
                _verify_shared_model(provider)
            self.assertEqual(hasher.call_count, 1)

            invalid_provider = replace(provider, sha256="0" * 64)
            with self.assertRaisesRegex(EncapError, "SHA-256"):
                _verify_shared_model(invalid_provider)

    def test_persistent_verification_cache_avoids_rehash_and_invalidates_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            model_path = root / "model.bin"
            cache_path = root / "verification.json"
            initial_payload = b"initial verified model"
            model_path.write_bytes(initial_payload)
            provider = TranscriptionProvider(
                provider_id="persistent-shared-test",
                name="Persistent Shared Test",
                engine=WHISPER_CPP_ENGINE,
                source_name="Test App",
                model_path=model_path,
                sha256=hashlib.sha256(initial_payload).hexdigest(),
            )
            transcription_models.verify_shared_model(provider, cache_path=cache_path)
            transcription_models._verified_shared_models.clear()

            with patch(
                "encap.transcription_models.hashlib.sha256",
                wraps=hashlib.sha256,
            ) as cached_hasher:
                self.assertTrue(
                    transcription_models.cached_shared_model_validity(
                        provider,
                        cache_path=cache_path,
                    )
                )
                _verify_shared_model(provider)

            self.assertEqual(cached_hasher.call_count, 0)

            changed_payload = b"changed model with a different identity"
            model_path.write_bytes(changed_payload)
            changed_provider = replace(
                provider,
                sha256=hashlib.sha256(changed_payload).hexdigest(),
            )
            transcription_models._verified_shared_models.clear()
            with patch(
                "encap.transcription_models.hashlib.sha256",
                wraps=hashlib.sha256,
            ) as changed_hasher:
                transcription_models.verify_shared_model(
                    changed_provider,
                    cache_path=cache_path,
                )

            self.assertEqual(changed_hasher.call_count, 1)

    def test_corrupt_verification_cache_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            model_path = root / "model.bin"
            cache_path = root / "verification.json"
            payload = b"verified model"
            model_path.write_bytes(payload)
            cache_path.write_bytes(b"\xff\xfeinvalid cache")
            provider = TranscriptionProvider(
                provider_id="corrupt-cache-test",
                name="Corrupt Cache Test",
                engine=WHISPER_CPP_ENGINE,
                source_name="Test App",
                model_path=model_path,
                sha256=hashlib.sha256(payload).hexdigest(),
            )

            transcription_models.verify_shared_model(provider, cache_path=cache_path)

            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertTrue(cache["providers"][provider.provider_id]["valid"])


class TranscriptionResultTest(unittest.TestCase):
    def test_whisper_json_offsets_are_preserved(self) -> None:
        payload = json.dumps(
            {
                "transcription": [
                    {
                        "offsets": {"from": 1250, "to": 2750},
                        "text": " Hello world ",
                    }
                ]
            }
        ).encode("utf-8")

        segments = parse_whisper_result(payload, time_offset=10.0)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "Hello world")
        self.assertEqual(segments[0].start_time_seconds, 11.25)
        self.assertEqual(segments[0].end_time_seconds, 12.75)

    def test_whisperkit_json_offsets_are_preserved(self) -> None:
        payload = json.dumps(
            {
                "segments": [
                    {
                        "start_seconds": 1.25,
                        "end_seconds": 2.75,
                        "text": " Shared model result ",
                    }
                ]
            }
        ).encode("utf-8")

        segments = parse_whisperkit_result(payload, time_offset=10.0)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "Shared model result")
        self.assertEqual(segments[0].start_time_seconds, 11.25)
        self.assertEqual(segments[0].end_time_seconds, 12.75)

    def test_apple_word_results_are_grouped_into_readable_segments(self) -> None:
        payload = json.dumps(
            {
                "locale": "en-US",
                "segments": [
                    {"start_seconds": 0.0, "duration_seconds": 0.3, "text": "Hello"},
                    {"start_seconds": 0.35, "duration_seconds": 0.2, "text": "world."},
                    {"start_seconds": 2.0, "duration_seconds": 0.2, "text": "Next"},
                    {"start_seconds": 2.25, "duration_seconds": 0.3, "text": "sentence"},
                ],
            }
        ).encode("utf-8")

        segments = parse_apple_result(payload, time_offset=5.0)

        self.assertEqual([segment.text for segment in segments], ["Hello world.", "Next sentence"])
        self.assertEqual(segments[0].start_time_seconds, 5.0)
        self.assertEqual(segments[1].start_time_seconds, 7.0)

    def test_multiple_audio_files_receive_project_timeline_offsets(self) -> None:
        sources = [
            AudioSourceEntry(Path("one.wav"), "one.wav", 3.0),
            AudioSourceEntry(Path("two.wav"), "two.wav", 4.0),
        ]

        def fake_apple(_path: Path, *, time_offset: float):
            return [TranscriptSegment(time_offset, time_offset + 1.0, text="result")]

        with patch("encap.transcription_service._transcribe_with_apple", fake_apple):
            segments = transcribe_audio_sources(sources, APPLE_PROVIDER_ID)

        self.assertEqual([segment.start_time_seconds for segment in segments], [0.0, 3.0])


class TranscriptionProviderRoutingTest(unittest.TestCase):
    def test_whisperkit_uses_a_private_tokenizer_copy_and_disables_network_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            tokenizer_path = root / "shared-tokenizer"
            tokenizer_path.mkdir()
            for filename in ("tokenizer.json", "tokenizer_config.json", "config.json"):
                (tokenizer_path / filename).write_text(filename, encoding="utf-8")

            def fake_run(
                command: list[str],
                *,
                description: str,
                environment: dict[str, str] | None = None,
            ) -> subprocess.CompletedProcess[str]:
                if description == "Audio preparation":
                    return subprocess.CompletedProcess(command, 0, "", "")
                self.assertEqual(description, "WhisperKit transcription")
                private_path = Path(command[command.index("--tokenizer") + 1])
                self.assertNotEqual(private_path, tokenizer_path)
                for filename in ("tokenizer.json", "tokenizer_config.json", "config.json"):
                    self.assertEqual(
                        (private_path / filename).read_text(encoding="utf-8"),
                        filename,
                    )
                self.assertEqual(environment["HF_ENDPOINT"], "http://127.0.0.1:9")
                return subprocess.CompletedProcess(command, 0, '{"segments": []}', "")

            with patch(
                "encap.transcription_service.ensure_ffmpeg",
                return_value="ffmpeg",
            ), patch(
                "encap.transcription_service.ensure_whisperkit_transcriber",
                return_value="whisperkit-transcriber",
            ), patch(
                "encap.transcription_service._run_checked",
                side_effect=fake_run,
            ):
                segments = _transcribe_with_whisperkit(
                    Path("input.m4a"),
                    model_path=Path("/shared/model"),
                    tokenizer_path=tokenizer_path,
                    language_code="auto",
                    time_offset=0.0,
                )

            self.assertEqual(segments, [])

    def test_superwhisper_routes_to_whisper_cpp_without_copying_the_model(self) -> None:
        provider = TranscriptionProvider(
            provider_id=SUPERWHISPER_PROVIDER_ID,
            name="Whisper Large V3 — Superwhisper",
            engine=WHISPER_CPP_ENGINE,
            source_name="Superwhisper",
            model_path=Path("/shared/superwhisper/ggml-large-v3.bin"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = provider
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]
        result = [TranscriptSegment(0.0, 1.0, text="result")]

        with patch(
            "encap.transcription_service._transcribe_with_whisper",
            return_value=result,
        ) as transcribe_whisper, patch(
            "encap.transcription_service.shutil.copy2"
        ) as copy_model:
            segments = transcribe_audio_sources(
                sources,
                SUPERWHISPER_PROVIDER_ID,
                model_store=store,
            )

        self.assertEqual(segments, result)
        transcribe_whisper.assert_called_once_with(
            Path("one.wav"),
            model_path=provider.model_path,
            language_code="auto",
            time_offset=0.0,
        )
        copy_model.assert_not_called()

    def test_macwhisper_routes_to_whisperkit_and_preserves_timeline_offsets(self) -> None:
        provider = TranscriptionProvider(
            provider_id="macwhisper-large-v3-turbo-compressed",
            name="Whisper Large V3 Turbo (compressed) — Whisper Transcription",
            engine=WHISPERKIT_ENGINE,
            source_name="Whisper Transcription",
            model_path=Path("/shared/macwhisper/model"),
            tokenizer_path=Path("/shared/macwhisper/tokenizer"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = provider
        sources = [
            AudioSourceEntry(Path("one.wav"), "one.wav", 3.0),
            AudioSourceEntry(Path("two.wav"), "two.wav", 4.0),
        ]

        def fake_whisperkit(
            _path: Path,
            *,
            model_path: Path,
            tokenizer_path: Path,
            language_code: str,
            time_offset: float,
        ) -> list[TranscriptSegment]:
            self.assertEqual(model_path, provider.model_path)
            self.assertEqual(tokenizer_path, provider.tokenizer_path)
            self.assertEqual(language_code, "auto")
            return [TranscriptSegment(time_offset, time_offset + 1.0, text="result")]

        with patch(
            "encap.transcription_service._transcribe_with_whisperkit",
            side_effect=fake_whisperkit,
        ) as transcribe_whisperkit:
            segments = transcribe_audio_sources(
                sources,
                provider.provider_id,
                model_store=store,
            )

        self.assertEqual(transcribe_whisperkit.call_count, 2)
        self.assertEqual([segment.start_time_seconds for segment in segments], [0.0, 3.0])

    def test_failed_shared_runtime_is_suppressed_for_the_rest_of_the_session(self) -> None:
        provider = TranscriptionProvider(
            provider_id="macwhisper-large-v3-turbo-compressed",
            name="Whisper Large V3 Turbo (compressed) — Whisper Transcription",
            engine=WHISPERKIT_ENGINE,
            source_name="Whisper Transcription",
            model_path=Path("/shared/macwhisper/model"),
            tokenizer_path=Path("/shared/macwhisper/tokenizer"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = provider
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisperkit",
            side_effect=EncapError("WhisperKit transcription failed: model load failed"),
        ), self.assertRaisesRegex(EncapError, "load failed"):
            transcribe_audio_sources(
                sources,
                provider.provider_id,
                model_store=store,
            )

        store.mark_provider_runtime_unusable.assert_called_once_with(provider.provider_id)

    def test_failed_superwhisper_runtime_is_suppressed_for_the_rest_of_the_session(self) -> None:
        provider = TranscriptionProvider(
            provider_id=SUPERWHISPER_PROVIDER_ID,
            name="Whisper Large V3 — Superwhisper",
            engine=WHISPER_CPP_ENGINE,
            source_name="Superwhisper",
            model_path=Path("/shared/superwhisper/ggml-large-v3.bin"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = provider
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisper",
            side_effect=EncapError("Whisper transcription failed: model load failed"),
        ), self.assertRaisesRegex(EncapError, "model load failed"):
            transcribe_audio_sources(
                sources,
                provider.provider_id,
                model_store=store,
            )

        store.mark_provider_runtime_unusable.assert_called_once_with(provider.provider_id)

    def test_audio_preparation_failure_does_not_suppress_a_shared_provider(self) -> None:
        provider = TranscriptionProvider(
            provider_id="macwhisper-large-v3-turbo-compressed",
            name="Whisper Large V3 Turbo (compressed) — Whisper Transcription",
            engine=WHISPERKIT_ENGINE,
            source_name="Whisper Transcription",
            model_path=Path("/shared/macwhisper/model"),
            tokenizer_path=Path("/shared/macwhisper/tokenizer"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = provider
        sources = [AudioSourceEntry(Path("broken.wav"), "broken.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisperkit",
            side_effect=EncapError("Audio preparation failed: unreadable input"),
        ), self.assertRaisesRegex(EncapError, "Audio preparation"):
            transcribe_audio_sources(
                sources,
                provider.provider_id,
                model_store=store,
            )

        store.mark_provider_runtime_unusable.assert_not_called()

    def test_managed_model_routes_to_whisper_cpp(self) -> None:
        model = WHISPER_MODELS[1]
        provider = TranscriptionProvider(
            provider_id=model.model_id,
            name=model.name,
            engine=WHISPER_CPP_ENGINE,
            source_name="EnCap",
            model_path=Path("/encap/models") / model.filename,
            language_code=model.language_code,
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = provider
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisper",
            return_value=[],
        ) as transcribe_whisper:
            transcribe_audio_sources(sources, model.model_id, model_store=store)

        transcribe_whisper.assert_called_once_with(
            Path("one.wav"),
            model_path=provider.model_path,
            language_code=model.language_code,
            time_offset=0.0,
        )

    def test_new_shared_source_supersedes_a_stale_managed_selection(self) -> None:
        managed_model = WHISPER_MODELS[0]
        shared_provider = TranscriptionProvider(
            provider_id=SUPERWHISPER_PROVIDER_ID,
            name="Whisper Large V3 — Superwhisper",
            engine=WHISPER_CPP_ENGINE,
            source_name="Superwhisper",
            model_path=Path("/shared/superwhisper/ggml-large-v3.bin"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = None
        store.available_providers.return_value = (shared_provider,)
        store.selected_model_id.return_value = managed_model.model_id
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisper",
            return_value=[],
        ) as transcribe_whisper:
            transcribe_audio_sources(
                sources,
                managed_model.model_id,
                model_store=store,
            )

        transcribe_whisper.assert_called_once_with(
            Path("one.wav"),
            model_path=shared_provider.model_path,
            language_code="auto",
            time_offset=0.0,
        )

    def test_disappearing_shared_provider_reports_a_clear_error(self) -> None:
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = None
        store.available_providers.return_value = ()
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with self.assertRaisesRegex(EncapError, "no longer available"):
            transcribe_audio_sources(
                sources,
                SUPERWHISPER_PROVIDER_ID,
                model_store=store,
            )

    def test_disappearing_shared_provider_uses_the_next_available_source(self) -> None:
        fallback = TranscriptionProvider(
            provider_id="macwhisper-large-v3-turbo-compressed",
            name="Whisper Large V3 Turbo (compressed) — Whisper Transcription",
            engine=WHISPERKIT_ENGINE,
            source_name="Whisper Transcription",
            model_path=Path("/shared/macwhisper/model"),
            tokenizer_path=Path("/shared/macwhisper/tokenizer"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = None
        store.available_providers.return_value = (fallback,)
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisperkit",
            return_value=[],
        ) as transcribe_whisperkit:
            transcribe_audio_sources(
                sources,
                SUPERWHISPER_PROVIDER_ID,
                model_store=store,
            )

        transcribe_whisperkit.assert_called_once_with(
            Path("one.wav"),
            model_path=fallback.model_path,
            tokenizer_path=fallback.tokenizer_path,
            language_code="auto",
            time_offset=0.0,
        )

    def test_disappearing_shared_provider_honors_selected_managed_model(self) -> None:
        base_model = WHISPER_MODELS[0]
        selected_model = WHISPER_MODELS[2]
        fallbacks = tuple(
            TranscriptionProvider(
                provider_id=model.model_id,
                name=model.name,
                engine=WHISPER_CPP_ENGINE,
                source_name="EnCap",
                model_path=Path("/encap/models") / model.filename,
                language_code=model.language_code,
            )
            for model in (base_model, selected_model)
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.provider.return_value = None
        store.available_providers.return_value = fallbacks
        store.selected_model_id.return_value = selected_model.model_id
        sources = [AudioSourceEntry(Path("one.wav"), "one.wav", 3.0)]

        with patch(
            "encap.transcription_service._transcribe_with_whisper",
            return_value=[],
        ) as transcribe_whisper:
            transcribe_audio_sources(
                sources,
                SUPERWHISPER_PROVIDER_ID,
                model_store=store,
            )

        transcribe_whisper.assert_called_once_with(
            Path("one.wav"),
            model_path=fallbacks[1].model_path,
            language_code=selected_model.language_code,
            time_offset=0.0,
        )


if __name__ == "__main__":
    unittest.main()
