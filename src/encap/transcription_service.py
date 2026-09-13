from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from .ffmpeg_tools import ensure_ffmpeg
from .models import AudioSourceEntry, TranscriptSegment
from .transcription_models import (
    MODEL_BY_ID,
    SHARED_PROVIDER_IDS,
    WHISPER_CPP_ENGINE,
    WHISPERKIT_ENGINE,
    SharedModelVerificationError,
    TranscriptionModelStore,
    TranscriptionProvider,
    verify_shared_model,
)
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


def ensure_whisperkit_transcriber() -> str:
    if sys.platform != "darwin":
        raise EncapError("WhisperKit transcription is available only on macOS.")
    return _resolve_tool("whisperkit-transcriber", "ENCAP_WHISPERKIT_TRANSCRIBER")


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

    if not isinstance(transcription, list):
        raise EncapError("whisper.cpp returned an invalid transcription result.")
    segments: list[TranscriptSegment] = []
    for item in transcription:
        try:
            offsets = item["offsets"]
            text = str(item["text"]).strip()
            start = time_offset + float(offsets["from"]) / 1000.0
            end = time_offset + float(offsets["to"]) / 1000.0
        except (TypeError, KeyError, ValueError) as exc:
            raise EncapError("whisper.cpp returned an invalid transcript segment.") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < 0:
            raise EncapError("The transcription engine returned an invalid segment time.")
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

    if not isinstance(raw_segments, list):
        raise EncapError("Apple Speech returned an invalid transcription result.")
    words: list[TranscriptSegment] = []
    for item in raw_segments:
        try:
            text = str(item["text"]).strip()
            start = time_offset + float(item["start_seconds"])
            end = start + float(item["duration_seconds"])
        except (TypeError, KeyError, ValueError) as exc:
            raise EncapError("Apple Speech returned an invalid transcript segment.") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < 0:
            raise EncapError("The transcription engine returned an invalid segment time.")
        if text:
            words.append(
                TranscriptSegment(
                    start_time_seconds=start,
                    end_time_seconds=max(end, start),
                    text=text,
                )
            )
    return _group_apple_words(words)


def parse_whisperkit_result(
    payload: bytes,
    *,
    time_offset: float = 0.0,
) -> list[TranscriptSegment]:
    try:
        document = json.loads(payload)
        raw_segments = document["segments"]
    except (ValueError, TypeError, KeyError) as exc:
        raise EncapError("WhisperKit returned an invalid transcription result.") from exc

    if not isinstance(raw_segments, list):
        raise EncapError("WhisperKit returned an invalid transcription result.")
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        try:
            text = str(item["text"]).strip()
            start = time_offset + float(item["start_seconds"])
            end = time_offset + float(item["end_seconds"])
        except (TypeError, KeyError, ValueError) as exc:
            raise EncapError("WhisperKit returned an invalid transcript segment.") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < 0:
            raise EncapError("The transcription engine returned an invalid segment time.")
        if text:
            segments.append(
                TranscriptSegment(
                    start_time_seconds=start,
                    end_time_seconds=max(end, start),
                    text=text,
                )
            )
    return segments


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


def _run_checked(
    command: list[str],
    *,
    description: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, env=environment)
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
        command = [
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
        ]
        try:
            _run_checked(command, description="Whisper transcription")
        except EncapError as exc:
            # Metal can fail under memory pressure before inference begins. The
            # same verified model remains usable through Accelerate on the CPU.
            if sys.platform != "darwin" or not any(
                marker in str(exc)
                for marker in ("ggml_metal_buffer_init", "failed to allocate buffer")
            ):
                raise
            _run_checked(command + ["--no-gpu"], description="Whisper transcription")
        result_path = output_prefix.with_suffix(".json")
        try:
            payload = result_path.read_bytes()
        except OSError as exc:
            raise EncapError("whisper.cpp did not create its JSON result.") from exc
    return parse_whisper_result(payload, time_offset=time_offset)


