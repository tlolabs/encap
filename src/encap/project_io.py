from __future__ import annotations

import json
import math
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from .models import (
    AudioSourceEntry,
    ChapterEntry,
    EpisodeMetadata,
    ExportSettings,
    ProjectDocument,
    TranscriptSegment,
)
from .wav_tools import EncapError

PROJECT_SCHEMA_VERSION = 1
_MAX_PROJECT_ENTRIES = 4096
_MAX_PROJECT_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_PROJECT_MEMBER_BYTES = 32 * 1024 * 1024 * 1024
_MAX_PROJECT_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
_MAX_PROJECT_COMPRESSION_RATIO = 1000
_MIN_FREE_BYTES_AFTER_EXTRACTION = 2 * 1024 * 1024 * 1024
_EXTRACTION_CHUNK_BYTES = 1024 * 1024


def save_project(project: ProjectDocument, target_path: Path) -> Path:
    target_path = target_path.with_suffix(".encap")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project_title": project.project_title,
        "metadata": {
            "podcast_title": project.metadata.podcast_title,
            "episode_title": project.metadata.episode_title,
            "summary": project.metadata.summary,
            "artwork_stored_path": None,
        },
        "audio_sources": [],
        "chapters": [],
        "transcript_segments": [],
        "export_settings": {
            "output_format": project.export_settings.output_format,
            "quality_preset": project.export_settings.quality_preset,
            "bitrate": project.export_settings.quality_preset,
            "encoder": project.export_settings.encoder,
            "channels": project.export_settings.channels,
        },
    }

    temp_path: Path | None = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=target_path.parent,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, source in enumerate(project.audio_sources, start=1):
                if not source.source_path.exists():
                    raise EncapError(
                        f"Audio source is missing and cannot be saved: {source.source_path}"
                    )
                stored_path = f"audio/{index:03d}-{source.source_path.name}"
                archive.write(source.source_path, stored_path)
                manifest["audio_sources"].append(
                    {
                        "display_name": source.display_name,
                        "duration_seconds": source.duration_seconds,
                        "stored_path": stored_path,
                    }
                )

            if project.metadata.artwork_path is not None:
                if not project.metadata.artwork_path.exists():
                    raise EncapError(
                        "Artwork file is missing and cannot be saved: "
                        f"{project.metadata.artwork_path}"
                    )
                artwork_path = f"artwork/{project.metadata.artwork_path.name}"
                archive.write(project.metadata.artwork_path, artwork_path)
                manifest["metadata"]["artwork_stored_path"] = artwork_path

            for index, chapter in enumerate(project.chapters, start=1):
                chapter_record = {
                    "start_time_seconds": chapter.start_time_seconds,
                    "duration_seconds": chapter.duration_seconds,
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "link_url": chapter.link_url,
                    "image_stored_path": None,
                }
                if chapter.image_path is not None:
                    if not chapter.image_path.exists():
                        raise EncapError(
                            f"Chapter image is missing and cannot be saved: {chapter.image_path}"
                        )
                    image_path = f"chapters/{index:03d}-{chapter.image_path.name}"
                    archive.write(chapter.image_path, image_path)
                    chapter_record["image_stored_path"] = image_path
                manifest["chapters"].append(chapter_record)

            for segment in project.transcript_segments:
                manifest["transcript_segments"].append(
                    {
                        "start_time_seconds": segment.start_time_seconds,
                        "end_time_seconds": segment.end_time_seconds,
                        "speaker": segment.speaker,
                        "text": segment.text,
                    }
                )

            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True))

        with temp_path.open("rb") as completed_file:
            os.fsync(completed_file.fileno())
        os.replace(temp_path, target_path)
    except EncapError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise EncapError(f"Project could not be saved: {exc}") from exc
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    project.project_path = target_path
    return target_path


