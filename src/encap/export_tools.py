from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .file_tools import atomic_output
from .ffmpeg_tools import ensure_ffmpeg, ensure_lame
from .models import ProjectDocument
from .service import create_stitched_wav_for_paths
from .wav_tools import EncapError


BITRATE_OPTIONS: dict[str, dict[int, tuple[str, ...]]] = {
    "mp3": {
        2: ("96k", "128k", "160k", "192k", "224k", "256k", "320k"),
        1: ("64k", "80k", "96k", "112k", "128k", "160k"),
    },
    "aac": {
        2: ("64k", "96k", "128k", "160k", "192k", "256k", "320k"),
        1: ("48k", "64k", "80k", "96k", "128k", "160k"),
    },
}

# Compatibility for callers that still import the old flat preset map.
QUALITY_PRESETS: dict[str, dict[str, str]] = {
    format_name: {
        bitrate: bitrate
        for channel_options in format_options.values()
        for bitrate in channel_options
    }
    for format_name, format_options in BITRATE_OPTIONS.items()
}
QUALITY_PRESETS["m4a"] = QUALITY_PRESETS["aac"]


def normalize_output_format(value: str) -> str:
    normalized = str(value).strip().lower()
    return "aac" if normalized == "m4a" else normalized


def normalize_encoder(value: str) -> str:
    normalized = str(value).strip().lower()
    return {
        "ffmpeg_default": "ffmpeg",
        "lame_mp3_advanced": "lame",
    }.get(normalized, normalized)


def export_project(
    project: ProjectDocument,
    output_dir: Path,
    prompt_for_conversion,
    *,
    output_path: Path | None = None,
) -> Path:
    validate_project_for_export(project)
    if output_path is None:
        output_path = output_dir / (
            f"{project.output_basename()}{project.export_settings.output_extension()}"
        )
    else:
        output_path = Path(output_path)
        output_dir = output_path.parent
    media_paths = [entry.source_path for entry in project.audio_sources]
    media_paths += [path for path in [project.metadata.artwork_path, project.project_path] if path]
    if any(output_path.resolve() == path.resolve() for path in media_paths):
        raise EncapError("The export destination must not overwrite project media or the project file.")
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = ensure_ffmpeg()

    with tempfile.TemporaryDirectory(prefix="encap-export-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        wav_name = f"{project.output_basename()}.wav"
        stitched_plan = create_stitched_wav_for_paths(
            wav_paths=[entry.source_path for entry in project.audio_sources],
            output_dir=temp_dir,
            output_name=wav_name,
            prompt_for_conversion=prompt_for_conversion,
            write_report=False,
        )
        metadata_path = temp_dir / "metadata.ffmeta"
        metadata_path.write_text(build_ffmetadata(project), encoding="utf-8")
        encoder = normalize_encoder(project.export_settings.encoder)
        format_name = normalize_output_format(project.export_settings.output_format)
        if encoder == "lame" and format_name == "mp3":
            intermediate_audio = export_mp3_with_lame(
                project=project,
                stitched_wav=stitched_plan.output_path,
                temp_dir=temp_dir,
            )
        else:
            intermediate_audio = stitched_plan.output_path

        with atomic_output(output_path) as temporary_output:
            command = build_ffmpeg_export_command(
                ffmpeg=ffmpeg,
                project=project,
                audio_input=intermediate_audio,
                metadata_input=metadata_path,
                output_path=temporary_output,
            )
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode != 0:
                raise EncapError(
                    "Final export failed.\n"
                    f"Command: {' '.join(command)}\n"
                    f"stderr:\n{completed.stderr.strip()}"
                )

    return output_path


def validate_project_for_export(project: ProjectDocument) -> None:
    if not project.audio_sources:
        raise EncapError("Import audio before exporting.")
    if not project.metadata.podcast_title.strip():
        raise EncapError("Podcast title is required.")
    if not project.metadata.episode_title.strip():
        raise EncapError("Episode title is required.")
    format_name = normalize_output_format(project.export_settings.output_format)
    encoder = normalize_encoder(project.export_settings.encoder)
    channels = project.export_settings.channels
    bitrate = project.export_settings.quality_preset
    if format_name not in {"mp3", "aac"}:
        raise EncapError(f"Unsupported output format: {project.export_settings.output_format}")
    if channels not in {1, 2}:
        raise EncapError(f"Unsupported channel count: {channels}")
    if bitrate not in BITRATE_OPTIONS[format_name][channels]:
        raise EncapError(
            f"Unsupported {format_name.upper()} bitrate for "
            f"{'mono' if channels == 1 else 'stereo'}: {bitrate}"
        )
    valid_encoders = {"ffmpeg", "lame"} if format_name == "mp3" else {"ffmpeg", "audio_toolbox"}
    if encoder not in valid_encoders:
        raise EncapError(
            f"The {encoder or 'selected'} encoder does not support {format_name.upper()}."
        )
    if not project.chapters:
        raise EncapError("At least one chapter is required.")
    if project.metadata.artwork_path is not None and not project.metadata.artwork_path.is_file():
        raise EncapError(f"Episode artwork is missing: {project.metadata.artwork_path}")
    previous_start = -1.0
    for chapter in project.chapters:
        start = chapter.start_time_seconds
        duration = chapter.duration_seconds
        if (not math.isfinite(start) or not math.isfinite(duration)
                or start < 0 or duration <= 0 or start < previous_start
                or not math.isfinite((start + duration) * 1000)):
            raise EncapError("Chapter times must be finite, nonnegative, in order, and have positive durations.")
        previous_start = start
        if not chapter.title.strip():
            raise EncapError("Every chapter must have a title.")
        if chapter.link_url.strip() and "://" not in chapter.link_url:
            raise EncapError(f"Chapter link must be a full URL: {chapter.link_url}")
    chapters_with_images = [
        str(chapter.chapter_number)
        for chapter in project.chapters
        if chapter.image_path is not None
    ]
    if chapters_with_images:
        chapter_list = ", ".join(chapters_with_images)
        raise EncapError(
            "Chapter-specific artwork cannot be embedded in MP3 or M4A exports "
            f"(chapter{'s' if len(chapters_with_images) != 1 else ''} {chapter_list}). "
            "Remove the chapter images before exporting. Episode artwork is still supported."
        )


def build_ffmetadata(project: ProjectDocument) -> str:
    lines = [
        ";FFMETADATA1",
        f"title={_escape_metadata(project.metadata.episode_title)}",
        f"album={_escape_metadata(project.metadata.podcast_title)}",
        f"artist={_escape_metadata(project.metadata.podcast_title)}",
        f"comment={_escape_metadata(project.metadata.summary)}",
    ]
    for chapter in project.chapters:
        start_ms = int(round(chapter.start_time_seconds * 1000))
        end_ms = int(round((chapter.start_time_seconds + chapter.duration_seconds) * 1000))
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={_escape_metadata(chapter.title)}",
            ]
        )
        if chapter.link_url.strip():
            lines.append(f"url={_escape_metadata(chapter.link_url)}")
    return "\n".join(lines) + "\n"


