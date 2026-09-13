from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from encap.native_bridge import project_from_payload, project_to_payload, run
from encap.service import build_project_document


class NativeBridgeTests(unittest.TestCase):
    def _write_wav(self, path: Path, frames: int = 8000) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * frames)

    def test_project_payload_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self._write_wav(directory / "one.wav")
            project = build_project_document(directory, lambda _path: True)
            project.metadata.podcast_title = "Station"
            project.chapters[0].link_url = "https://example.com"

            restored = project_from_payload(project_to_payload(project))

            self.assertEqual(restored.metadata.podcast_title, "Station")
            self.assertEqual(restored.audio_sources[0].source_path, directory / "one.wav")
            self.assertEqual(restored.chapters[0].link_url, "https://example.com")

    def test_inspect_command_returns_native_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self._write_wav(directory / "one.wav")

            payload = run(["inspect", str(directory)])

            self.assertIsInstance(payload, dict)
            self.assertEqual(payload["audio_sources"][0]["display_name"], "one.wav")


if __name__ == "__main__":
    unittest.main()
