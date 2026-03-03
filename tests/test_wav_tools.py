from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from encap.service import create_stitched_wav
from encap.wav_tools import load_wav_source


def write_test_wav(path: Path, frame_count: int, sample_rate: int = 48000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


class WavToolsTest(unittest.TestCase):
    def test_stitches_wavs_and_writes_cue_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_dir = temp_dir / "src"
            output_dir = temp_dir / "out"
            source_dir.mkdir()
            output_dir.mkdir()

            write_test_wav(source_dir / "001.wav", frame_count=100)
            write_test_wav(source_dir / "002.wav", frame_count=200)
            write_test_wav(source_dir / "003.wav", frame_count=300)

            plan = create_stitched_wav(
                source_dir=source_dir,
                output_dir=output_dir,
                output_name="joined.wav",
                prompt_for_conversion=lambda _: False,
                write_report=True,
            )

            self.assertEqual(plan.output_path.name, "joined.wav")
            self.assertEqual([marker.sample_offset for marker in plan.markers], [100, 300])

            output_bytes = plan.output_path.read_bytes()
            self.assertIn(b"cue ", output_bytes)
            self.assertIn(b"LIST", output_bytes)
            self.assertIn(b"labl", output_bytes)

            stitched = load_wav_source(plan.output_path)
            self.assertEqual(stitched.frame_count, 600)

            cue_index = output_bytes.index(b"cue ")
            cue_count = struct.unpack("<I", output_bytes[cue_index + 8 : cue_index + 12])[0]
            self.assertEqual(cue_count, 2)
            self.assertTrue(plan.report_path is not None and plan.report_path.exists())


if __name__ == "__main__":
    unittest.main()
