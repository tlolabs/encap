from __future__ import annotations

import re
import tempfile
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
from collections.abc import Callable
from pathlib import Path

from .ffmpeg_tools import convert_to_match
from .models import (
    AudioSourceEntry,
    ChapterEntry,
    EpisodeMetadata,
    ExportSettings,
    ProjectDocument,
    StitchPlan,
    WavSource,
)
from .wav_tools import (
    AUDIO_FILE_EXTENSIONS,
    EncapError,
    build_stitch_plan,
    formats_match,
    load_audio_source,
    load_wav_source,
    read_source_pcm,
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


def discover_audio_files(source_dir: Path) -> list[Path]:
    files = [
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_FILE_EXTENSIONS
    ]
    if not files:
        raise EncapError(f"No WAV or AIFF files were found in {source_dir}.")
    return sort_wav_files(files)


def sort_wav_files(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=audio_path_sort_key)


def audio_path_sort_key(path: Path) -> tuple:
    parsed = parse_recorder_timestamp(path.stem)
    natural_name = tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"([0-9]+)", path.name.lower())
    )
    if parsed is not None:
        return (0, parsed, natural_name, path.name)
    return (1, (0, 0, 0, 0, 0, 0), natural_name, path.name)


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
    year, month, day = recording_date
    return f"encap-{month}.{day}.{year % 100:02d}.wav"


def infer_episode_title(recording_date: RecordingDate | None, fallback_name: str) -> str:
    if recording_date is None:
        return fallback_name
    year, month, day = recording_date
    return f"{year:04d}-{month:02d}-{day:02d} Aircheck"


def parse_recorder_timestamp(stem: str) -> tuple[int, int, int, int, int, int] | None:
    match = RECORDER_NAME_PATTERN.match(stem)
    if match is None:
        return None
    timestamp = (
        int(match.group("yyyy")),
        int(match.group("mm")),
        int(match.group("dd")),
        int(match.group("hh")),
        int(match.group("min")),
        int(match.group("ss")),
    )
    try:
        datetime(*timestamp)
    except ValueError:
        return None
    return timestamp


def build_project_document(
    source_dir: Path,
    prompt_for_conversion: ConversionPrompt,
) -> ProjectDocument:
    wav_paths = discover_audio_files(source_dir)
    recording_date = parse_recorder_timestamp(wav_paths[0].stem)
    audio_entries = build_audio_source_entries(wav_paths=wav_paths)
    chapters = build_chapter_entries(audio_entries)
    fallback_name = wav_paths[0].stem
    episode_title = infer_episode_title(recording_date[:3] if recording_date is not None else None, fallback_name)
    source_channels = load_audio_source(wav_paths[0]).wav_format.channels
    output_channels = 1 if source_channels == 1 else 2
    highest_mp3_bitrate = "160k" if output_channels == 1 else "320k"
    return ProjectDocument(
        project_title=episode_title,
        source_folder=source_dir,
        audio_sources=audio_entries,
        chapters=chapters,
        metadata=EpisodeMetadata(episode_title=episode_title),
        export_settings=ExportSettings(
            output_format="mp3",
            quality_preset=highest_mp3_bitrate,
            encoder="lame",
            channels=output_channels,
        ),
    )


def build_audio_source_entries(wav_paths: list[Path]) -> list[AudioSourceEntry]:
    if not wav_paths:
        raise EncapError("No WAV files were selected for processing.")

    entries: list[AudioSourceEntry] = []
    for path in wav_paths:
        source = load_audio_source(path)
        duration_seconds = source.frame_count / source.wav_format.sample_rate
        entries.append(
            AudioSourceEntry(
                source_path=path,
                display_name=path.name,
                duration_seconds=duration_seconds,
            )
        )
    return entries


def build_chapter_entries(audio_sources: list[AudioSourceEntry]) -> list[ChapterEntry]:
    chapters: list[ChapterEntry] = []
    running_time = 0.0
    for index, source in enumerate(audio_sources, start=1):
        chapters.append(
            ChapterEntry(
                start_time_seconds=running_time,
                duration_seconds=source.duration_seconds,
                chapter_number=index,
                title=f"Chapter {index}",
            )
        )
        running_time += source.duration_seconds
    return chapters


def update_project_document_metadata(
    project: ProjectDocument,
    podcast_title: str = "",
    episode_title: str | None = None,
    summary: str = "",
) -> ProjectDocument:
    if episode_title is None:
        episode_title = project.project_title
    project.metadata.podcast_title = podcast_title
    project.metadata.episode_title = episode_title
    project.metadata.summary = summary
    return project


def prepare_sources(
    source_dir: Path,
    prompt_for_conversion: ConversionPrompt,
) -> list[WavSource]:
    wav_paths = discover_wav_files(source_dir)
    return prepare_sources_for_paths(wav_paths=wav_paths, prompt_for_conversion=prompt_for_conversion)


def prepare_sources_for_paths(
    wav_paths: list[Path],
    prompt_for_conversion: ConversionPrompt,
    *,
    working_dir: Path | None = None,
) -> list[WavSource]:
    if not wav_paths:
        raise EncapError("No WAV files were selected for processing.")

    sources: list[WavSource] = []
    reference = load_audio_source(wav_paths[0])
    sources.append(reference)

    temporary = tempfile.TemporaryDirectory(prefix="encap-") if working_dir is None else nullcontext(working_dir)
    with temporary as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        for index, path in enumerate(wav_paths[1:]):
            source = load_audio_source(path)
            if formats_match(reference.wav_format, source.wav_format):
                sources.append(source)
                continue

            if not prompt_for_conversion(path):
                raise EncapError(f"Conversion declined for mismatched WAV: {path}")

            converted_path = temp_dir / f"{index}-{path.stem}.converted.wav"
            convert_to_match(path, converted_path, reference.wav_format)
            converted_source = load_wav_source(converted_path)
            if not formats_match(reference.wav_format, converted_source.wav_format):
                raise EncapError(f"Converted file still does not match the reference format: {path}")
            sources.append(
                WavSource(
                    path=path,
                    wav_format=converted_source.wav_format,
                    data=read_source_pcm(converted_source) if working_dir is None else None,
                    data_path=converted_path if working_dir is not None else None,
                    data_offset=converted_source.data_offset if working_dir is not None else 0,
                    data_size=converted_source.data_size,
                )
            )

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
    with tempfile.TemporaryDirectory(prefix="encap-stitch-") as directory:
        sources = prepare_sources_for_paths(
            wav_paths=wav_paths, prompt_for_conversion=prompt_for_conversion,
            working_dir=Path(directory),
        )
        plan = build_stitch_plan(sources=sources, output_path=output_path, report_path=report_path)
        write_wav(plan)
        # A returned plan must remain readable after conversion files are removed.
        data_offset = load_wav_source(output_path).data_offset
        retained_sources = []
        for source in sources:
            if source.data_path is not None and source.data_path.parent == Path(directory):
                source = replace(source, data_path=output_path, data_offset=data_offset)
            retained_sources.append(source)
            data_offset += source.data_size
        plan = replace(plan, sources=retained_sources)
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
    wav_paths = discover_audio_files(source_dir)
    return create_stitched_wav_for_paths(
        wav_paths=wav_paths,
        output_dir=output_dir,
        output_name=output_name,
        prompt_for_conversion=prompt_for_conversion,
        write_report=write_report,
    )
