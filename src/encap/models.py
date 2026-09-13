from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


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
    def encoding(self) -> int:
        if self.audio_format == 65534 and len(self.fmt_chunk_data) >= 40:
            return int.from_bytes(self.fmt_chunk_data[24:28], "little")
        return self.audio_format

    @property
    def valid_bits(self) -> int:
        if self.audio_format == 65534 and len(self.fmt_chunk_data) >= 40:
            return int.from_bytes(self.fmt_chunk_data[18:20], "little")
        return self.bits_per_sample

    @property
    def channel_mask(self) -> int:
        if self.audio_format == 65534 and len(self.fmt_chunk_data) >= 40:
            return int.from_bytes(self.fmt_chunk_data[20:24], "little")
        return 0

    @property
    def sample_width_bytes(self) -> int:
        return self.bits_per_sample // 8


@dataclass(frozen=True)
class WavSource:
    path: Path
    wav_format: WavFormat
    data: bytes | None = field(default=None, repr=False)
    data_path: Path | None = None
    data_offset: int = 0
    data_size: int | None = None
    pcm_byte_order: str = "little"
    pcm_8bit_signed: bool = False

    def __post_init__(self) -> None:
        if self.data_size is None:
            object.__setattr__(self, "data_size", len(self.data or b""))
        if self.data is not None and self.data_size != len(self.data):
            raise ValueError("In-memory PCM data does not match its declared size.")
        if self.data_offset < 0 or self.data_size < 0:
            raise ValueError("PCM offsets and sizes cannot be negative.")
        if self.pcm_byte_order not in {"little", "big"}:
            raise ValueError(f"Unsupported PCM byte order: {self.pcm_byte_order}")

    @property
    def frame_count(self) -> int:
        return self.data_size // self.wav_format.block_align


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


@dataclass
class AudioSourceEntry:
    source_path: Path
    display_name: str
    duration_seconds: float
    stored_path: str | None = None


@dataclass
class ChapterEntry:
    start_time_seconds: float
    duration_seconds: float
    chapter_number: int
    title: str
    link_url: str = ""
    image_path: Path | None = None
    image_stored_path: str | None = None
    id: str = field(
        default_factory=lambda: uuid4().hex,
        init=False,
        repr=False,
        compare=False,
    )


@dataclass
class EpisodeMetadata:
    podcast_title: str = ""
    episode_title: str = ""
    summary: str = ""
    artwork_path: Path | None = None
    artwork_stored_path: str | None = None


@dataclass
class TranscriptSegment:
    start_time_seconds: float
    end_time_seconds: float
    speaker: str = ""
    text: str = ""


@dataclass
class ExportSettings:
    output_format: str = "mp3"
    quality_preset: str = "320k"
    encoder: str = "lame"
    channels: int = 2

    def output_extension(self) -> str:
        return ".m4a" if self.output_format.lower() in {"aac", "m4a"} else ".mp3"


@dataclass(frozen=True)
class CapabilityFlags:
    apple_transcription_available: bool = False
    apple_ai_available: bool = False
    lame_available: bool = False
    audio_toolbox_aac_available: bool = False
    audio_toolbox_aac_implementation: str = ""


@dataclass
class ProjectDocument:
    schema_version: int = 1
    audio_sources: list[AudioSourceEntry] = field(default_factory=list)
    metadata: EpisodeMetadata = field(default_factory=EpisodeMetadata)
    chapters: list[ChapterEntry] = field(default_factory=list)
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    export_settings: ExportSettings = field(default_factory=ExportSettings)
    project_title: str = "Untitled"
    source_folder: Path | None = None
    project_path: Path | None = None
    working_dir: Path | None = None

    def output_basename(self) -> str:
        title = self.metadata.episode_title.strip() or self.project_title.strip() or "encap-output"
        sanitized = "".join(char if char.isalnum() or char in {"-", "_", " "} else "-" for char in title)
        sanitized = "-".join(sanitized.split())
        return sanitized or "encap-output"
