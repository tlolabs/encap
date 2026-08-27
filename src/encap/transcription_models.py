from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import shutil
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class ModelDownloadError(RuntimeError):
    """Raised when a transcription model cannot be safely installed."""


class SharedModelVerificationError(RuntimeError):
    """Raised when another application's shared model cannot be trusted."""


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


WHISPER_CPP_ENGINE = "whisper-cpp"
WHISPERKIT_ENGINE = "whisperkit"
SUPERWHISPER_PROVIDER_ID = "superwhisper-large-v3"
SUPERWHISPER_MODEL_FILENAME = "ggml-large-v3.bin"
SUPERWHISPER_MODEL_SIZE = 3_095_033_483
SUPERWHISPER_MODEL_SHA256 = "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"
_verified_shared_models: set[tuple[int, int, int, int, str]] = set()
_invalid_shared_models: set[tuple[int, int, int, int, str]] = set()


@dataclass(frozen=True)
class TranscriptionProvider:
    provider_id: str
    name: str
    engine: str
    source_name: str
    model_path: Path
    language_code: str = "auto"
    tokenizer_path: Path | None = None
    sha256: str | None = None


# Prefer the compact Turbo package when MacWhisper has more than one model.
# Each tuple is (folder, provider id, display name, tokenizer repository).
MACWHISPER_MODELS: tuple[tuple[str, str, str, str], ...] = (
    (
        "openai_whisper-large-v3-v20240930_626MB",
        "macwhisper-large-v3-turbo-compressed",
        "Whisper Large V3 Turbo (compressed) — Whisper Transcription",
        "whisper-large-v3",
    ),
    (
        "openai_whisper-large-v3-v20240930",
        "macwhisper-large-v3-turbo",
        "Whisper Large V3 Turbo — Whisper Transcription",
        "whisper-large-v3",
    ),
    (
        "openai_whisper-large-v3",
        "macwhisper-large-v3",
        "Whisper Large V3 — Whisper Transcription",
        "whisper-large-v3",
    ),
)
SHARED_PROVIDER_IDS = frozenset(
    (SUPERWHISPER_PROVIDER_ID, *(provider_id for _, provider_id, _, _ in MACWHISPER_MODELS))
)


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


def _application_is_installed(
    names: tuple[str, ...],
    bundle_id: str,
    *,
    home: Path,
    application_dirs: tuple[Path, ...] | None,
) -> bool:
    roots = (
        application_dirs
        if application_dirs is not None
        else (Path("/Applications"), home / "Applications")
    )
    for root in roots:
        named_candidates = [root / name for name in names]
        try:
            discovered_candidates = [
                *root.glob("*.app"),
                *root.glob("*/*.app"),
            ]
        except OSError:
            discovered_candidates = []
        seen: set[Path] = set()
        for app_path in (*named_candidates, *discovered_candidates):
            if app_path in seen:
                continue
            seen.add(app_path)
            info_path = app_path / "Contents" / "Info.plist"
            try:
                with info_path.open("rb") as info_file:
                    info = plistlib.load(info_file)
            except (OSError, plistlib.InvalidFileException):
                continue
            if isinstance(info, dict) and info.get("CFBundleIdentifier") == bundle_id:
                return True
    return False


def whisperkit_helper_available() -> bool:
    name = "whisperkit-transcriber"
    override = os.environ.get("ENCAP_WHISPERKIT_TRANSCRIBER", "").strip()
    candidates: list[Path] = [Path(override)] if override else []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / name)
    source_root = Path(__file__).resolve().parents[2]
    candidates.append(source_root / ".build-tools" / name)
    if any(path.is_file() and os.access(path, os.X_OK) for path in candidates):
        return True
    return shutil.which(name) is not None


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return document if isinstance(document, dict) else None


def _file_matches_sha256(path: Path, expected_sha256: str) -> bool:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest().lower() == expected_sha256.lower()