def load_project(project_path: Path, *, extraction_parent: Path | None = None) -> ProjectDocument:
    if not project_path.exists():
        raise EncapError(f"Project file does not exist: {project_path}")

    temp_dir = Path(tempfile.mkdtemp(prefix="encap-project-", dir=extraction_parent))
    try:
        with zipfile.ZipFile(project_path, "r") as archive:
            _safe_extract_archive(archive, temp_dir)
        return _load_extracted_project(project_path, temp_dir)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
            zipfile.BadZipFile, RuntimeError) as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise EncapError(f"Project could not be opened: {exc}") from exc
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _load_extracted_project(project_path: Path, temp_dir: Path) -> ProjectDocument:
    manifest_path = temp_dir / "manifest.json"
    if not manifest_path.exists():
        raise EncapError(f"{project_path} does not contain a manifest.json file.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    if manifest.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise EncapError(
            f"Unsupported project schema version: {manifest.get('schema_version')!r}."
        )

    metadata_blob = manifest["metadata"]
    metadata = EpisodeMetadata(
        podcast_title=metadata_blob.get("podcast_title", ""),
        episode_title=metadata_blob.get("episode_title", ""),
        summary=metadata_blob.get("summary", ""),
        artwork_path=_resolve_optional_path(temp_dir, metadata_blob.get("artwork_stored_path")),
        artwork_stored_path=metadata_blob.get("artwork_stored_path"),
    )

    audio_sources: list[AudioSourceEntry] = []
    for item in manifest["audio_sources"]:
        stored_path = item["stored_path"]
        source_path = _resolve_media_path(temp_dir, stored_path)
        audio_sources.append(
            AudioSourceEntry(
                source_path=source_path,
                display_name=item.get("display_name", source_path.name),
                duration_seconds=float(item.get("duration_seconds", 0.0)),
                stored_path=stored_path,
            )
        )

    chapters: list[ChapterEntry] = []
    for item in manifest["chapters"]:
        chapters.append(
            ChapterEntry(
                start_time_seconds=float(item.get("start_time_seconds", 0.0)),
                duration_seconds=float(item.get("duration_seconds", 0.0)),
                chapter_number=int(item.get("chapter_number", len(chapters) + 1)),
                title=item.get("title", ""),
                link_url=item.get("link_url", ""),
                image_path=_resolve_optional_path(temp_dir, item.get("image_stored_path")),
                image_stored_path=item.get("image_stored_path"),
            )
        )

    transcript_segments: list[TranscriptSegment] = []
    for item in manifest["transcript_segments"]:
        transcript_segments.append(
            TranscriptSegment(
                start_time_seconds=float(item.get("start_time_seconds", 0.0)),
                end_time_seconds=float(item.get("end_time_seconds", 0.0)),
                speaker=item.get("speaker", ""),
                text=item.get("text", ""),
            )
        )

    export_blob = manifest["export_settings"]
    output_format = str(export_blob.get("output_format", "mp3")).lower()
    if output_format == "m4a":
        output_format = "aac"
    channels = int(export_blob.get("channels", 2))
    default_encoder = "lame" if output_format == "mp3" else "ffmpeg"
    encoder = str(export_blob.get("encoder", default_encoder))
    encoder = {
        "ffmpeg_default": "ffmpeg",
        "lame_mp3_advanced": "lame",
    }.get(encoder, encoder)
    export_settings = ExportSettings(
        output_format=output_format,
        quality_preset=export_blob.get(
            "bitrate",
            export_blob.get("quality_preset", "160k" if channels == 1 else "320k"),
        ),
        encoder=encoder,
        channels=channels,
    )

    return ProjectDocument(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_title=manifest.get("project_title", metadata.episode_title or "Untitled"),
        audio_sources=audio_sources,
        metadata=metadata,
        chapters=chapters,
        transcript_segments=transcript_segments,
        export_settings=export_settings,
        project_path=project_path,
        working_dir=temp_dir,
    )


def cleanup_loaded_project(project: ProjectDocument) -> None:
    if project.working_dir is not None and project.working_dir.exists():
        shutil.rmtree(project.working_dir, ignore_errors=True)
        project.working_dir = None


def _resolve_optional_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    return _resolve_media_path(root, value)


def _resolve_media_path(root: Path, value: object) -> Path:
    path = _resolve_stored_path(root, value)
    if not path.is_file():
        raise EncapError(f"Project media is missing: {value}")
    return path


