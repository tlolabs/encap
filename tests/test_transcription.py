from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from encap.models import AudioSourceEntry, TranscriptSegment
from encap.transcription_models import (
    ModelDownloadError,
    TranscriptionModelStore,
    WHISPER_MODELS,
)
from encap.transcription_service import (
    APPLE_PROVIDER_ID,
    parse_apple_result,
    parse_whisper_result,
    transcribe_audio_sources,
)


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


if __name__ == "__main__":
    unittest.main()