def _valid_whisperkit_model(path: Path) -> bool:
    model_config = _read_json_object(path / "config.json")
    generation_config = _read_json_object(path / "generation_config.json")
    if model_config is None or generation_config is None:
        return False
    if not (
        model_config.get("model_type") == "whisper"
        and type(model_config.get("d_model")) is int
        and model_config["d_model"] > 0
        and type(model_config.get("decoder_start_token_id")) is int
        and isinstance(generation_config.get("lang_to_id"), dict)
        and bool(generation_config["lang_to_id"])
        and isinstance(generation_config.get("task_to_id"), dict)
        and bool(generation_config["task_to_id"])
        and type(generation_config.get("no_timestamps_token_id")) is int
    ):
        return False
    try:
        for component in ("AudioEncoder", "MelSpectrogram", "TextDecoder"):
            model_dir = path / f"{component}.mlmodelc"
            required_files = (
                model_dir / "model.mil",
                model_dir / "coremldata.bin",
                model_dir / "metadata.json",
                model_dir / "weights" / "weight.bin",
            )
            if not model_dir.is_dir() or not all(
                required.is_file() and required.stat().st_size > 0
                for required in required_files
            ):
                return False
    except OSError:
        return False
    return True


def _valid_whisperkit_tokenizer(path: Path) -> bool:
    tokenizer = _read_json_object(path / "tokenizer.json")
    tokenizer_config = _read_json_object(path / "tokenizer_config.json")
    model_config = _read_json_object(path / "config.json")
    if tokenizer is None or tokenizer_config is None or model_config is None:
        return False
    tokenizer_model = tokenizer.get("model")
    return (
        isinstance(tokenizer_model, dict)
        and tokenizer_model.get("type") == "BPE"
        and isinstance(tokenizer_model.get("vocab"), dict)
        and bool(tokenizer_model["vocab"])
        and isinstance(tokenizer_model.get("merges"), list)
        and bool(tokenizer_model["merges"])
        and tokenizer_config.get("tokenizer_class") == "WhisperTokenizer"
        and isinstance(tokenizer_config.get("added_tokens_decoder"), dict)
        and model_config.get("model_type") == "whisper"
        and isinstance(model_config.get("d_model"), int)
        and model_config["d_model"] > 0
        and isinstance(model_config.get("decoder_start_token_id"), int)
    )


def _shared_model_identity(
    provider: TranscriptionProvider,
) -> tuple[tuple[int, int, int, int, str], dict[str, int | str]]:
    if provider.sha256 is None:
        raise SharedModelVerificationError("The shared model has no expected SHA-256 digest.")
    try:
        stat = provider.model_path.stat()
    except OSError as exc:
        raise SharedModelVerificationError(
            f"The shared {provider.source_name} transcription model is no longer available."
        ) from exc
    cache_key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, provider.sha256)
    identity: dict[str, int | str] = {
        "path": str(provider.model_path),
        "sha256": provider.sha256,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }
    return cache_key, identity


def _cached_shared_model_result(
    cache_path: Path,
    provider_id: str,
    identity: dict[str, int | str],
) -> bool | None:
    try:
        document = json.loads(cache_path.read_text(encoding="utf-8"))
        entry = document["providers"][provider_id]
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return None
    if not isinstance(entry, dict) or any(entry.get(key) != value for key, value in identity.items()):
        return None
    valid = entry.get("valid")
    return valid if isinstance(valid, bool) else None


