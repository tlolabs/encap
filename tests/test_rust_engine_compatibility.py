from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from encap.models import AudioSourceEntry, ChapterEntry, ProjectDocument
from encap.project_io import cleanup_loaded_project, load_project, save_project


ENGINE = ROOT / "target" / "debug" / "encap-engine"


@unittest.skipUnless(ENGINE.is_file(), "build encap-engine before compatibility tests")
class RustEngineCompatibilityTests(unittest.TestCase):
    def make_audio(self, root: Path) -> Path:
        path = root / "part 01.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(b"\0\0" * 4_800)
        return path

    def run_engine(self, *arguments: str) -> object:
        completed = subprocess.run(
            [ENGINE, *arguments], capture_output=True, text=True, check=True
        )
        return json.loads(completed.stdout)

    def test_rust_opens_python_project_without_losing_manifest_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = self.make_audio(root)
            project = ProjectDocument(project_title="Python baseline")
            project.audio_sources = [AudioSourceEntry(audio, audio.name, 0.1)]
            project.chapters = [ChapterEntry(0, 0.1, 1, "Opening")]
            path = save_project(project, root / "python.encap")

            payload = self.run_engine("open", str(path), "--extraction-parent", str(root))
            self.assertEqual(payload["project_title"], "Python baseline")
            self.assertEqual(payload["chapters"][0]["title"], "Opening")
            self.assertTrue(Path(payload["audio_sources"][0]["source_path"]).is_file())

    def test_python_opens_rust_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = self.make_audio(root)
            payload = {
                "schema_version": 1,
                "project_title": "Rust replacement",
                "metadata": {"podcast_title": "Show", "episode_title": "Episode"},
                "audio_sources": [
                    {"source_path": str(audio), "display_name": audio.name, "duration_seconds": 0.1}
                ],
                "chapters": [
                    {
                        "id": "chapter-one",
                        "start_time_seconds": 0,
                        "duration_seconds": 0.1,
                        "chapter_number": 1,
                        "title": "Opening",
                    }
                ],
                "transcript_segments": [],
                "export_settings": {
                    "output_format": "mp3",
                    "quality_preset": "320k",
                    "encoder": "ffmpeg",
                    "channels": 2,
                },
            }
            payload_path = root / "payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_engine("save", str(payload_path), str(root / "rust.encap"))

            loaded = load_project(Path(result["path"]))
            try:
                self.assertEqual(loaded.project_title, "Rust replacement")
                self.assertEqual(loaded.metadata.podcast_title, "Show")
                self.assertEqual(loaded.chapters[0].title, "Opening")
            finally:
                cleanup_loaded_project(loaded)

    def test_rust_engine_exports_chaptered_audio_with_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = self.make_audio(root)
            payload = {
                "schema_version": 1,
                "project_title": "Engine export",
                "metadata": {
                    "podcast_title": "Compatibility Show",
                    "episode_title": "Compatibility Episode",
                    "summary": "Created by the cross-language test.",
                },
                "audio_sources": [
                    {"source_path": str(audio), "display_name": audio.name, "duration_seconds": 0.1}
                ],
                "chapters": [
                    {
                        "id": "chapter-one",
                        "start_time_seconds": 0,
                        "duration_seconds": 0.1,
                        "chapter_number": 1,
                        "title": "Opening",
                    }
                ],
                "transcript_segments": [],
                "export_settings": {
                    "output_format": "mp3",
                    "quality_preset": "128k",
                    "encoder": "ffmpeg",
                    "channels": 1,
                },
            }
            payload_path = root / "payload.json"
            output_path = root / "result.mp3"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_engine("export", str(payload_path), str(output_path))
            self.assertEqual(Path(result["path"]), output_path)
            self.assertGreater(output_path.stat().st_size, 0)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format_tags=title,album", "-of", "json", output_path],
                capture_output=True,
                text=True,
                check=True,
            )
            tags = json.loads(probe.stdout)["format"]["tags"]
            self.assertEqual(tags["title"], "Compatibility Episode")
            self.assertEqual(tags["album"], "Compatibility Show")


if __name__ == "__main__":
    unittest.main()
