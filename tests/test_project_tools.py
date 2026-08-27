from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
import sys
import shutil
import stat
import struct
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from encap.export_tools import (
    build_ffmpeg_export_command,
    export_mp3_with_lame,
    export_project,
    validate_project_for_export,
)
from encap.gui import _apply_chapter_form_values, validate_link_url
from encap.project_io import cleanup_loaded_project, load_project, save_project
from encap.service import build_project_document, prepare_sources_for_paths
from encap.transcript_tools import export_transcript_srt, export_transcript_txt, parse_transcript_text
from encap.wav_tools import EncapError


def write_test_wav(
    path: Path,
    frame_count: int,
    sample_rate: int = 48000,
    channels: int = 1,
) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count * channels)


def write_test_aiff(
    path: Path,
    frame_count: int,
    sample_rate: int = 48000,
    channels: int = 1,
) -> None:
    if sample_rate != 48000:
        raise ValueError("The compact AIFF test writer currently uses a 48 kHz fixture.")
    sample_rate_extended = bytes.fromhex("400ebb80000000000000")
    comm_data = struct.pack(">HIH", channels, frame_count, 16) + sample_rate_extended
    sample_data = b"\x00\x00" * frame_count * channels
    ssnd_data = struct.pack(">II", 0, 0) + sample_data

    def chunk(chunk_id: bytes, data: bytes) -> bytes:
        return chunk_id + struct.pack(">I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")

    body = b"AIFF" + chunk(b"COMM", comm_data) + chunk(b"SSND", ssnd_data)
    path.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)