def _store_shared_model_result(
    cache_path: Path,
    provider_id: str,
    identity: dict[str, int | str],
    *,
    valid: bool,
) -> None:
    try:
        document = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        document = {}
    if not isinstance(document, dict):
        document = {}
    providers = document.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        document["providers"] = providers
    providers[provider_id] = {**identity, "valid": valid}
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(cache_path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def verify_shared_model(
    provider: TranscriptionProvider,
    *,
    cache_path: Path | None = None,
) -> None:
    """Verify a shared model once per file identity, with an optional persistent cache."""

    if provider.sha256 is None:
        return
    cache_key, identity = _shared_model_identity(provider)
    if cache_key in _verified_shared_models:
        return
    if cache_key in _invalid_shared_models:
        raise SharedModelVerificationError(
            f"The shared {provider.source_name} transcription model failed SHA-256 verification."
        )
    if cache_path is not None:
        cached_result = _cached_shared_model_result(cache_path, provider.provider_id, identity)
        if cached_result is True:
            _verified_shared_models.add(cache_key)
            return
        if cached_result is False:
            _invalid_shared_models.add(cache_key)
            raise SharedModelVerificationError(
                f"The shared {provider.source_name} transcription model failed SHA-256 verification."
            )

    digest = hashlib.sha256()
    try:
        with provider.model_path.open("rb") as model_file:
            while chunk := model_file.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SharedModelVerificationError(
            f"The shared {provider.source_name} transcription model could not be read."
        ) from exc
    valid = digest.hexdigest().lower() == provider.sha256.lower()
    if cache_path is not None:
        _store_shared_model_result(
            cache_path,
            provider.provider_id,
            identity,
            valid=valid,
        )
    if not valid:
        _invalid_shared_models.add(cache_key)
        raise SharedModelVerificationError(
            f"The shared {provider.source_name} transcription model failed SHA-256 verification."
        )
    _verified_shared_models.add(cache_key)


def cached_shared_model_validity(
    provider: TranscriptionProvider,
    *,
    cache_path: Path,
) -> bool | None:
    """Return a cached integrity result without reading the multi-gigabyte model."""

    if provider.sha256 is None:
        return True
    try:
        cache_key, identity = _shared_model_identity(provider)
    except SharedModelVerificationError:
        return False
    if cache_key in _verified_shared_models:
        return True
    if cache_key in _invalid_shared_models:
        return False
    cached_result = _cached_shared_model_result(cache_path, provider.provider_id, identity)
    if cached_result is True:
        _verified_shared_models.add(cache_key)
    elif cached_result is False:
        _invalid_shared_models.add(cache_key)
    return cached_result


def _macwhisper_model_roots(home: Path) -> tuple[Path, ...]:
    container_support = (
        home
        / "Library"
        / "Containers"
        / "com.goodsnooze.MacWhisper"
        / "Data"
        / "Library"
        / "Application Support"
        / "MacWhisper"
        / "models"
    )
    regular_support = home / "Library" / "Application Support" / "MacWhisper" / "models"
    return (container_support, regular_support)


def discover_shared_transcription_providers(
    *,
    home: Path | None = None,
    application_dirs: tuple[Path, ...] | None = None,
    whisperkit_available: bool | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
    macos_version: str | None = None,
    skip_superwhisper: bool = False,
) -> tuple[TranscriptionProvider, ...]:
    """Return the first usable shared-model source in application priority order."""

    current_platform = platform_name or sys.platform
    if current_platform != "darwin":
        return ()
    user_home = (home or Path.home()).expanduser()
    superwhisper_installed = _application_is_installed(
        ("superwhisper.app", "Superwhisper.app"),
        "com.superduper.superwhisper",
        home=user_home,
        application_dirs=application_dirs,
    )
    superwhisper_model = (
        user_home
        / "Library"
        / "Application Support"
        / "superwhisper"
        / SUPERWHISPER_MODEL_FILENAME
    )
    try:
        superwhisper_size = superwhisper_model.stat().st_size
    except OSError:
        superwhisper_size = 0
    if (
        not skip_superwhisper
        and superwhisper_installed
        and superwhisper_size == SUPERWHISPER_MODEL_SIZE
    ):
        return (
            TranscriptionProvider(
                provider_id=SUPERWHISPER_PROVIDER_ID,
                name="Whisper Large V3 — Superwhisper",
                engine=WHISPER_CPP_ENGINE,
                source_name="Superwhisper",
                model_path=superwhisper_model,
                sha256=SUPERWHISPER_MODEL_SHA256,
            ),
        )

    macwhisper_installed = _application_is_installed(
        ("Whisper Transcription.app", "MacWhisper.app"),
        "com.goodsnooze.MacWhisper",
        home=user_home,
        application_dirs=application_dirs,
    )
    helper_available = (
        whisperkit_helper_available()
        if whisperkit_available is None
        else whisperkit_available
    )
    current_machine = (machine or platform.machine()).lower()
    version_text = macos_version if macos_version is not None else platform.mac_ver()[0]
    try:
        macos_major = int(version_text.split(".", 1)[0])
    except (TypeError, ValueError):
        macos_major = 0
    if (
        not macwhisper_installed
        or not helper_available
        or current_machine not in {"arm64", "aarch64"}
        or macos_major < 14
    ):
        return ()

    providers: list[TranscriptionProvider] = []
    for folder_name, provider_id, display_name, tokenizer_name in MACWHISPER_MODELS:
        for model_root in _macwhisper_model_roots(user_home):
            whisperkit_models = model_root / "whisperkit" / "models"
            repository = whisperkit_models / "argmaxinc" / "whisperkit-coreml"
            model_path = repository / folder_name
            tokenizer_candidates = (
                whisperkit_models / "openai" / tokenizer_name,
                model_path / "models" / "openai" / tokenizer_name,
            )
            tokenizer_path = next(
                (path for path in tokenizer_candidates if _valid_whisperkit_tokenizer(path)),
                None,
            )
            if not _valid_whisperkit_model(model_path) or tokenizer_path is None:
                continue
            providers.append(
                TranscriptionProvider(
                    provider_id=provider_id,
                    name=display_name,
                    engine=WHISPERKIT_ENGINE,
                    source_name="Whisper Transcription",
                    model_path=model_path,
                    tokenizer_path=tokenizer_path,
                )
            )
            break
    return tuple(providers)


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
    def __init__(
        self,
        root: Path | None = None,
        *,
        home: Path | None = None,
        application_dirs: tuple[Path, ...] | None = None,
        whisperkit_available: bool | None = None,
        platform_name: str | None = None,
        machine: str | None = None,
        macos_version: str | None = None,
    ) -> None:
        self.root = root or default_model_root()
        self.home = home
        self.application_dirs = application_dirs
        self.whisperkit_available = whisperkit_available
        self.platform_name = platform_name
        self.machine = machine
        self.macos_version = macos_version
        self._runtime_unusable_provider_ids: set[str] = set()

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def model_path(self, model: TranscriptionModel) -> Path:
        return self.root / "whisper" / model.filename

    def is_installed(self, model: TranscriptionModel) -> bool:
        path = self.model_path(model)
        return path.is_file() and path.stat().st_size > 0

    def shared_providers(
        self,
        *,
        verify_integrity: bool = False,
    ) -> tuple[TranscriptionProvider, ...]:
        discovery_options = dict(
            home=self.home,
            application_dirs=self.application_dirs,
            whisperkit_available=self.whisperkit_available,
            platform_name=self.platform_name,
            machine=self.machine,
            macos_version=self.macos_version,
        )

        def usable_runtime_providers(
            candidates: tuple[TranscriptionProvider, ...],
        ) -> tuple[TranscriptionProvider, ...]:
            return tuple(
                provider
                for provider in candidates
                if provider.provider_id not in self._runtime_unusable_provider_ids
            )

        providers = discover_shared_transcription_providers(
            **discovery_options,
            skip_superwhisper=SUPERWHISPER_PROVIDER_ID
            in self._runtime_unusable_provider_ids,
        )
        providers = usable_runtime_providers(providers)
        if providers and providers[0].provider_id == SUPERWHISPER_PROVIDER_ID:
            verification_cache = self.root / "shared-model-verification.json"
            cached_validity = cached_shared_model_validity(
                providers[0],
                cache_path=verification_cache,
            )
            if cached_validity is False:
                return usable_runtime_providers(
                    discover_shared_transcription_providers(
                        **discovery_options,
                        skip_superwhisper=True,
                    )
                )
            if cached_validity is None and verify_integrity:
                try:
                    verify_shared_model(
                        providers[0],
                        cache_path=verification_cache,
                    )
                except SharedModelVerificationError:
                    return usable_runtime_providers(
                        discover_shared_transcription_providers(
                            **discovery_options,
                            skip_superwhisper=True,
                        )
                    )
        return providers

    def mark_provider_runtime_unusable(self, provider_id: str) -> None:
        if provider_id in SHARED_PROVIDER_IDS:
            self._runtime_unusable_provider_ids.add(provider_id)

    def available_providers(
        self,
        *,
        verify_integrity: bool = False,
    ) -> tuple[TranscriptionProvider, ...]:
        shared = self.shared_providers(verify_integrity=verify_integrity)
        if shared:
            return shared
        managed = tuple(
            TranscriptionProvider(
                provider_id=model.model_id,
                name=model.name,
                engine=WHISPER_CPP_ENGINE,
                source_name="EnCap",
                model_path=self.model_path(model),
                language_code=model.language_code,
            )
            for model in WHISPER_MODELS
            if self.is_installed(model)
        )
        selected_id = self.selected_model_id()
        if selected_id is None:
            return managed
        return tuple(
            sorted(
                managed,
                key=lambda provider: provider.provider_id != selected_id,
            )
        )

    def provider(
        self,
        provider_id: str,
        *,
        verify_integrity: bool = False,
    ) -> TranscriptionProvider | None:
        return next(
            (
                provider
                for provider in self.available_providers(verify_integrity=verify_integrity)
                if provider.provider_id == provider_id
            ),
            None,
        )

    def selected_model_id(self) -> str | None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            return None
        if not isinstance(state, dict):
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
            if _file_matches_sha256(destination, model.sha256):
                if progress is not None:
                    size = destination.stat().st_size
                    progress(size, size)
                return destination
            destination.unlink(missing_ok=True)

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
