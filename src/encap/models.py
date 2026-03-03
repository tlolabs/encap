from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WavFormat:
    audio_format: int
    channels: int
    sample_rate: int
    byte_rate: int
    block_align: int
    bits_per_sample: int
    fmt_chunk_data: bytes

    @property
    def sample_width_bytes(self) -> int:
        return self.bits_per_sample // 8


@dataclass(frozen=True)
class WavSource:
    path: Path
    wav_format: WavFormat
    data: bytes

    @property
    def frame_count(self) -> int:
        return len(self.data) // self.wav_format.block_align


@dataclass(frozen=True)
class CueMarker:
    marker_id: int
    sample_offset: int
    label: str


@dataclass(frozen=True)
class StitchPlan:
    output_path: Path
    sources: list[WavSource]
    markers: list[CueMarker]
    report_path: Path | None = None