def ffprobe_output(output_path: Path) -> dict:
    command = [
        shutil.which("ffprobe") or "ffprobe",
        "-v",
        "error",
        "-show_entries",
        (
            "format_tags=title,album,artist,comment:"
            "chapter=start_time,end_time:chapter_tags=title:"
            "stream=codec_name,codec_type,width,height:"
            "stream_disposition=attached_pic"
        ),
        "-of",
        "json",
        str(output_path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def minimal_project_manifest() -> dict:
    return {
        "schema_version": 1,
        "metadata": {},
        "audio_sources": [],
        "chapters": [],
        "transcript_segments": [],
        "export_settings": {},
    }


class ProjectToolsTest(unittest.TestCase):
    def test_build_project_document_infers_episode_title_and_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()

            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=48000)
            write_test_wav(source_dir / "05042026120500_DN-700R.wav", frame_count=96000)

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)

            self.assertEqual(project.metadata.episode_title, "2026-05-04 Aircheck")
            self.assertEqual(len(project.chapters), 2)
            self.assertEqual(project.chapters[0].start_time_seconds, 0.0)
            self.assertAlmostEqual(project.chapters[1].start_time_seconds, 1.0, places=2)
            self.assertEqual(project.export_settings.output_format, "mp3")
            self.assertEqual(project.export_settings.encoder, "lame")
            self.assertEqual(project.export_settings.channels, 1)
            self.assertEqual(project.export_settings.quality_preset, "160k")

    def test_stereo_import_selects_stereo_and_highest_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            source_dir = Path(temp_dir_name)
            write_test_wav(
                source_dir / "05042026120000_DN-700R.wav",
                frame_count=48000,
                channels=2,
            )

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)

            self.assertEqual(project.export_settings.encoder, "lame")
            self.assertEqual(project.export_settings.channels, 2)
            self.assertEqual(project.export_settings.quality_preset, "320k")

    def test_import_accepts_wav_and_aiff_in_the_same_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            source_dir = Path(temp_dir_name)
            write_test_aiff(
                source_dir / "05042026110000_DN-700R.aiff",
                frame_count=24000,
            )
            write_test_wav(
                source_dir / "05042026120000_DN-700R.wav",
                frame_count=48000,
            )

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)

            self.assertEqual(
                [entry.display_name for entry in project.audio_sources],
                [
                    "05042026110000_DN-700R.aiff",
                    "05042026120000_DN-700R.wav",
                ],
            )
            self.assertAlmostEqual(project.audio_sources[0].duration_seconds, 0.5)
            self.assertAlmostEqual(project.chapters[1].start_time_seconds, 0.5)
            prepared = prepare_sources_for_paths(
                [entry.source_path for entry in project.audio_sources],
                prompt_for_conversion=lambda _: False,
            )
            self.assertEqual([source.frame_count for source in prepared], [24000, 48000])

    def test_save_and_load_project_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()

            first = source_dir / "05042026120000_DN-700R.wav"
            second = source_dir / "05042026120500_DN-700R.wav"
            write_test_wav(first, frame_count=48000)
            write_test_wav(second, frame_count=96000)

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            project.metadata.podcast_title = "Show Title"
            project.metadata.summary = "Episode summary"
            project.transcript_segments = parse_transcript_text("Host: Hello world")
            project.chapters[0].link_url = "https://example.com/chapter"
            project.export_settings.output_format = "aac"
            project.export_settings.encoder = "audio_toolbox"
            project.export_settings.channels = 1
            project.export_settings.quality_preset = "80k"

            project_path = temp_dir / "episode.encap"
            save_project(project, project_path)
            first.unlink()
            second.unlink()

            loaded = load_project(project_path)
            self.addCleanup(lambda: cleanup_loaded_project(loaded))

            self.assertEqual(loaded.metadata.podcast_title, "Show Title")
            self.assertEqual(loaded.metadata.summary, "Episode summary")
            self.assertTrue(loaded.audio_sources[0].source_path.exists())
            self.assertEqual(loaded.transcript_segments[0].speaker, "Host")
            self.assertEqual(loaded.chapters[0].link_url, "https://example.com/chapter")
            self.assertEqual(loaded.export_settings.output_format, "aac")
            self.assertEqual(loaded.export_settings.encoder, "audio_toolbox")
            self.assertEqual(loaded.export_settings.channels, 1)
            self.assertEqual(loaded.export_settings.quality_preset, "80k")

    def test_save_project_replaces_existing_file_only_after_archive_completes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=100)
            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            project_path = temp_dir / "episode.encap"
            original_contents = b"existing project remains intact"
            project_path.write_bytes(original_contents)

            with patch.object(zipfile.ZipFile, "writestr", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(EncapError, "Project could not be saved: disk full"):
                    save_project(project, project_path)

            self.assertEqual(project_path.read_bytes(), original_contents)
            self.assertEqual(list(temp_dir.glob(".episode.encap.*.tmp")), [])
            self.assertIsNone(project.project_path)

    def test_load_project_rejects_unsafe_archive_members(self) -> None:
        symlink = zipfile.ZipInfo("audio/link.wav")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        unsafe_members: tuple[str | zipfile.ZipInfo, ...] = (
            "../escaped.txt",
            "/absolute.txt",
            symlink,
        )

        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            for index, member in enumerate(unsafe_members):
                with self.subTest(member=member):
                    project_path = temp_dir / f"unsafe-archive-{index}.encap"
                    extraction_dir = temp_dir / f"extracted-{index}"
                    with zipfile.ZipFile(project_path, "w") as archive:
                        archive.writestr(member, b"unsafe")

                    with patch(
                        "encap.project_io.tempfile.mkdtemp",
                        return_value=str(extraction_dir),
                    ):
                        with self.assertRaisesRegex(
                            EncapError,
                            r"unsafe (?:stored )?path",
                        ):
                            load_project(project_path)

                    self.assertFalse(extraction_dir.exists())
                    self.assertFalse((temp_dir / "escaped.txt").exists())

    def test_load_project_rejects_unsafe_manifest_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            absolute_path = str((temp_dir / "outside.wav").resolve())
            cases = (
                ("audio parent", "audio", "../outside.wav"),
                ("audio absolute", "audio", absolute_path),
                ("artwork parent", "artwork", "../../outside.png"),
                ("artwork absolute", "artwork", absolute_path),
                ("chapter parent", "chapter", "../outside.png"),
                ("chapter absolute", "chapter", absolute_path),
            )

            for index, (name, field, stored_path) in enumerate(cases):
                with self.subTest(name=name):
                    manifest = minimal_project_manifest()
                    if field == "audio":
                        manifest["audio_sources"] = [{"stored_path": stored_path}]
                    elif field == "artwork":
                        manifest["metadata"]["artwork_stored_path"] = stored_path
                    else:
                        manifest["chapters"] = [{"image_stored_path": stored_path}]

                    project_path = temp_dir / f"unsafe-manifest-{index}.encap"
                    extraction_dir = temp_dir / f"manifest-extracted-{index}"
                    with zipfile.ZipFile(project_path, "w") as archive:
                        archive.writestr("manifest.json", json.dumps(manifest))

                    with patch(
                        "encap.project_io.tempfile.mkdtemp",
                        return_value=str(extraction_dir),
                    ):
                        with self.assertRaisesRegex(EncapError, r"unsafe stored path"):
                            load_project(project_path)

                    self.assertFalse(extraction_dir.exists())

    def test_transcript_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=48000)

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            project.transcript_segments = parse_transcript_text("Host: Hello world\nGuest: Goodbye")

            txt_path = temp_dir / "transcript.txt"
            srt_path = temp_dir / "transcript.srt"
            export_transcript_txt(project, txt_path)
            export_transcript_srt(project, srt_path)

            self.assertIn("Host: Hello world", txt_path.read_text(encoding="utf-8"))
            srt_text = srt_path.read_text(encoding="utf-8")
            self.assertIn("00:00:00,000 --> 00:00:05,000", srt_text)
            self.assertIn("Guest: Goodbye", srt_text)

    def test_ffmpeg_export_command_explicitly_maps_metadata_and_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=48000)
            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)

            command = build_ffmpeg_export_command(
                ffmpeg="ffmpeg",
                project=project,
                audio_input=temp_dir / "audio.wav",
                metadata_input=temp_dir / "metadata.ffmeta",
                output_path=temp_dir / "output.mp3",
            )

            self.assertEqual(command[command.index("-map_metadata") + 1], "1")
            self.assertEqual(command[command.index("-map_chapters") + 1], "1")
            self.assertEqual(command[command.index("-compression_level") + 1], "0")

            project.export_settings.output_format = "aac"
            project.export_settings.encoder = "audio_toolbox"
            project.export_settings.channels = 1
            project.export_settings.quality_preset = "80k"
            aac_command = build_ffmpeg_export_command(
                ffmpeg="ffmpeg",
                project=project,
                audio_input=temp_dir / "audio.wav",
                metadata_input=temp_dir / "metadata.ffmeta",
                output_path=temp_dir / "output.m4a",
            )
            self.assertEqual(aac_command[aac_command.index("-c:a") + 1], "aac_at")
            self.assertEqual(aac_command[aac_command.index("-ac") + 1], "1")
            self.assertEqual(aac_command[aac_command.index("-b:a") + 1], "80k")
            self.assertEqual(aac_command[aac_command.index("-aac_at_mode") + 1], "cbr")
            self.assertEqual(aac_command[aac_command.index("-aac_at_quality") + 1], "0")

            project.export_settings.encoder = "ffmpeg"
            native_aac_command = build_ffmpeg_export_command(
                ffmpeg="ffmpeg",
                project=project,
                audio_input=temp_dir / "audio.wav",
                metadata_input=temp_dir / "metadata.ffmeta",
                output_path=temp_dir / "native-output.m4a",
            )
            self.assertEqual(
                native_aac_command[native_aac_command.index("-aac_coder") + 1],
                "twoloop",
            )

    def test_export_rejects_chapter_images_instead_of_silently_omitting_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=100)
            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            project.metadata.podcast_title = "Show Title"
            project.chapters[0].image_path = temp_dir / "chapter.png"

            with self.assertRaisesRegex(
                EncapError,
                r"Chapter-specific artwork cannot be embedded.*chapter 1",
            ):
                validate_project_for_export(project)

    def test_lame_encodes_the_stitched_wav_in_one_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=24000)
            write_test_wav(source_dir / "05042026120500_DN-700R.wav", frame_count=48000)
            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            project.export_settings.quality_preset = "128k"

            stitched_wav = temp_dir / "stitched.wav"
            with (
                patch("encap.export_tools.ensure_lame", return_value="/usr/bin/lame"),
                patch("encap.export_tools._run_lame") as run_lame,
            ):
                output_path = export_mp3_with_lame(project, stitched_wav, temp_dir)

            self.assertEqual(output_path, temp_dir / "lame-encoded.mp3")
            run_lame.assert_called_once_with(
                "/usr/bin/lame",
                stitched_wav,
                output_path,
                "128",
                1,
            )

    def test_exported_mp3_and_m4a_preserve_media_contract(self) -> None:
        missing_tools = [
            tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None
        ]
        if missing_tools:
            message = f"Export contract test requires: {', '.join(missing_tools)}"
            if os.environ.get("ENCAP_REQUIRE_MEDIA_TESTS") == "1":
                self.fail(message)
            self.skipTest(message)

        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=36000)
            write_test_wav(source_dir / "05042026120500_DN-700R.wav", frame_count=60000)

            artwork_path = temp_dir / "cover.jpg"
            subprocess.run(
                [
                    shutil.which("ffmpeg") or "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=32x32",
                    "-frames:v",
                    "1",
                    str(artwork_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            project.metadata.podcast_title = "Show Title"
            project.metadata.episode_title = "Episode Title"
            project.metadata.summary = "Summary text"
            project.metadata.artwork_path = artwork_path
            project.chapters[0].title = "Opening & News"
            project.chapters[0].link_url = "https://example.com/opening"
            project.chapters[1].title = "Interview Finale"
            project.chapters[1].link_url = "https://example.com/interview"
            project.export_settings.quality_preset = "128k"
            project.export_settings.encoder = "ffmpeg_default"

            for output_format in ("mp3", "m4a"):
                with self.subTest(output_format=output_format):
                    project.export_settings.output_format = output_format
                    output_path = export_project(
                        project,
                        temp_dir / output_format,
                        prompt_for_conversion=lambda _: False,
                    )
                    probe = ffprobe_output(output_path)

                    self.assertEqual(
                        probe["format"]["tags"],
                        {
                            "title": "Episode Title",
                            "album": "Show Title",
                            "artist": "Show Title",
                            "comment": "Summary text",
                        },
                    )
                    self.assertEqual(
                        [
                            {
                                "start_time": chapter["start_time"],
                                "end_time": chapter["end_time"],
                                "tags": chapter["tags"],
                            }
                            for chapter in probe["chapters"]
                        ],
                        [
                            {
                                "start_time": "0.000000",
                                "end_time": "0.750000",
                                "tags": {"title": "Opening & News"},
                            },
                            {
                                "start_time": "0.750000",
                                "end_time": "2.000000",
                                "tags": {"title": "Interview Finale"},
                            },
                        ],
                    )
                    artwork_streams = [
                        stream
                        for stream in probe["streams"]
                        if stream.get("disposition", {}).get("attached_pic") == 1
                    ]
                    self.assertEqual(
                        artwork_streams,
                        [
                            {
                                "codec_name": "mjpeg",
                                "codec_type": "video",
                                "width": 32,
                                "height": 32,
                                "disposition": {"attached_pic": 1},
                            }
                        ],
                    )

    def test_chapter_form_values_apply_url_without_manual_save_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            source_dir.mkdir()
            write_test_wav(source_dir / "05042026120000_DN-700R.wav", frame_count=48000)

            project = build_project_document(source_dir, prompt_for_conversion=lambda _: False)
            chapter = project.chapters[0]
            _apply_chapter_form_values(
                chapter=chapter,
                start_value="0:00",
                duration_value="0:01",
                chapter_number_value="1",
                title_value="Chapter 1",
                link_value="example.com/chapter",
            )
            self.assertEqual(project.chapters[0].link_url, "https://example.com/chapter")

    def test_validate_link_url_promotes_bare_host_and_returns_resolved_url(self) -> None:
        with patch("encap.gui._resolve_url_candidate", return_value="https://www.apple.com/") as resolver:
            status, resolved_url, detail = validate_link_url("apple.com")

        self.assertEqual(status, "valid")
        self.assertEqual(resolved_url, "https://www.apple.com/")
        self.assertEqual(detail, "")
        self.assertEqual(
            [call.args[0] for call in resolver.call_args_list],
            ["https://apple.com"],
        )

    def test_validate_link_url_falls_back_to_http_for_bare_host(self) -> None:
        def fake_resolve(candidate: str) -> str:
            if candidate == "https://legacy.example.com":
                raise ValueError("https unavailable")
            return "http://legacy.example.com"

        with patch("encap.gui._resolve_url_candidate", side_effect=fake_resolve) as resolver:
            status, resolved_url, detail = validate_link_url("legacy.example.com")

        self.assertEqual(status, "valid")
        self.assertEqual(resolved_url, "http://legacy.example.com")
        self.assertEqual(detail, "")
        self.assertEqual(
            [call.args[0] for call in resolver.call_args_list],
            ["https://legacy.example.com", "http://legacy.example.com"],
        )


if __name__ == "__main__":
    unittest.main()
