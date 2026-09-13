from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from encap.export_tools import export_project
from encap.models import (
    AudioSourceEntry,
    ChapterEntry,
    EpisodeMetadata,
    ExportSettings,
    ProjectDocument,
    TranscriptSegment,
)
from encap.project_io import load_project, save_project
from encap.service import build_project_document
from encap.transcription_models import TranscriptionModelStore
from encap.transcription_service import (
    APPLE_PROVIDER_ID,
    apple_transcription_available,
    transcribe_audio_sources,
)
from encap.wav_tools import EncapError


def _optional_path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def project_to_payload(project: ProjectDocument) -> dict[str, object]:
    return {
        "schema_version": project.schema_version,
        "project_title": project.project_title,
        "source_folder": str(project.source_folder) if project.source_folder else None,
        "project_path": str(project.project_path) if project.project_path else None,
        "working_dir": str(project.working_dir) if project.working_dir else None,
        "metadata": {
            "podcast_title": project.metadata.podcast_title,
            "episode_title": project.metadata.episode_title,
            "summary": project.metadata.summary,
            "artwork_path": str(project.metadata.artwork_path) if project.metadata.artwork_path else None,
        },
        "audio_sources": [
            {
                "source_path": str(source.source_path),
                "display_name": source.display_name,
                "duration_seconds": source.duration_seconds,
            }
            for source in project.audio_sources
        ],
        "chapters": [
            {
                "id": chapter.id,
                "start_time_seconds": chapter.start_time_seconds,
                "duration_seconds": chapter.duration_seconds,
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "link_url": chapter.link_url,
                "image_path": str(chapter.image_path) if chapter.image_path else None,
            }
            for chapter in project.chapters
        ],
        "transcript_segments": [
            {
                "id": f"{index}-{segment.start_time_seconds:.6f}",
                "start_time_seconds": segment.start_time_seconds,
                "end_time_seconds": segment.end_time_seconds,
                "speaker": segment.speaker,
                "text": segment.text,
            }
            for index, segment in enumerate(project.transcript_segments)
        ],
        "export_settings": {
            "output_format": project.export_settings.output_format,
            "quality_preset": project.export_settings.quality_preset,
            "encoder": project.export_settings.encoder,
            "channels": project.export_settings.channels,
        },
    }


def project_from_payload(payload: dict[str, object]) -> ProjectDocument:
    metadata_blob = payload.get("metadata") or {}
    export_blob = payload.get("export_settings") or {}
    assert isinstance(metadata_blob, dict)
    assert isinstance(export_blob, dict)

    audio_sources = []
    for item in payload.get("audio_sources") or []:
        assert isinstance(item, dict)
        audio_sources.append(
            AudioSourceEntry(
                source_path=Path(str(item["source_path"])),
                display_name=str(item.get("display_name", "")),
                duration_seconds=float(item.get("duration_seconds", 0.0)),
            )
        )

    chapters = []
    for item in payload.get("chapters") or []:
        assert isinstance(item, dict)
        chapters.append(
            ChapterEntry(
                start_time_seconds=float(item.get("start_time_seconds", 0.0)),
                duration_seconds=float(item.get("duration_seconds", 0.0)),
                chapter_number=int(item.get("chapter_number", len(chapters) + 1)),
                title=str(item.get("title", "")),
                link_url=str(item.get("link_url", "")),
                image_path=_optional_path(item.get("image_path")),
            )
        )

    transcript_segments = []
    for item in payload.get("transcript_segments") or []:
        assert isinstance(item, dict)
        transcript_segments.append(
            TranscriptSegment(
                start_time_seconds=float(item.get("start_time_seconds", 0.0)),
                end_time_seconds=float(item.get("end_time_seconds", 0.0)),
                speaker=str(item.get("speaker", "")),
                text=str(item.get("text", "")),
            )
        )

    return ProjectDocument(
        schema_version=int(payload.get("schema_version", 1)),
        project_title=str(payload.get("project_title", "Untitled")),
        source_folder=_optional_path(payload.get("source_folder")),
        project_path=_optional_path(payload.get("project_path")),
        metadata=EpisodeMetadata(
            podcast_title=str(metadata_blob.get("podcast_title", "")),
            episode_title=str(metadata_blob.get("episode_title", "")),
            summary=str(metadata_blob.get("summary", "")),
            artwork_path=_optional_path(metadata_blob.get("artwork_path")),
        ),
        audio_sources=audio_sources,
        chapters=chapters,
        transcript_segments=transcript_segments,
        export_settings=ExportSettings(
            output_format=str(export_blob.get("output_format", "mp3")),
            quality_preset=str(export_blob.get("quality_preset", "320k")),
            encoder=str(export_blob.get("encoder", "lame")),
            channels=int(export_blob.get("channels", 2)),
        ),
    )


def _read_project(path: Path) -> ProjectDocument:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EncapError("The native project payload is invalid.")
    try:
        return project_from_payload(payload)
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        raise EncapError("The native project payload is invalid.") from exc


def _providers() -> list[dict[str, object]]:
    providers: list[dict[str, object]] = []
    if apple_transcription_available():
        providers.append(
            {
                "id": APPLE_PROVIDER_ID,
                "name": "Apple On-Device",
                "detail": "Apple Speech · on this Mac",
            }
        )
    store = TranscriptionModelStore()
    for provider in store.available_providers(verify_integrity=False):
        providers.append(
            {
                "id": provider.provider_id,
                "name": provider.name,
                "detail": f"{provider.engine} · {provider.source_name}",
            }
        )
    return providers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="encap-engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("folder", type=Path)

    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("project", type=Path)
    open_parser.add_argument("--extraction-parent", type=Path)

    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("payload", type=Path)
    save_parser.add_argument("project", type=Path)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("payload", type=Path)
    export_parser.add_argument("output", type=Path)

    transcribe_parser = subparsers.add_parser("transcribe")
    transcribe_parser.add_argument("payload", type=Path)
    transcribe_parser.add_argument("provider")

    subparsers.add_parser("providers")
    return parser


def run(argv: list[str] | None = None) -> object:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        return project_to_payload(build_project_document(args.folder, lambda _path: True))
    if args.command == "open":
        return project_to_payload(load_project(args.project, extraction_parent=args.extraction_parent))
    if args.command == "save":
        project = _read_project(args.payload)
        saved_path = save_project(project, args.project)
        return {"path": str(saved_path)}
    if args.command == "export":
        project = _read_project(args.payload)
        output_path = export_project(
            project,
            args.output.parent,
            lambda _path: True,
            output_path=args.output,
        )
        return {"path": str(output_path)}
    if args.command == "transcribe":
        project = _read_project(args.payload)
        project.transcript_segments = transcribe_audio_sources(
            project.audio_sources,
            args.provider,
            model_store=TranscriptionModelStore(),
        )
        return project_to_payload(project)["transcript_segments"]
    if args.command == "providers":
        return _providers()
    raise AssertionError(f"Unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(argv)
    except (EncapError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
