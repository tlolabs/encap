from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from .ffmpeg_tools import convert_to_match
from .models import StitchPlan, WavSource
from .wav_tools import (
    EncapError,
    build_stitch_plan,
    formats_match,
    load_wav_source,
    write_wav,
)

ConversionPrompt = Callable[[Path], bool]


def discover_wav_files(source_dir: Path) -> list[Path]:
    files = sorted(
        path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() == ".wav"
    )
    if not files:
        raise EncapError(f"No WAV files were found in {source_dir}.")
    return files


def prepare_sources(
    source_dir: Path,
    prompt_for_conversion: ConversionPrompt,
) -> list[WavSource]:
    wav_paths = discover_wav_files(source_dir)
    sources: list[WavSource] = []
    reference = load_wav_source(wav_paths[0])
    sources.append(reference)

    with tempfile.TemporaryDirectory(prefix="encap-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        for path in wav_paths[1:]:
            source = load_wav_source(path)
            if formats_match(reference.wav_format, source.wav_format):
                sources.append(source)
                continue

            if not prompt_for_conversion(path):
                raise EncapError(f"Conversion declined for mismatched WAV: {path}")

            converted_path = temp_dir / f"{path.stem}.converted.wav"
            convert_to_match(path, converted_path, reference.wav_format)
            converted_source = load_wav_source(converted_path)
            if not formats_match(reference.wav_format, converted_source.wav_format):
                raise EncapError(f"Converted file still does not match the reference format: {path}")
            sources.append(WavSource(path=path, wav_format=converted_source.wav_format, data=converted_source.data))

        # Keep source data in memory while the temporary directory is alive.
        return list(sources)


def create_stitched_wav(
    source_dir: Path,
    output_dir: Path,
    output_name: str,
    prompt_for_conversion: ConversionPrompt,
    write_report: bool = False,
) -> StitchPlan:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name
    report_path = output_path.with_suffix(".markers.txt") if write_report else None
    sources = prepare_sources(source_dir, prompt_for_conversion)
    plan = build_stitch_plan(sources=sources, output_path=output_path, report_path=report_path)
    write_wav(plan)
    return plan
