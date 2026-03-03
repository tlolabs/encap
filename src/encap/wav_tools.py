from __future__ import annotations

import struct
from pathlib import Path

from .models import CueMarker, StitchPlan, WavFormat, WavSource

RIFF_HEADER_SIZE = 12
CHUNK_HEADER_SIZE = 8


class EncapError(Exception):
    """Base error for E.N.C.A.P."""


class UnsupportedWavError(EncapError):
    """Raised when a WAV file is unsupported."""


def load_wav_source(path: Path) -> WavSource:
    raw = path.read_bytes()
    if len(raw) < RIFF_HEADER_SIZE:
        raise UnsupportedWavError(f"{path} is too small to be a valid WAV file.")
    riff_id, riff_size, wave_id = struct.unpack("<4sI4s", raw[:RIFF_HEADER_SIZE])
    if riff_id != b"RIFF" or wave_id != b"WAVE":
        raise UnsupportedWavError(f"{path} is not a RIFF/WAVE file.")

    offset = RIFF_HEADER_SIZE
    fmt_chunk_data = None
    data_chunk_data = None

    while offset + CHUNK_HEADER_SIZE <= len(raw):
        chunk_id = raw[offset : offset + 4]
        chunk_size = struct.unpack("<I", raw[offset + 4 : offset + 8])[0]
        data_start = offset + CHUNK_HEADER_SIZE
        data_end = data_start + chunk_size
        if data_end > len(raw):
            raise UnsupportedWavError(f"{path} has a truncated {chunk_id!r} chunk.")

        chunk_data = raw[data_start:data_end]
        if chunk_id == b"fmt ":
            fmt_chunk_data = chunk_data
        elif chunk_id == b"data":
            data_chunk_data = chunk_data

        offset = data_end + (chunk_size % 2)

    if fmt_chunk_data is None or data_chunk_data is None:
        raise UnsupportedWavError(f"{path} is missing required fmt/data chunks.")
    if len(fmt_chunk_data) < 16:
        raise UnsupportedWavError(f"{path} has an invalid fmt chunk.")

    audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack(
        "<HHIIHH", fmt_chunk_data[:16]
    )
    if block_align == 0:
        raise UnsupportedWavError(f"{path} has an invalid block alignment.")
    if len(data_chunk_data) % block_align != 0:
        raise UnsupportedWavError(f"{path} has a data chunk that is not frame aligned.")

    wav_format = WavFormat(
        audio_format=audio_format,
        channels=channels,
        sample_rate=sample_rate,
        byte_rate=byte_rate,
        block_align=block_align,
        bits_per_sample=bits_per_sample,
        fmt_chunk_data=fmt_chunk_data,
    )
    return WavSource(path=path, wav_format=wav_format, data=data_chunk_data)


def formats_match(left: WavFormat, right: WavFormat) -> bool:
    return (
        left.audio_format == right.audio_format
        and left.channels == right.channels
        and left.sample_rate == right.sample_rate
        and left.byte_rate == right.byte_rate
        and left.block_align == right.block_align
        and left.bits_per_sample == right.bits_per_sample
        and left.fmt_chunk_data == right.fmt_chunk_data
    )


def build_markers(sources: list[WavSource]) -> list[CueMarker]:
    markers: list[CueMarker] = []
    cumulative_frames = 0
    for index, source in enumerate(sources[:-1], start=1):
        cumulative_frames += source.frame_count
        markers.append(CueMarker(marker_id=index, sample_offset=cumulative_frames, label=str(index)))
    return markers


def build_stitch_plan(
    sources: list[WavSource],
    output_path: Path,
    report_path: Path | None = None,
) -> StitchPlan:
    if not sources:
        raise EncapError("At least one WAV source is required.")
    markers = build_markers(sources)
    return StitchPlan(output_path=output_path, sources=sources, markers=markers, report_path=report_path)


def build_cue_chunk(markers: list[CueMarker]) -> bytes:
    body = struct.pack("<I", len(markers))
    for marker in markers:
        body += struct.pack(
            "<II4sIII",
            marker.marker_id,
            marker.sample_offset,
            b"data",
            0,
            0,
            marker.sample_offset,
        )
    return _chunk(b"cue ", body)


def build_adtl_list_chunk(markers: list[CueMarker]) -> bytes:
    subchunks = b""
    for marker in markers:
        text = marker.label.encode("ascii", errors="strict") + b"\x00"
        subchunks += _chunk(b"labl", struct.pack("<I", marker.marker_id) + text)
    return _chunk(b"LIST", b"adtl" + subchunks)


def write_wav(plan: StitchPlan) -> None:
    fmt_chunk = _chunk(b"fmt ", plan.sources[0].wav_format.fmt_chunk_data)
    data = b"".join(source.data for source in plan.sources)
    data_chunk = _chunk(b"data", data)
    extra_chunks = b""
    if plan.markers:
        extra_chunks += build_cue_chunk(plan.markers)
        extra_chunks += build_adtl_list_chunk(plan.markers)

    riff_body = b"WAVE" + fmt_chunk + data_chunk + extra_chunks
    riff = b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body
    plan.output_path.write_bytes(riff)

    if plan.report_path is not None:
        lines = ["E.N.C.A.P. marker report", f"Output: {plan.output_path}", ""]
        total_frames = 0
        for index, source in enumerate(plan.sources, start=1):
            total_frames += source.frame_count
            lines.append(f"Source {index}: {source.path.name} ({source.frame_count} frames)")
        lines.append("")
        for marker in plan.markers:
            lines.append(f"Marker {marker.label}: frame {marker.sample_offset}")
        lines.append("")
        lines.append(f"Total frames: {total_frames}")
        plan.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    padded = payload + (b"\x00" if len(payload) % 2 else b"")
    return chunk_id + struct.pack("<I", len(payload)) + padded
