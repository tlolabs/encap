from __future__ import annotations

import struct
from collections.abc import Iterator
from pathlib import Path

from .models import CueMarker, StitchPlan, WavFormat, WavSource

RIFF_HEADER_SIZE = 12
CHUNK_HEADER_SIZE = 8
AUDIO_FILE_EXTENSIONS = {".aif", ".aiff", ".wav"}
STREAM_BUFFER_SIZE = 1024 * 1024
RIFF_MAX_SIZE = (1 << 32) - 1


class EncapError(Exception):
    """Base error for E.N.C.A.P."""


class UnsupportedWavError(EncapError):
    """Raised when a WAV file is unsupported."""


def load_wav_source(path: Path) -> WavSource:
    file_size = path.stat().st_size
    if file_size < RIFF_HEADER_SIZE:
        raise UnsupportedWavError(f"{path} is too small to be a valid WAV file.")
    fmt_chunk_data: bytes | None = None
    data_offset: int | None = None
    data_size: int | None = None

    with path.open("rb") as source_file:
        riff_id, riff_size, wave_id = struct.unpack(
            "<4sI4s", _read_exact(source_file, RIFF_HEADER_SIZE, path, "RIFF header")
        )
        if riff_id != b"RIFF" or wave_id != b"WAVE":
            raise UnsupportedWavError(f"{path} is not a RIFF/WAVE file.")
        riff_end = riff_size + 8
        if riff_end > file_size:
            raise UnsupportedWavError(f"{path} has a truncated RIFF chunk.")

        offset = RIFF_HEADER_SIZE
        while offset + CHUNK_HEADER_SIZE <= riff_end:
            source_file.seek(offset)
            chunk_id, chunk_size = struct.unpack(
                "<4sI", _read_exact(source_file, CHUNK_HEADER_SIZE, path, "chunk header")
            )
            chunk_data_offset = offset + CHUNK_HEADER_SIZE
            chunk_end = chunk_data_offset + chunk_size
            if chunk_end > riff_end:
                raise UnsupportedWavError(f"{path} has a truncated {chunk_id!r} chunk.")

            if chunk_id == b"fmt ":
                source_file.seek(chunk_data_offset)
                fmt_chunk_data = _read_exact(source_file, chunk_size, path, "fmt chunk")
            elif chunk_id == b"data":
                data_offset = chunk_data_offset
                data_size = chunk_size

            offset = chunk_end + (chunk_size % 2)

    if fmt_chunk_data is None or data_offset is None or data_size is None:
        raise UnsupportedWavError(f"{path} is missing required fmt/data chunks.")
    if len(fmt_chunk_data) < 16:
        raise UnsupportedWavError(f"{path} has an invalid fmt chunk.")

    audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack(
        "<HHIIHH", fmt_chunk_data[:16]
    )
    if block_align == 0:
        raise UnsupportedWavError(f"{path} has an invalid block alignment.")
    if data_size % block_align != 0:
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
    return WavSource(
        path=path,
        wav_format=wav_format,
        data_path=path,
        data_offset=data_offset,
        data_size=data_size,
    )


def load_audio_source(path: Path) -> WavSource:
    """Load an uncompressed WAV or AIFF file into the internal PCM representation."""
    if path.suffix.lower() in {".aif", ".aiff"}:
        return load_aiff_source(path)
    return load_wav_source(path)


def load_aiff_source(path: Path) -> WavSource:
    file_size = path.stat().st_size
    if file_size < RIFF_HEADER_SIZE:
        raise UnsupportedWavError(f"{path} is too small to be a valid AIFF file.")
    comm_chunk_data: bytes | None = None
    sound_data_offset: int | None = None
    sound_data_available: int | None = None
    with path.open("rb") as source_file:
        form_id, form_size, form_type = struct.unpack(
            ">4sI4s", _read_exact(source_file, RIFF_HEADER_SIZE, path, "FORM header")
        )
        if form_id != b"FORM" or form_type != b"AIFF":
            raise UnsupportedWavError(f"{path} is not an uncompressed AIFF file.")
        form_end = form_size + 8
        if form_end > file_size:
            raise UnsupportedWavError(f"{path} has a truncated FORM chunk.")

        offset = RIFF_HEADER_SIZE
        while offset + CHUNK_HEADER_SIZE <= form_end:
            source_file.seek(offset)
            chunk_id, chunk_size = struct.unpack(
                ">4sI", _read_exact(source_file, CHUNK_HEADER_SIZE, path, "chunk header")
            )
            chunk_data_offset = offset + CHUNK_HEADER_SIZE
            chunk_end = chunk_data_offset + chunk_size
            if chunk_end > form_end:
                raise UnsupportedWavError(f"{path} has a truncated {chunk_id!r} chunk.")
            if chunk_id == b"COMM":
                source_file.seek(chunk_data_offset)
                comm_chunk_data = _read_exact(source_file, chunk_size, path, "COMM chunk")
            elif chunk_id == b"SSND":
                if chunk_size < 8:
                    raise UnsupportedWavError(f"{path} has an invalid AIFF audio chunk.")
                source_file.seek(chunk_data_offset)
                sound_offset, _block_size = struct.unpack(
                    ">II", _read_exact(source_file, 8, path, "SSND header")
                )
                if sound_offset > chunk_size - 8:
                    raise UnsupportedWavError(f"{path} has an invalid AIFF audio chunk.")
                sound_data_offset = chunk_data_offset + 8 + sound_offset
                sound_data_available = chunk_size - 8 - sound_offset
            offset = chunk_end + (chunk_size % 2)

    if comm_chunk_data is None or sound_data_offset is None or sound_data_available is None:
        raise UnsupportedWavError(f"{path} is missing required COMM/SSND chunks.")
    if len(comm_chunk_data) < 18:
        raise UnsupportedWavError(f"{path} has an invalid AIFF audio chunk.")

    channels, frame_count, bits_per_sample = struct.unpack(">HIH", comm_chunk_data[:8])
    sample_rate = _decode_extended_float(comm_chunk_data[8:18])
    if channels <= 0 or frame_count < 0 or bits_per_sample not in {8, 16, 24, 32}:
        raise UnsupportedWavError(f"{path} uses an unsupported AIFF PCM format.")
    sample_width = bits_per_sample // 8
    block_align = channels * sample_width
    expected_size = frame_count * block_align
    if expected_size > sound_data_available:
        raise UnsupportedWavError(f"{path} has truncated AIFF sample data.")

    byte_rate = sample_rate * block_align
    fmt_chunk_data = struct.pack(
        "<HHIIHH",
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    )
    return WavSource(
        path=path,
        wav_format=WavFormat(
            audio_format=1,
            channels=channels,
            sample_rate=sample_rate,
            byte_rate=byte_rate,
            block_align=block_align,
            bits_per_sample=bits_per_sample,
            fmt_chunk_data=fmt_chunk_data,
        ),
        data_path=path,
        data_offset=sound_data_offset,
        data_size=expected_size,
        pcm_byte_order="big",
        pcm_8bit_signed=sample_width == 1,
    )


