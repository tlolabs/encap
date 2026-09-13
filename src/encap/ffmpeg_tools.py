from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from .models import WavFormat
from .wav_tools import EncapError


def _tool_name(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def _is_runnable(path: Path) -> bool:
    if not path.is_file():
        return False
    return sys.platform == "win32" or os.access(path, os.X_OK)


def _bundled_candidates(name: str) -> list[Path]:
    tool_name = _tool_name(name)
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / tool_name)

    if sys.platform == "darwin":
        candidates.extend(
            [
                Path(f"/ENCAP.app/Contents/MacOS/{tool_name}"),
                Path(f"/Applications/ENCAP.app/Contents/MacOS/{tool_name}"),
                Path(f"/Applications/EnCap.app/Contents/MacOS/{tool_name}"),
            ]
        )

    return candidates


def _resolve_media_tool(name: str, fallback_paths: list[Path]) -> str:
    for candidate in [*_bundled_candidates(name), *fallback_paths]:
        if _is_runnable(candidate):
            return str(candidate)

    tool = shutil.which(_tool_name(name)) or shutil.which(name)
    if tool is not None:
        return tool

    checked = ", ".join(
        str(path) for path in [*_bundled_candidates(name), *fallback_paths]
    )
    raise EncapError(f"{name} is required but was not found. Checked {checked} and PATH.")


def ensure_ffmpeg() -> str:
    return _resolve_media_tool(
        "ffmpeg",
        [
            Path("/usr/local/bin/ffmpeg"),
            Path("/Applications/ffmpeg"),
        ],
    )


def ensure_ffprobe() -> str:
    return _resolve_media_tool(
        "ffprobe",
        [
            Path("/usr/local/bin/ffprobe"),
            Path("/Applications/ffprobe"),
        ],
    )


def ensure_lame() -> str:
    """Resolve the bundled LAME first, then common developer installations."""
    return _resolve_media_tool(
        "lame",
        [
            Path("/opt/homebrew/bin/lame"),
            Path("/usr/local/bin/lame"),
        ],
    )


@lru_cache(maxsize=None)
def media_encoder_available(encoder_name: str) -> bool:
    try:
        ffmpeg = ensure_ffmpeg()
    except EncapError:
        return False
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-h", f"encoder={encoder_name}"],
        capture_output=True,
        text=True,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    return completed.returncode == 0 and f"Encoder {encoder_name}" in output


@lru_cache(maxsize=1)
def apple_aac_encoder_implementation() -> str:
    """Describe the AAC components macOS exposes to AudioToolbox.

    FFmpeg's ``aac_at`` wrapper creates a system-selected AudioConverter and
    does not expose AudioConverterNewSpecific, so this is a capability report,
    not a claim that a particular component can be forced.
    """
    if sys.platform != "darwin":
        return ""
    project_helper = Path(__file__).resolve().parents[2] / ".build-tools" / "apple-aac-info"
    candidates = [*_bundled_candidates("apple-aac-info"), project_helper]
    helper = next((candidate for candidate in candidates if _is_runnable(candidate)), None)
    if helper is None:
        return "Apple system-selected (component details unavailable)"
    completed = subprocess.run([str(helper)], capture_output=True, text=True)
    implementation = completed.stdout.strip()
    if completed.returncode == 0 and implementation:
        return implementation
    return "Apple system-selected (component details unavailable)"


def codec_for_format(wav_format: WavFormat) -> str:
    if wav_format.encoding == 3 and wav_format.bits_per_sample in {32, 64}:
        return f"pcm_f{wav_format.bits_per_sample}le"
    if wav_format.encoding != 1:
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