def build_ffmpeg_export_command(
    ffmpeg: str,
    project: ProjectDocument,
    audio_input: Path,
    metadata_input: Path,
    output_path: Path,
) -> list[str]:
    format_name = normalize_output_format(project.export_settings.output_format)
    encoder = normalize_encoder(project.export_settings.encoder)
    bitrate = project.export_settings.quality_preset
    channels = project.export_settings.channels
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(audio_input),
        "-i",
        str(metadata_input),
    ]
    has_artwork = project.metadata.artwork_path is not None and project.metadata.artwork_path.exists()
    if has_artwork:
        command.extend(["-i", str(project.metadata.artwork_path)])

    command.extend(
        [
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-map",
            "0:a",
        ]
    )
    if has_artwork:
        command.extend(["-map", "2:v"])

    if format_name == "mp3":
        if audio_input.suffix.lower() == ".mp3":
            command.extend(["-c:a", "copy"])
        else:
            command.extend(
                [
                    "-c:a",
                    "libmp3lame",
                    "-compression_level",
                    "0",
                    "-ac",
                    str(channels),
                    "-b:a",
                    bitrate,
                ]
            )
        if has_artwork:
            command.extend(
                [
                    "-c:v",
                    "mjpeg",
                    "-id3v2_version",
                    "3",
                    "-metadata:s:v",
                    "title=Album cover",
                    "-metadata:s:v",
                    "comment=Cover (front)",
                    "-disposition:v",
                    "attached_pic",
                ]
            )
    else:
        if audio_input.suffix.lower() == ".m4a":
            command.extend(["-c:a", "copy"])
        else:
            codec = "aac_at" if encoder == "audio_toolbox" else "aac"
            command.extend(["-c:a", codec, "-ac", str(channels), "-b:a", bitrate])
            if encoder == "audio_toolbox":
                # Highest AudioToolbox codec-quality setting. FFmpeg's wrapper
                # uses AudioConverterNew, so macOS selects the installed Apple
                # component rather than accepting a hardware selector.
                command.extend(["-aac_at_mode", "cbr", "-aac_at_quality", "0"])
            else:
                command.extend(["-aac_coder", "twoloop"])
        if has_artwork:
            command.extend(["-c:v", "copy", "-disposition:v", "attached_pic"])

    command.append(str(output_path))
    return command


def export_mp3_with_lame(
    project: ProjectDocument,
    stitched_wav: Path,
    temp_dir: Path,
) -> Path:
    lame = ensure_lame()
    bitrate = project.export_settings.quality_preset.rstrip("k")
    channels = project.export_settings.channels
    output_path = temp_dir / "lame-encoded.mp3"
    _run_lame(lame, stitched_wav, output_path, bitrate, channels)
    return output_path


def _run_lame(
    lame: str,
    wav_path: Path,
    mp3_path: Path,
    bitrate: str,
    channels: int,
) -> None:
    command = [
        lame,
        "-q",
        "0",
        "-b",
        bitrate,
        "-m",
        "m" if channels == 1 else "j",
        str(wav_path),
        str(mp3_path),
    ]
    environment = os.environ.copy()
    bundled_libraries = Path(lame).resolve().parent / "lame-libs"
    if bundled_libraries.is_dir() and sys.platform.startswith("linux"):
        existing = environment.get("LD_LIBRARY_PATH", "")
        environment["LD_LIBRARY_PATH"] = (
            str(bundled_libraries)
            if not existing
            else f"{bundled_libraries}{os.pathsep}{existing}"
        )
    completed = subprocess.run(command, capture_output=True, text=True, env=environment)
    if completed.returncode != 0:
        raise EncapError(
            "LAME encoding failed.\n"
            f"Command: {' '.join(command)}\n"
            f"stderr:\n{completed.stderr.strip()}"
        )


def _escape_metadata(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", "\\\n")
    )