def _decode_extended_float(raw: bytes) -> int:
    """Decode the positive 80-bit extended value used for AIFF sample rates."""
    if len(raw) != 10:
        raise UnsupportedWavError("Invalid AIFF sample-rate value.")
    exponent = struct.unpack(">H", raw[:2])[0]
    mantissa = int.from_bytes(raw[2:], byteorder="big")
    if exponent == 0 and mantissa == 0:
        return 0
    if exponent & 0x8000:
        raise UnsupportedWavError("Negative AIFF sample rates are not supported.")
    value = mantissa * (2.0 ** ((exponent & 0x7FFF) - 16383 - 63))
    sample_rate = int(round(value))
    if sample_rate <= 0:
        raise UnsupportedWavError("Invalid AIFF sample rate.")
    return sample_rate


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
    data_size = sum(source.data_size for source in plan.sources)
    extra_chunks = b""
    if plan.markers:
        extra_chunks += build_cue_chunk(plan.markers)
        extra_chunks += build_adtl_list_chunk(plan.markers)

    data_padding_size = data_size % 2
    riff_size = 4 + len(fmt_chunk) + CHUNK_HEADER_SIZE + data_size + data_padding_size + len(extra_chunks)
    if data_size > RIFF_MAX_SIZE or riff_size > RIFF_MAX_SIZE:
        raise EncapError(
            "The stitched WAV would exceed the 4 GiB RIFF/WAV size limit. "
            "Export shorter sections, use 16-bit audio, or downsample the sources before exporting."
        )

    with plan.output_path.open("wb") as output_file:
        output_file.write(b"RIFF")
        output_file.write(struct.pack("<I", riff_size))
        output_file.write(b"WAVE")
        output_file.write(fmt_chunk)
        output_file.write(b"data")
        output_file.write(struct.pack("<I", data_size))
        for source in plan.sources:
            for chunk in _iter_pcm_chunks(source):
                output_file.write(chunk)
        if data_padding_size:
            output_file.write(b"\x00")
        output_file.write(extra_chunks)

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


def read_source_pcm(source: WavSource) -> bytes:
    """Materialize one source when a caller cannot retain its backing file."""
    return b"".join(_iter_pcm_chunks(source))


def _iter_pcm_chunks(source: WavSource) -> Iterator[bytes]:
    if source.data is not None:
        for offset in range(0, len(source.data), STREAM_BUFFER_SIZE):
            yield source.data[offset : offset + STREAM_BUFFER_SIZE]
        return

    data_path = source.data_path or source.path
    sample_width = source.wav_format.sample_width_bytes
    read_size = STREAM_BUFFER_SIZE - (STREAM_BUFFER_SIZE % sample_width)
    remaining = source.data_size
    with data_path.open("rb") as source_file:
        source_file.seek(source.data_offset)
        while remaining:
            chunk = source_file.read(min(read_size, remaining))
            if not chunk:
                raise UnsupportedWavError(f"{data_path} has truncated sample data.")
            remaining -= len(chunk)
            if source.pcm_8bit_signed:
                chunk = chunk.translate(_AIFF_SIGNED_8_TO_WAV_UNSIGNED)
            elif source.pcm_byte_order == "big" and sample_width > 1:
                chunk = _swap_sample_byte_order(chunk, sample_width)
            yield chunk


def _swap_sample_byte_order(chunk: bytes, sample_width: int) -> bytes:
    converted = bytearray(len(chunk))
    for offset in range(0, len(chunk), sample_width):
        converted[offset : offset + sample_width] = chunk[offset : offset + sample_width][::-1]
    return bytes(converted)


def _read_exact(source_file, size: int, path: Path, description: str) -> bytes:
    data = source_file.read(size)
    if len(data) != size:
        raise UnsupportedWavError(f"{path} has a truncated {description}.")
    return data


_AIFF_SIGNED_8_TO_WAV_UNSIGNED = bytes.maketrans(
    bytes(range(256)), bytes((sample + 128) & 0xFF for sample in range(256))
)
