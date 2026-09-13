"""Secure, platform-aware application updates backed by GitHub Releases.

macOS uses Sparkle (see :mod:`encap.sparkle_updater`). Windows and Linux use
the signed manifest parsed here and a separately packaged replacement helper.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .version import __version__


UPDATE_MANIFEST_URL = (
    "https://github.com/tlolabs/encap/releases/latest/download/latest.json"
)
UPDATE_PUBLIC_KEY_FILE = "update_public_key.txt"
USER_AGENT = f"EnCap/{__version__} (+https://github.com/tlolabs/encap)"
MANIFEST_SCHEMA_VERSION = 1
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
MAX_MANIFEST_SIZE = 2 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")


class UpdateError(RuntimeError):
    """An update could not be checked, verified, prepared, or installed."""


class UpdateConfigurationError(UpdateError):
    """The packaged application is missing required update configuration."""


@dataclass(frozen=True)
class UpdateAsset:
    platform: str
    url: str
    sha256: str
    size: int
    archive: str


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    release_url: str
    notes: str
    asset: UpdateAsset


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    target_dir: Path
    staged_dir: Path
    executable_name: str


def current_platform_key(
    system_name: str | None = None,
    machine_name: str | None = None,
) -> str:
    """Return the exact release-manifest key for this OS and CPU."""

    system_value = (system_name or platform.system()).strip().lower()
    machine_value = (machine_name or platform.machine()).strip().lower()
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine_value)
    if architecture is None:
        raise UpdateConfigurationError(f"Unsupported processor architecture: {machine_value}")

    os_name = {
        "windows": "windows",
        "linux": "linux",
        "darwin": "macos",
    }.get(system_value)
    if os_name is None:
        raise UpdateConfigurationError(f"Unsupported operating system: {system_value}")
    if os_name == "macos" and architecture == "x64":
        return "macos-intel"
    return f"{os_name}-{architecture}"


def _version_key(value: str) -> tuple[int, ...]:
    """Build a comparison key for the stable dotted versions used by releases."""

    normalized = value.strip().lstrip("v")
    if VERSION_PATTERN.fullmatch(normalized) is None:
        raise UpdateError(f"Invalid application version: {value}")
    return tuple(int(component) for component in normalized.split("."))


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return _version_key(candidate) > _version_key(current)


def canonical_manifest_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_signature(payload: dict[str, Any], signature: str, public_key: str) -> None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ModuleNotFoundError as exc:  # pragma: no cover - packaging contract
        raise UpdateConfigurationError(
            "The cryptography package required for update verification is missing."
        ) from exc

    try:
        public_key_bytes = base64.b64decode(public_key, validate=True)
        signature_bytes = base64.b64decode(signature, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature_bytes,
            canonical_manifest_payload(payload),
        )
    except (ValueError, InvalidSignature) as exc:
        raise UpdateError("The update manifest signature is invalid.") from exc


def parse_update_manifest(
    raw_manifest: bytes | str,
    *,
    public_key: str,
    platform_key: str | None = None,
) -> UpdateRelease:
    if not public_key.strip():
        raise UpdateConfigurationError("No update-signing public key is configured.")
    try:
        document = json.loads(raw_manifest)
        payload = document["payload"]
        signature = document["signature"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpdateError("The update manifest is malformed.") from exc
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise UpdateError("The update manifest has invalid field types.")
    _verify_signature(payload, signature, public_key.strip())

    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise UpdateError("The update manifest uses an unsupported schema version.")
    selected_platform = platform_key or current_platform_key()
    try:
        asset_data = payload["assets"][selected_platform]
        asset = UpdateAsset(
            platform=selected_platform,
            url=str(asset_data["url"]),
            sha256=str(asset_data["sha256"]).lower(),
            size=int(asset_data["size"]),
            archive=str(asset_data["archive"]),
        )
        release = UpdateRelease(
            version=str(payload["version"]),
            release_url=str(payload["release_url"]),
            notes=str(payload.get("notes", "")),
            asset=asset,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateConfigurationError(
            f"No valid update is published for {selected_platform}."
        ) from exc
    _version_key(release.version)
    if not asset.url.startswith("https://github.com/tlolabs/encap/releases/download/"):
        raise UpdateError("The update asset URL is outside the trusted GitHub repository.")
    if len(asset.sha256) != 64 or any(character not in "0123456789abcdef" for character in asset.sha256):
        raise UpdateError("The update asset has an invalid SHA-256 digest.")
    expected_archive = (
        "dmg"
        if selected_platform.startswith("macos-")
        else "zip"
        if selected_platform.startswith("windows-")
        else "tar.gz"
    )
    if asset.size <= 0 or asset.archive != expected_archive:
        raise UpdateError("The update asset metadata is invalid.")
    return release


def load_update_public_key() -> str:
    candidates = [Path(__file__).with_name(UPDATE_PUBLIC_KEY_FILE)]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.insert(0, Path(frozen_root) / "encap" / UPDATE_PUBLIC_KEY_FILE)
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            continue
        if value:
            return value
    raise UpdateConfigurationError(
        "This build does not contain an update-signing public key."
    )


def check_for_update(
    *,
    current_version: str = __version__,
    manifest_url: str = UPDATE_MANIFEST_URL,
    public_key: str | None = None,
    platform_key: str | None = None,
    timeout_seconds: float = 15.0,
) -> UpdateRelease | None:
    request = urllib.request.Request(
        manifest_url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_manifest = response.read(MAX_MANIFEST_SIZE + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not contact GitHub for updates: {exc}") from exc
    if len(raw_manifest) > MAX_MANIFEST_SIZE:
        raise UpdateError("The update manifest is unexpectedly large.")
    release = parse_update_manifest(
        raw_manifest,
        public_key=public_key or load_update_public_key(),
        platform_key=platform_key,
    )
    return release if is_newer_version(release.version, current_version) else None


def download_update(
    release: UpdateRelease,
    *,
    destination_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    download_dir = destination_dir or Path(tempfile.mkdtemp(prefix="encap-download-"))
    download_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(urllib.parse.urlparse(release.asset.url).path).name
    if not filename:
        filename = f"EnCap-{release.version}.{release.asset.archive}"
    destination = download_dir / filename
    request = urllib.request.Request(release.asset.url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                if downloaded + len(chunk) > release.asset.size:
                    raise OSError("The update exceeds its signed download size.")
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, release.asset.size)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise UpdateError(f"Could not download the update: {exc}") from exc
    if downloaded != release.asset.size:
        destination.unlink(missing_ok=True)
        raise UpdateError(
            f"The update download was incomplete ({downloaded} of {release.asset.size} bytes)."
        )
    if digest.hexdigest() != release.asset.sha256:
        destination.unlink(missing_ok=True)
        raise UpdateError("The downloaded update failed SHA-256 verification.")
    return destination


def _safe_extract_archive(archive_path: Path, archive_kind: str, destination: Path) -> None:
    destination_resolved = destination.resolve()

    def safe_target(member_name: str) -> Path:
        target = (destination / member_name).resolve()
        if target != destination_resolved and destination_resolved not in target.parents:
            raise UpdateError("The update archive contains an unsafe path.")
        return target

    if archive_kind == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                safe_target(member.filename)
                unix_mode = member.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise UpdateError("The update archive contains an unsupported symbolic link.")
            archive.extractall(destination)
        return
    if archive_kind == "tar.gz":
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                safe_target(member.name)
                if member.issym() or member.islnk() or member.isdev():
                    raise UpdateError("The update archive contains an unsupported special file.")
            archive.extractall(destination, filter="data")
        return
    raise UpdateError(f"Unsupported update archive type: {archive_kind}")


def installed_app_dir() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    if sys.platform == "darwin":
        return Path(sys.executable).resolve().parents[2]
    return Path(sys.executable).resolve().parent


def prepare_update(
    release: UpdateRelease,
    archive_path: Path,
    *,
    target_dir: Path | None = None,
) -> PreparedUpdate:
    target = (target_dir or installed_app_dir())
    if target is None:
        raise UpdateConfigurationError(
            "Automatic installation is only available in a packaged EnCap application."
        )
    target = target.resolve()
    executable_name = "EnCap.exe" if sys.platform == "win32" else "EnCap"
    if not (target / executable_name).is_file():
        raise UpdateError(f"The installed application is missing {executable_name}.")

    extraction_root = Path(tempfile.mkdtemp(prefix="encap-extract-"))
    try:
        _safe_extract_archive(archive_path, release.asset.archive, extraction_root)
        payload_candidates = [
            path.parent
            for path in extraction_root.rglob(executable_name)
            if path.parent.name == "EnCap"
        ]
        if len(payload_candidates) != 1:
            raise UpdateError("The update archive does not contain exactly one EnCap application.")
        staging = target.parent / f".encap-update-{release.version}-{uuid.uuid4().hex[:8]}"
        shutil.copytree(payload_candidates[0], staging, symlinks=False)
    finally:
        shutil.rmtree(extraction_root, ignore_errors=True)
    return PreparedUpdate(release.version, target, staging, executable_name)


def launch_update_helper(prepared: PreparedUpdate) -> None:
    helper_name = "encap_updater.exe" if sys.platform == "win32" else "encap_updater"
    bundled_helper = prepared.target_dir / helper_name
    if not bundled_helper.is_file():
        raise UpdateConfigurationError(f"The packaged updater helper {helper_name} is missing.")

    helper_dir = Path(tempfile.mkdtemp(prefix="encap-updater-"))
    helper_copy = helper_dir / helper_name
    shutil.copy2(bundled_helper, helper_copy)
    helper_copy.chmod(helper_copy.stat().st_mode | stat.S_IXUSR)
    instruction_path = helper_dir / "instruction.json"
    instruction_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "target_dir": str(prepared.target_dir),
                "staged_dir": str(prepared.staged_dir),
                "executable_name": prepared.executable_name,
                "version": prepared.version,
            }
        ),
        encoding="utf-8",
    )
    kwargs: dict[str, Any] = {
        "cwd": str(helper_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [str(helper_copy), "--apply-update", str(instruction_path)],
        **kwargs,
    )
