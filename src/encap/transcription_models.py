from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class ModelDownloadError(RuntimeError):
    """Raised when a transcription model cannot be safely installed."""


@dataclass(frozen=True)
class TranscriptionModel:
    model_id: str
    name: str
    filename: str
    download_url: str
    sha256: str
    download_size: str
    languages: str
    description: str
    language_code: str
    license_name: str = "MIT"
    license_url: str = "https://github.com/openai/whisper/blob/main/LICENSE"


# These are immutable revisions of OpenAI Whisper weights converted for
# whisper.cpp. Only this catalog can be downloaded; arbitrary model URLs are
# intentionally not accepted.
WHISPER_MODELS: tuple[TranscriptionModel, ...] = (
    TranscriptionModel(
        model_id="whisper-base-en",
        name="Whisper Base (English)",
        filename="ggml-base.en.bin",
        download_url=(
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
            "c521a4b02f422512d734391fdf08bb08c0862f68/ggml-base.en.bin?download=true"
        ),
        sha256="a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
        download_size="148 MB",
        languages="English",
        description="Fast, compact, and the recommended starting point for English recordings.",
        language_code="en",
    ),
    TranscriptionModel(
        model_id="whisper-small",
        name="Whisper Small (Multilingual)",
        filename="ggml-small.bin",
        download_url=(
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
            "c521a4b02f422512d734391fdf08bb08c0862f68/ggml-small.bin?download=true"
        ),
        sha256="1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
        download_size="488 MB",
        languages="Multilingual",
        description="A balanced multilingual model with better accuracy than Base.",
        language_code="auto",
    ),
    TranscriptionModel(
        model_id="whisper-large-v3-turbo",
        name="Whisper Large v3 Turbo",
        filename="ggml-large-v3-turbo.bin",
        download_url=(
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
            "6034871ec87c84e342efab769d4c5c06cd126db3/ggml-large-v3-turbo.bin?download=true"
        ),
        sha256="1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",
        download_size="1.62 GB",
        languages="Multilingual",
        description="Highest-quality option in EnCap's initial catalog; requires substantially more memory.",
        language_code="auto",
    ),
)

MODEL_BY_ID = {model.model_id: model for model in WHISPER_MODELS}
DownloadProgress = Callable[[int, int | None], None]


def default_model_root() -> Path:
    override = os.environ.get("ENCAP_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "EnCap" / "Models"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "EnCap" / "Models"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "encap" / "models"


class TranscriptionModelStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_model_root()

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def model_path(self, model: TranscriptionModel) -> Path:
        return self.root / "whisper" / model.filename

    def is_installed(self, model: TranscriptionModel) -> bool:
        path = self.model_path(model)
        return path.is_file() and path.stat().st_size > 0

    def selected_model_id(self) -> str | None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        model_id = state.get("selected_model_id")
        if not isinstance(model_id, str) or model_id not in MODEL_BY_ID:
            return None
        return model_id

    def set_selected_model(self, model_id: str | None) -> None:
        if model_id is not None:
            model = MODEL_BY_ID.get(model_id)
            if model is None:
                raise ValueError(f"Unknown transcription model: {model_id}")
            if not self.is_installed(model):
                raise ModelDownloadError(f"Download {model.name} before selecting it.")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps({"selected_model_id": model_id}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.state_path)

    def download(
        self,
        model: TranscriptionModel,
        progress: DownloadProgress | None = None,
        *,
        opener=urllib.request.urlopen,
    ) -> Path:
        destination = self.model_path(model)
        if self.is_installed(model):
            if progress is not None:
                size = destination.stat().st_size
                progress(size, size)
            return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        partial_path = destination.with_suffix(destination.suffix + ".part")
        partial_path.unlink(missing_ok=True)
        digest = hashlib.sha256()
        downloaded = 0
        request = urllib.request.Request(
            model.download_url,
            headers={"User-Agent": "EnCap/1.0"},
        )
        try:
            with opener(request, timeout=60) as response, partial_path.open("wb") as output:
                header_value = response.headers.get("Content-Length")
                total = int(header_value) if header_value and header_value.isdigit() else None
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total)
            if digest.hexdigest().lower() != model.sha256.lower():
                raise ModelDownloadError(
                    f"The downloaded {model.name} file failed its SHA-256 verification."
                )
            partial_path.replace(destination)
            return destination
        except ModelDownloadError:
            partial_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            partial_path.unlink(missing_ok=True)
            raise ModelDownloadError(f"Could not download {model.name}: {exc}") from exc

    def remove(self, model: TranscriptionModel) -> None:
        self.model_path(model).unlink(missing_ok=True)
        if self.selected_model_id() == model.model_id:
            self.set_selected_model(None)
