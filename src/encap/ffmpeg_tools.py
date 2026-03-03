from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .models import WavFormat
from .wav_tools import EncapError


def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise EncapError("ffmpeg is required for conversion but was not found on PATH.")
    return ffmpeg


def codec_for_format(wav_format: WavFormat) -> str:
    if wav_format.audio_format not in {1, 65534}:
        raise EncapError(
            "Automatic conversion currently supports PCM WAV targets only."
        )
    bits = wav_format.bits_per_sample
    if bits == 8:
        return "pcm_u8"
    if bits == 16:
        return "pcm_s16le"
    if bits == 24:
        return "pcm_s24le"
    if bits == 32:
        return "pcm_s32le"
    raise EncapError(f"Unsupported PCM bit depth for conversion: {bits}.")


def convert_to_match(source_path: Path, target_path: Path, wav_format: WavFormat) -> None:
    ffmpeg = ensure_ffmpeg()
    codec = codec_for_format(wav_format)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-acodec",
        codec,
        "-ar",
        str(wav_format.sample_rate),
        "-ac",
        str(wav_format.channels),
        str(target_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise EncapError(
            "ffmpeg conversion failed.\n"
            f"Command: {' '.join(command)}\n"
            f"stderr:\n{completed.stderr.strip()}"
        )
