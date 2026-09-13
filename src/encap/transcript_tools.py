from __future__ import annotations

from pathlib import Path

from .file_tools import atomic_output
from .models import ProjectDocument, TranscriptSegment


def export_transcript_txt(project: ProjectDocument, output_path: Path) -> Path:
    lines: list[str] = []
    for segment in project.transcript_segments:
        prefix = f"{segment.speaker}: " if segment.speaker.strip() else ""
        lines.append(f"{prefix}{segment.text}".rstrip())
    with atomic_output(output_path) as temporary:
        temporary.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return output_path


def export_transcript_srt(project: ProjectDocument, output_path: Path) -> Path:
    blocks: list[str] = []
    for index, segment in enumerate(project.transcript_segments, start=1):
        content = segment.text.strip()
        if segment.speaker.strip():
            content = f"{segment.speaker}: {content}"
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_srt_time(segment.start_time_seconds)} --> {_format_srt_time(segment.end_time_seconds)}",
                    content,
                ]
            )
        )
    with atomic_output(output_path) as temporary:
        temporary.write_text("\n\n".join(blocks).strip() + "\n", encoding="utf-8")
    return output_path


def parse_transcript_text(raw_text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        speaker = ""
        text = line
        if ":" in line:
            candidate_speaker, candidate_text = line.split(":", 1)
            if candidate_speaker.strip() and candidate_text.strip():
                speaker = candidate_speaker.strip()
                text = candidate_text.strip()
        start_time = float(len(segments) * 5)
        end_time = start_time + 5.0
        segments.append(
            TranscriptSegment(
                start_time_seconds=start_time,
                end_time_seconds=end_time,
                speaker=speaker,
                text=text,
            )
        )
    return segments


def _format_srt_time(value: float) -> str:
    total_milliseconds = int(round(max(value, 0.0) * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
