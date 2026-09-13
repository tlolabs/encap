from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from encap.export_tools import export_project, validate_project_for_export
from encap.file_tools import atomic_output
from encap.models import TranscriptSegment
from encap.project_io import cleanup_loaded_project, load_project, save_project
from encap.service import build_project_document, create_stitched_wav_for_paths
from encap.wav_tools import (
    EncapError, _decode_extended_float, _swap_sample_byte_order,
    build_stitch_plan, load_wav_source, read_source_pcm, write_wav,
)


def write_audio(path: Path, rate: int = 48000) -> None:
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(bytes(range(256)) * 100)


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.audio = self.root / 'source.wav'
        write_audio(self.audio)

    def project(self):
        project = build_project_document(self.root, lambda _: True)
        project.metadata.podcast_title = 'Podcast'
        project.export_settings.encoder = 'ffmpeg'
        return project

    def test_atomic_output_preserves_existing_file_and_removes_partial_on_error(self):
        destination = self.root / 'result.mp3'
        destination.write_bytes(b'original')
        with self.assertRaises(OSError):
            with atomic_output(destination) as partial:
                self.assertEqual(partial.suffix, '.mp3')
                partial.write_bytes(b'partial')
                raise OSError('disk full')
        self.assertEqual(destination.read_bytes(), b'original')
        self.assertEqual(list(self.root.glob('.result.*')), [])

    def test_wav_failure_preserves_existing_destination(self):
        destination = self.root / 'output.wav'
        destination.write_bytes(b'original')
        source = load_wav_source(self.audio)
        self.audio.write_bytes(b'truncated')
        with self.assertRaises(EncapError):
            write_wav(build_stitch_plan([source], destination))
        self.assertEqual(destination.read_bytes(), b'original')
        self.assertEqual(list(self.root.glob('.output.*')), [])

    def test_wav_can_read_input_before_atomically_replacing_same_path(self):
        source = load_wav_source(self.audio)
        pcm = read_source_pcm(source)
        write_wav(build_stitch_plan([source, source], self.audio))
        self.assertEqual(read_source_pcm(load_wav_source(self.audio)), pcm * 2)

    def test_malformed_wav_formats_fail_before_time_or_sample_arithmetic(self):
        valid = self.audio.read_bytes()
        for field, code, value in [(20,'H',2), (22,'H',0), (24,'I',0),
                                   (28,'I',1), (32,'H',1), (34,'H',0), (34,'H',7)]:
            with self.subTest(field=field, value=value):
                data = bytearray(valid)
                struct.pack_into('<' + code, data, field, value)
                self.audio.write_bytes(data)
                with self.assertRaises(EncapError):
                    load_wav_source(self.audio)

    def test_invalid_aiff_sample_rates_raise_domain_errors(self):
        for raw in [b'\0'*10, bytes.fromhex('7fff8000000000000000'),
                    bytes.fromhex('7ffe8000000000000000'), bytes.fromhex('bfff8000000000000000')]:
            with self.subTest(raw=raw), self.assertRaises(EncapError):
                _decode_extended_float(raw)
        self.assertEqual(_decode_extended_float(bytes.fromhex('400ebb80000000000000')), 48000)

    def test_aiff_byte_swap_preserves_all_sample_widths(self):
        for width in (2, 3, 4, 8):
            data = bytes(range(240))
            expected = b''.join(data[i:i+width][::-1] for i in range(0, len(data), width))
            self.assertEqual(_swap_sample_byte_order(data, width), expected)

    def test_mixed_format_stitch_streams_conversion_and_returned_plan_stays_readable(self):
        second = self.root / 'second.wav'
        write_audio(second, 24000)
        output = self.root / 'stitched.wav'
        with patch('encap.service.read_source_pcm', side_effect=AssertionError('materialized PCM')):
            plan = create_stitched_wav_for_paths([self.audio, second], self.root, output.name, lambda _: True)
        self.assertEqual(b''.join(read_source_pcm(source) for source in plan.sources),
                         read_source_pcm(load_wav_source(output)))

    def test_failed_encoder_preserves_existing_export(self):
        project = self.project()
        target = self.root / 'result.mp3'
        target.write_bytes(b'previous export')
        def failed(command, **kwargs):
            Path(command[-1]).write_bytes(b'incomplete audio')
            return subprocess.CompletedProcess(command, 1, '', 'encoder failed')
        with patch('encap.export_tools.subprocess.run', side_effect=failed):
            with self.assertRaisesRegex(EncapError, 'Final export failed'):
                export_project(project, self.root, lambda _: True, output_path=target)
        self.assertEqual(target.read_bytes(), b'previous export')
        self.assertEqual(list(self.root.glob('.result.*')), [])

    def test_export_rejects_overwriting_source_and_missing_artwork(self):
        project = self.project()
        original = self.audio.read_bytes()
        with self.assertRaisesRegex(EncapError, 'must not overwrite'):
            export_project(project, self.root, lambda _: True, output_path=self.audio)
        self.assertEqual(self.audio.read_bytes(), original)
        project.metadata.artwork_path = self.root / 'missing.png'
        with self.assertRaisesRegex(EncapError, 'artwork is missing'):
            validate_project_for_export(project)

    def test_export_rejects_invalid_chapter_times(self):
        for value in (math.nan, math.inf, -1, 1e308):
            project = self.project()
            project.chapters[0].start_time_seconds = value
            with self.subTest(value=value), self.assertRaises(EncapError):
                validate_project_for_export(project)

    def test_corrupt_project_is_reported_as_domain_error(self):
        target = self.root / 'invalid.encap'
        target.write_text('not a zip')
        with self.assertRaises(EncapError):
            load_project(target)

    def test_invalid_manifests_fail_and_extraction_is_cleaned(self):
        project_file = save_project(self.project(), self.root / 'valid.encap')
        with zipfile.ZipFile(project_file) as archive:
            original = json.loads(archive.read('manifest.json'))
        invalid = [[], dict(original, metadata=[]), dict(original, chapters=[None]),
                   dict(original, transcript_segments=[{'start_time_seconds': float('nan')}]),
                   dict(original, transcript_segments=[{'start_time_seconds': 2, 'end_time_seconds': 1}]),
                   dict(original, metadata={'episode_title': None}),
                   dict(original, audio_sources=[{'stored_path': 'audio/missing.wav'}])]
        parent = self.root / 'sessions'
        parent.mkdir()
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                target = self.root / 'invalid.encap'
                with zipfile.ZipFile(target, 'w') as archive:
                    archive.writestr('manifest.json', json.dumps(manifest))
                with self.assertRaises(EncapError):
                    load_project(target, extraction_parent=parent)
                self.assertEqual(list(parent.iterdir()), [])

    def test_project_archive_rejects_excessive_file_count_and_cleans_extraction(self):
        target = self.root / 'too-many.encap'
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('manifest.json', '{}')
            archive.writestr('extra.txt', 'extra')
        parent = self.root / 'sessions'
        parent.mkdir()

        with patch('encap.project_io._MAX_PROJECT_ENTRIES', 1):
            with self.assertRaisesRegex(EncapError, 'too many files'):
                load_project(target, extraction_parent=parent)

        self.assertEqual(list(parent.iterdir()), [])

    def test_project_archive_rejects_excessive_expanded_size_and_cleans_extraction(self):
        target = self.root / 'too-large.encap'
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', '{}')
            archive.writestr('audio/large.wav', b'0' * 1024)
        parent = self.root / 'sessions'
        parent.mkdir()

        with patch('encap.project_io._MAX_PROJECT_TOTAL_BYTES', 512):
            with self.assertRaisesRegex(EncapError, 'too large'):
                load_project(target, extraction_parent=parent)

        self.assertEqual(list(parent.iterdir()), [])

    def test_loaded_project_media_is_owned_by_requested_session(self):
        parent = self.root / 'sessions'
        parent.mkdir()
        saved = save_project(self.project(), self.root / 'project.encap')
        loaded = load_project(saved, extraction_parent=parent)
        self.assertEqual(loaded.working_dir.parent, parent)
        self.assertEqual(loaded.audio_sources[0].source_path.read_bytes(), self.audio.read_bytes())
        cleanup_loaded_project(loaded)
        self.assertEqual(list(parent.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