def _validate_manifest(manifest: object) -> None:
    """Reject malformed values before they reach UI controls or time arithmetic."""
    if not isinstance(manifest, dict):
        raise EncapError("The project manifest must be an object.")

    def record(value: object, name: str) -> dict:
        if not isinstance(value, dict):
            raise EncapError(f"Invalid project {name}.")
        return value

    def text_fields(item: dict, names: tuple[str, ...]) -> None:
        for name in names:
            if name in item and not isinstance(item[name], str):
                raise EncapError(f"Project {name} must be text.")

    def time_value(item: dict, name: str) -> float:
        value = item.get(name, 0.0)
        if isinstance(value, bool):
            raise EncapError(f"Invalid project {name}.")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise EncapError(f"Project {name} must be a finite, nonnegative number.")
        return number

    text_fields(manifest, ("project_title",))
    metadata = record(manifest.get("metadata"), "metadata")
    text_fields(metadata, ("podcast_title", "episode_title", "summary"))
    settings = record(manifest.get("export_settings"), "export settings")
    text_fields(settings, ("output_format", "quality_preset", "bitrate", "encoder"))
    for collection, times, texts in (
        ("audio_sources", ("duration_seconds",), ("display_name",)),
        ("chapters", ("start_time_seconds", "duration_seconds"), ("title", "link_url")),
        ("transcript_segments", ("start_time_seconds", "end_time_seconds"), ("speaker", "text")),
    ):
        items = manifest.get(collection)
        if not isinstance(items, list):
            raise EncapError(f"Project {collection} must be a list.")
        for item in items:
            item = record(item, collection)
            text_fields(item, texts)
            values = [time_value(item, name) for name in times]
            if collection == "transcript_segments" and values[1] < values[0]:
                raise EncapError("Transcript end time precedes its start time.")


def _safe_extract_archive(archive: zipfile.ZipFile, destination: Path) -> None:
    members = archive.infolist()
    if len(members) > _MAX_PROJECT_ENTRIES:
        raise EncapError("The project archive contains too many files.")

    seen: set[Path] = set()
    targets: dict[str, Path] = {}
    total_size = 0
    manifest_found = False
    for member in members:
        target = _resolve_stored_path(destination, member.filename)
        if target in seen:
            raise EncapError("The project archive contains duplicate paths.")
        seen.add(target)
        targets[member.filename] = target

        unix_mode = member.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise EncapError("The project archive contains an unsafe path.")
        file_type = stat.S_IFMT(unix_mode)
        if file_type and not (stat.S_ISREG(unix_mode) or stat.S_ISDIR(unix_mode)):
            raise EncapError("The project archive contains an unsafe file type.")

        if member.is_dir():
            continue
        if member.file_size < 0 or member.file_size > _MAX_PROJECT_MEMBER_BYTES:
            raise EncapError("A file in the project archive is too large.")
        total_size += member.file_size
        if total_size > _MAX_PROJECT_TOTAL_BYTES:
            raise EncapError("The project archive is too large to open safely.")
        if member.file_size and member.file_size > max(member.compress_size, 1) * _MAX_PROJECT_COMPRESSION_RATIO:
            raise EncapError("The project archive has an unsafe compression ratio.")
        if target == destination.resolve() / "manifest.json":
            manifest_found = True
            if member.file_size > _MAX_PROJECT_MANIFEST_BYTES:
                raise EncapError("The project manifest is too large.")

    if not manifest_found:
        raise EncapError("The project does not contain a manifest.json file.")

    destination.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(destination).free
    if total_size > max(0, free_bytes - _MIN_FREE_BYTES_AFTER_EXTRACTION):
        raise EncapError("There is not enough free space to open this project safely.")

    extracted_size = 0
    for member in members:
        target = targets[member.filename]
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        member_size = 0
        with archive.open(member, "r") as source, target.open("xb") as output:
            while True:
                chunk = source.read(_EXTRACTION_CHUNK_BYTES)
                if not chunk:
                    break
                member_size += len(chunk)
                extracted_size += len(chunk)
                if member_size > member.file_size or extracted_size > _MAX_PROJECT_TOTAL_BYTES:
                    raise EncapError("The project archive expanded beyond its declared size.")
                output.write(chunk)
        if member_size != member.file_size:
            raise EncapError("A file in the project archive has an invalid size.")


def _resolve_stored_path(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise EncapError("The project contains an unsafe stored path.")

    try:
        root_resolved = root.resolve()
        target = (root / value).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise EncapError("The project contains an unsafe stored path.") from exc

    if not target.is_relative_to(root_resolved):
        raise EncapError("The project contains an unsafe stored path.")
    return target
