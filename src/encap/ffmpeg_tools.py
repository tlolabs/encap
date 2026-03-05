from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .models import WavFormat
from .wav_tools import EncapError


def ensure_ffmpeg() -> str:
    # macOS lookup order:
    # 1) bundled binary inside the .app
    # 2) system install in /usr/local/bin
    # 3) /Applications/ffmpeg
    # 4) PATH fallback
    bundled_candidates = []
    if getattr(sys, "frozen", False):
        bundled_candidates.append(Path(sys.executable).resolve().parent / "ffmpeg")
    bundled_candidates.append(Path("/ENCAP.app/Contents/MacOS/ffmpeg"))
    bundled_candidates.append(Path("/Applications/ENCAP.app/Contents/MacOS/ffmpeg"))

    for candidate in [
        *bundled_candidates,
        Path("/usr/local/bin/ffmpeg"),
        Path("/Applications/ffmpeg"),
    ]:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise EncapError(
            "ffmpeg is required for conversion but was not found. "
            "Checked app bundle, /usr/local/bin/ffmpeg, /Applications/ffmpeg, and PATH."
        )
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