def _transcribe_with_whisperkit(
    source_path: Path,
    *,
    model_path: Path,
    tokenizer_path: Path,
    language_code: str,
    time_offset: float,
) -> list[TranscriptSegment]:
    ffmpeg = ensure_ffmpeg()
    helper = ensure_whisperkit_transcriber()
    with tempfile.TemporaryDirectory(prefix="encap-whisperkit-") as directory_name:
        directory = Path(directory_name)
        normalized_audio = directory / "input.wav"
        private_tokenizer = directory / "tokenizer"
        try:
            private_tokenizer.mkdir()
            for filename in ("tokenizer.json", "tokenizer_config.json", "config.json"):
                shutil.copy2(tokenizer_path / filename, private_tokenizer / filename)
        except OSError as exc:
            raise EncapError(
                "The shared Whisper Transcription tokenizer is incomplete or unreadable."
            ) from exc
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
        command = [
            helper,
            "--model",
            str(model_path),
            "--tokenizer",
            str(private_tokenizer),
            "--input",
            str(normalized_audio),
        ]
        if language_code != "auto":
            command.extend(["--language", language_code])
        environment = os.environ.copy()
        # Shared-model transcription must remain local. If tokenizer parsing
        # unexpectedly fails, make WhisperKit's network fallback fail closed.
        environment["HF_ENDPOINT"] = "http://127.0.0.1:9"
        completed = _run_checked(
            command,
            description="WhisperKit transcription",
            environment=environment,
        )
    return parse_whisperkit_result(completed.stdout.encode("utf-8"), time_offset=time_offset)


def _verify_shared_model(provider: TranscriptionProvider) -> None:
    try:
        verify_shared_model(provider)
    except SharedModelVerificationError as exc:
        raise EncapError(str(exc)) from exc


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
    provider = None
    if provider_id != APPLE_PROVIDER_ID:
        provider = store.provider(provider_id, verify_integrity=True)
        if provider is None and (
            provider_id in SHARED_PROVIDER_IDS or provider_id in MODEL_BY_ID
        ):
            available_fallbacks = store.available_providers(verify_integrity=True)
            selected_id = store.selected_model_id()
            provider = next(
                (
                    fallback
                    for fallback in available_fallbacks
                    if fallback.provider_id == selected_id
                ),
                available_fallbacks[0] if available_fallbacks else None,
            )
        if provider is None:
            model = MODEL_BY_ID.get(provider_id)
            if model is not None:
                raise EncapError(f"Download {model.name} before transcribing.")
            raise EncapError(
                "The selected shared transcription model is no longer available. "
                "Refresh the transcription engine list and try again."
            )
        if provider.source_name != "EnCap":
            _verify_shared_model(provider)

    results: list[TranscriptSegment] = []
    time_offset = 0.0
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        if progress is not None:
            progress(index - 1, total, f"Transcribing {source.display_name}…")
        if provider_id == APPLE_PROVIDER_ID:
            results.extend(_transcribe_with_apple(source.source_path, time_offset=time_offset))
        else:
            assert provider is not None
            try:
                if provider.engine == WHISPER_CPP_ENGINE:
                    results.extend(
                        _transcribe_with_whisper(
                            source.source_path,
                            model_path=provider.model_path,
                            language_code=provider.language_code,
                            time_offset=time_offset,
                        )
                    )
                elif provider.engine == WHISPERKIT_ENGINE and provider.tokenizer_path is not None:
                    results.extend(
                        _transcribe_with_whisperkit(
                            source.source_path,
                            model_path=provider.model_path,
                            tokenizer_path=provider.tokenizer_path,
                            language_code=provider.language_code,
                            time_offset=time_offset,
                        )
                    )
                else:
                    raise EncapError(f"Unsupported transcription engine: {provider.engine}")
            except EncapError as exc:
                detail = str(exc)
                provider_runtime_failed = provider.engine == WHISPERKIT_ENGINE and (
                    detail.startswith("WhisperKit transcription failed:")
                    or detail.startswith("WhisperKit returned an invalid")
                    or "Whisper Transcription tokenizer" in detail
                    or "whisperkit-transcriber" in detail
                )
                provider_runtime_failed = provider_runtime_failed or (
                    provider.engine == WHISPER_CPP_ENGINE
                    and (
                        detail.startswith("Whisper transcription failed:")
                        or detail.startswith("whisper.cpp ")
                        or "'whisper-cli'" in detail
                    )
                )
                if provider.source_name != "EnCap" and provider_runtime_failed:
                    store.mark_provider_runtime_unusable(provider.provider_id)
                raise
        time_offset += source.duration_seconds
    if progress is not None:
        progress(total, total, "Transcription complete.")
    return results
