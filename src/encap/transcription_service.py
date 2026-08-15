from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from .ffmpeg_tools import ensure_ffmpeg
from .models import AudioSourceEntry, TranscriptSegment
from .transcription_models import MODEL_BY_ID, TranscriptionModelStore
from .wav_tools import EncapError


APPLE_PROVIDER_ID = "apple-local"
TranscriptionProgress = Callable[[int, int, str], None]


def _tool_name(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def _tool_candidates(name: str) -> list[Path]:
    tool_name = _tool_name(name)
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / tool_name)
    source_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            source_root / ".build-tools" / tool_name,
            source_root / ".whisper-cpp" / "build" / "bin" / tool_name,
            source_root / ".whisper-cpp" / "build" / "bin" / "Release" / tool_name,
        ]
    )
    return candidates


def _resolve_tool(name: str, environment_variable: str) -> str:
    override = os.environ.get(environment_variable, "").strip()
    candidates = ([Path(override)] if override else []) + _tool_candidates(name)
    for candidate in candidates:
        if candidate.is_file() and (sys.platform == "win32" or os.access(candidate, os.X_OK)):
            return str(candidate)
    resolved = shutil.which(_tool_name(name)) or shutil.which(name)
    if resolved is not None:
        return resolved
    raise EncapError(f"The local transcription helper '{name}' is not available in this build.")


def ensure_whisper_cli() -> str:
    return _resolve_tool("whisper-cli", "ENCAP_WHISPER_CLI")


def ensure_apple_transcriber() -> str:
    if sys.platform != "darwin":
        raise EncapError("Apple On-Device transcription is available only on macOS.")
    return _resolve_tool("apple-transcriber", "ENCAP_APPLE_TRANSCRIBER")


def apple_transcription_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        ensure_apple_transcriber()
    except EncapError:
        return False
    return True


def parse_whisper_result(payload: bytes, *, time_offset: float = 0.0) -> list[TranscriptSegment]:
    try:
        document = json.loads(payload)
        transcription = document["transcription"]
    except (ValueError, TypeError, KeyError) as exc:
        raise EncapError("whisper.cpp returned an invalid transcription result.") from exc

    segments: list[TranscriptSegment] = []
    for item in transcription:
        try:
            offsets = item["offsets"]
            text = str(item["text"]).strip()
            start = time_offset + float(offsets["from"]) / 1000.0
            end = time_offset + float(offsets["to"]) / 1000.0
        except (TypeError, KeyError, ValueError) as exc:
            raise EncapError("whisper.cpp returned an invalid transcript segment.") from exc
        if text:
            segments.append(
                TranscriptSegment(
                    start_time_seconds=start,
                    end_time_seconds=max(end, start),
                    text=text,
                )
            )
    return segments


def parse_apple_result(payload: bytes, *, time_offset: float = 0.0) -> list[TranscriptSegment]:
    try:
        document = json.loads(payload)
        raw_segments = document["segments"]
    except (ValueError, TypeError, KeyError) as exc:
        raise EncapError("Apple Speech returned an invalid transcription result.") from exc

    words: list[TranscriptSegment] = []
    for item in raw_segments:
        try:
            text = str(item["text"]).strip()
            start = time_offset + float(item["start_seconds"])
            end = start + float(item["duration_seconds"])
        except (TypeError, KeyError, ValueError) as exc:
            raise EncapError("Apple Speech returned an invalid transcript segment.") from exc
        if text:
            words.append(
                TranscriptSegment(
                    start_time_seconds=start,
                    end_time_seconds=max(end, start),
                    text=text,
                )
            )
    return _group_apple_words(words)


def _group_apple_words(words: list[TranscriptSegment]) -> list[TranscriptSegment]:
    grouped: list[TranscriptSegment] = []
    current: TranscriptSegment | None = None
    for word in words:
        if current is None:
            current = TranscriptSegment(
                start_time_seconds=word.start_time_seconds,
                end_time_seconds=word.end_time_seconds,
                text=word.text,
            )
            continue
        gap = word.start_time_seconds - current.end_time_seconds
        if gap > 1.0 or current.end_time_seconds - current.start_time_seconds >= 10.0:
            grouped.append(current)
            current = TranscriptSegment(
                start_time_seconds=word.start_time_seconds,
                end_time_seconds=word.end_time_seconds,
                text=word.text,
            )
            continue
        separator = "" if word.text[:1] in ".,!?;:)" else " "
        current.text += separator + word.text
        current.end_time_seconds = word.end_time_seconds
        if current.text.endswith((".", "?", "!")):
            grouped.append(current)
            current = None
    if current is not None:
        grouped.append(current)
    return grouped


def _run_checked(command: list[str], *, description: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown error"
        raise EncapError(f"{description} failed: {detail}")
    return completed


def _transcribe_with_apple(source_path: Path, *, time_offset: float) -> list[TranscriptSegment]:
    helper = ensure_apple_transcriber()
    completed = _run_checked(
        [helper, "--input", str(source_path)],
        description="Apple On-Device transcription",
    )
    return parse_apple_result(completed.stdout.encode("utf-8"), time_offset=time_offset)


def _transcribe_with_whisper(
    source_path: Path,
    *,
    model_path: Path,
    language_code: str,
    time_offset: float,
) -> list[TranscriptSegment]:
    ffmpeg = ensure_ffmpeg()
    whisper_cli = ensure_whisper_cli()
    with tempfile.TemporaryDirectory(prefix="encap-transcription-") as directory_name:
        directory = Path(directory_name)
        normalized_audio = directory / "input.wav"
        output_prefix = directory / "transcript"
        _run_checked(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(normalized_audio),
            ],
            description="Audio preparation",
        )
        _run_checked(
            [
                whisper_cli,
                "--model",
                str(model_path),
                "--file",
                str(normalized_audio),
                "--language",
                language_code,
                "--output-json",
                "--output-file",
                str(output_prefix),
                "--no-prints",
            ],
            description="Whisper transcription",
        )
        result_path = output_prefix.with_suffix(".json")
        try:
            payload = result_path.read_bytes()
        except OSError as exc:
            raise EncapError("whisper.cpp did not create its JSON result.") from exc
    return parse_whisper_result(payload, time_offset=time_offset)


def transcribe_audio_sources(
    audio_sources: Iterable[AudioSourceEntry],
    provider_id: str,
    *,
    model_store: TranscriptionModelStore | None = None,
    progress: TranscriptionProgress | None = None,
) -> list[TranscriptSegment]:
    sources = list(audio_sources)
    if not sources:
        raise EncapError("Import audio before transcribing.")

    store = model_store or TranscriptionModelStore()
    model = None
    if provider_id != APPLE_PROVIDER_ID:
        model = MODEL_BY_ID.get(provider_id)
        if model is None:
            raise EncapError(f"Unknown transcription provider: {provider_id}")
        if not store.is_installed(model):
            raise EncapError(f"Download {model.name} before transcribing.")

    results: list[TranscriptSegment] = []
    time_offset = 0.0
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        if progress is not None:
            progress(index - 1, total, f"Transcribing {source.display_name}…")
        if provider_id == APPLE_PROVIDER_ID:
            results.extend(_transcribe_with_apple(source.source_path, time_offset=time_offset))
        else:
            assert model is not None
            results.extend(
                _transcribe_with_whisper(
                    source.source_path,
                    model_path=store.model_path(model),
                    language_code=model.language_code,
                    time_offset=time_offset,
                )
            )
        time_offset += source.duration_seconds
    if progress is not None:
        progress(total, total, "Transcription complete.")
    return results
