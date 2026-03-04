from __future__ import annotations

import re
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
RecordingDate = tuple[int, int, int]

RECORDER_NAME_PATTERN = re.compile(
    r"^(?P<mm>\d{2})(?P<dd>\d{2})(?P<yyyy>\d{4})(?P<hh>\d{2})(?P<min>\d{2})(?P<ss>\d{2})_DN-?700R$",
    re.IGNORECASE,
)


def discover_wav_files(source_dir: Path) -> list[Path]:
    files = [
        path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() == ".wav"
    ]
    if not files:
        raise EncapError(f"No WAV files were found in {source_dir}.")
    return sort_wav_files(files)


def sort_wav_files(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=_wav_sort_key)


def discover_wav_groups(source_dir: Path) -> list[tuple[RecordingDate | None, list[Path]]]:
    wav_paths = discover_wav_files(source_dir)
    groups: dict[RecordingDate | None, list[Path]] = {}
    for path in wav_paths:
        parsed = parse_recorder_timestamp(path.stem)
        recording_date = parsed[:3] if parsed is not None else None
        groups.setdefault(recording_date, []).append(path)

    ordered: list[tuple[RecordingDate | None, list[Path]]] = []
    for recording_date in sorted((date for date in groups if date is not None)):
        ordered.append((recording_date, sort_wav_files(groups[recording_date])))
    if None in groups:
        ordered.append((None, sort_wav_files(groups[None])))
    return ordered


def build_date_output_name(recording_date: RecordingDate) -> str:
    month, day, year = recording_date
    return f"encap-{month}.{day}.{year % 100:02d}.wav"


def parse_recorder_timestamp(stem: str) -> tuple[int, int, int, int, int, int] | None:
    match = RECORDER_NAME_PATTERN.match(stem)
    if match is None:
        return None
    return (
        int(match.group("yyyy")),
        int(match.group("mm")),
        int(match.group("dd")),
        int(match.group("hh")),
        int(match.group("min")),
        int(match.group("ss")),
    )


def prepare_sources(
    source_dir: Path,
    prompt_for_conversion: ConversionPrompt,
) -> list[WavSource]:
    wav_paths = discover_wav_files(source_dir)
    return prepare_sources_for_paths(wav_paths=wav_paths, prompt_for_conversion=prompt_for_conversion)


def prepare_sources_for_paths(
    wav_paths: list[Path],
    prompt_for_conversion: ConversionPrompt,
) -> list[WavSource]:
    if not wav_paths:
        raise EncapError("No WAV files were selected for processing.")

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


def create_stitched_wav_for_paths(
    wav_paths: list[Path],
    output_dir: Path,
    output_name: str,
    prompt_for_conversion: ConversionPrompt,
    write_report: bool = False,
) -> StitchPlan:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name
    report_path = output_path.with_suffix(".markers.txt") if write_report else None
    sources = prepare_sources_for_paths(wav_paths=wav_paths, prompt_for_conversion=prompt_for_conversion)
    plan = build_stitch_plan(sources=sources, output_path=output_path, report_path=report_path)
    write_wav(plan)
    return plan


def create_stitched_wavs_by_date(
    source_dir: Path,
    output_dir: Path,
    prompt_for_conversion: ConversionPrompt,
    write_report: bool = False,
) -> list[StitchPlan]:
    plans: list[StitchPlan] = []
    for recording_date, group_paths in discover_wav_groups(source_dir):
        if recording_date is None:
            output_name = "encap-unsorted.wav"
        else:
            output_name = build_date_output_name(recording_date)
        plans.append(
            create_stitched_wav_for_paths(
                wav_paths=group_paths,
                output_dir=output_dir,
                output_name=output_name,
                prompt_for_conversion=prompt_for_conversion,
                write_report=write_report,
            )
        )
    return plans


def create_stitched_wav(
    source_dir: Path,
    output_dir: Path,
    output_name: str,
    prompt_for_conversion: ConversionPrompt,
    write_report: bool = False,
) -> StitchPlan:
    wav_paths = discover_wav_files(source_dir)
    return create_stitched_wav_for_paths(
        wav_paths=wav_paths,
        output_dir=output_dir,
        output_name=output_name,
        prompt_for_conversion=prompt_for_conversion,
        write_report=write_report,
    )


def _wav_sort_key(path: Path) -> tuple[int, tuple[int, int, int, int, int, int], str]:
    parsed = parse_recorder_timestamp(path.stem)
    if parsed is not None:
        return (0, parsed, path.name.lower())
    return (1, (0, 0, 0, 0, 0, 0), path.name.lower())
