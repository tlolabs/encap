#!/usr/bin/env python3
"""Rebuild AVID's small model catalog from pinned, public upstream metadata.

No model weights are hosted or downloaded by this script. SHA-256 values for LFS
objects come from the pinned Hugging Face Git/LFS metadata; ordinary Git files
are fetched, checked against their Git blob ID, and SHA-256 hashed locally.
Run --check for an offline structural check or --verify-upstream to compare the
bundled catalog with the same immutable upstream revisions without writing it.
Updating a source pin is an intentional source edit to SOURCES below.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "apple/AVIDTranscription/Sources/AVIDTranscription/Resources/models.json"
SOURCES = {
    "argmaxinc/whisperkit-coreml": "0f63a7800b00dd0226abd051b906c246e1907482",
    "openai/whisper-large-v3": "06f233fe06e710322aca913c1bc4249a0d71fce1",
    "FluidInference/parakeet-tdt-0.6b-v3-coreml": "7dd20fe6b1797d35f5e3307e8b1732d9a178edfe",
    "mlx-community/Qwen3-ASR-1.7B-4bit": "78a389c776a5483b2d0d4ea5494e11012e0d6159",
    "mlx-community/Qwen3-ForcedAligner-0.6B-4bit": "2f652af86ae0c73fe189b9429225c908ce4bf020",
}
WHISPER_LANGUAGES = "af am ar as az ba be bg bn bo br bs ca cs cy da de el en es et eu fa fi fo fr gl gu haw ha he hi hr ht hu hy id is it ja jw ka kk km kn ko la lb ln lo lt lv mg mi mk ml mn mr ms mt my ne nl nn no oc pa pl ps pt ro ru sa sd si sk sl sn so sq sr su sv sw ta te tg th tk tl tr tt uk ur uz vi yi yo yue zh".split()
PARAKEET_LANGUAGES = "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro ru sk sl es sv uk".split()
QWEN_LANGUAGES = "zh en yue ar de fr es pt id it ko ru th vi ja tr hi ms nl sv da fi pl cs fil fa el hu mk ro".split()
ALIGNMENT_LANGUAGES = "zh en yue fr de it ja ko pt ru es".split()
WHISPER_LICENSE = {
    "identifier": "MIT AND Apache-2.0",
    "notice": "Whisper Core ML conversion: Argmax, Inc. (MIT, as declared by the converted model repository). Original Whisper large-v3 model/tokenizer: OpenAI (Apache-2.0, as declared by its pinned model card). Retain both upstream notices; see MODEL_NOTICES.md.",
    "url": "https://huggingface.co/argmaxinc/whisperkit-coreml",
}
PARAKEET_LICENSE = {
    "identifier": "CC-BY-4.0",
    "notice": "Parakeet TDT 0.6B v3: NVIDIA. Core ML conversion: FluidInference. Licensed under Creative Commons Attribution 4.0; credit NVIDIA and FluidInference, link to CC-BY-4.0, and indicate conversion/quantization changes. The FluidAudio SDK's Apache-2.0 license is separate.",
    "url": "https://creativecommons.org/licenses/by/4.0/",
}
QWEN_LICENSE = {
    "identifier": "Apache-2.0",
    "notice": "Qwen3-ASR / Qwen3-ForcedAligner: Qwen Team, Alibaba Cloud. MLX conversion and 4-bit quantization: MLX Community. Apache License 2.0. Retain license, copyright, and any upstream NOTICE files; indicate conversion/quantization changes.",
    "url": "https://www.apache.org/licenses/LICENSE-2.0",
}
MLX_FILES = {"chat_template.json", "config.json", "generation_config.json", "merges.txt", "model.safetensors", "model.safetensors.index.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.json"}
TOKENIZER_FILES = {"tokenizer.json", "tokenizer_config.json", "config.json"}
FLUID_DIRECTORIES = {"Preprocessor.mlmodelc", "Encoder_v2.mlmodelc", "Decoder.mlmodelc", "JointDecisionv3.mlmodelc"}


def safe_relative_path(value: str) -> bool:
    """Allow ordinary repository filenames without traversal or URL syntax."""
    return bool(value) and not value.startswith("/") and all(part not in {"", ".", ".."} for part in value.split("/")) and "\\" not in value and not any(ch in value for ch in "?#%\x00") and str(PurePosixPath(value)) == value


def read_url(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AVIDCore-Transcription-Catalog/1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Upstream response exceeds {limit} bytes: {url}")
    return data


def load_metadata(repository: str) -> dict:
    revision = SOURCES[repository]
    url = f"https://huggingface.co/api/models/{repository}/revision/{revision}?blobs=true"
    data = json.loads(read_url(url, 16 * 1024 * 1024))
    if data.get("sha") != revision or data.get("private") is not False or data.get("gated") is not False:
        raise ValueError(f"Expected immutable public, ungated source {repository}@{revision}")
    return data


def artifact_for(repository: str, record: dict, local_path: str, primary_repository: str) -> dict:
    repository_path = record["rfilename"]
    if not safe_relative_path(local_path) or not safe_relative_path(repository_path):
        raise ValueError(f"Unsafe artifact path: {repository_path}")
    size = record.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError(f"Missing artifact size: {repository_path}")
    lfs = record.get("lfs")
    if lfs:
        digest = lfs.get("sha256", "")
        if size != lfs.get("size") or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid LFS object metadata: {repository_path}")
    else:
        if size > 32 * 1024 * 1024:
            raise ValueError(f"Refusing large non-LFS artifact: {repository_path}")
        url = f"https://huggingface.co/{repository}/resolve/{SOURCES[repository]}/{urllib.parse.quote(repository_path, safe='/')}"
        payload = read_url(url, 32 * 1024 * 1024)
        if len(payload) != size:
            raise ValueError(f"Artifact size mismatch: {repository_path}")
        blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        if blob != record.get("blobId"):
            raise ValueError(f"Git blob mismatch: {repository_path}")
        digest = hashlib.sha256(payload).hexdigest()
    artifact = {"path": local_path, "repositoryPath": repository_path, "sizeBytes": size, "sha256": digest}
    if repository != primary_repository:
        artifact.update(repository=repository, revision=SOURCES[repository])
    return artifact


def build_catalog() -> dict:
    with ThreadPoolExecutor(max_workers=5) as pool:
        metadata = dict(zip(SOURCES, pool.map(load_metadata, SOURCES)))
    specs = [
        ("whisper-large-v3", "Whisper large-v3 · Quality", "whisperKit", "recognizer", "argmaxinc/whisperkit-coreml", "openai_whisper-large-v3/", WHISPER_LANGUAGES, WHISPER_LANGUAGES, WHISPER_LICENSE),
        ("whisper-large-v3-turbo", "Whisper large-v3 Turbo · Faster", "whisperKit", "recognizer", "argmaxinc/whisperkit-coreml", "openai_whisper-large-v3-v20240930/", WHISPER_LANGUAGES, WHISPER_LANGUAGES, WHISPER_LICENSE),
        ("parakeet-tdt-v3", "Parakeet TDT 0.6B v3", "fluidAudio", "recognizer", "FluidInference/parakeet-tdt-0.6b-v3-coreml", "", PARAKEET_LANGUAGES, PARAKEET_LANGUAGES, PARAKEET_LICENSE),
        ("qwen3-asr-1.7b-4bit", "Qwen3-ASR 1.7B · 4-bit", "mlx", "recognizer", "mlx-community/Qwen3-ASR-1.7B-4bit", "", QWEN_LANGUAGES, [], QWEN_LICENSE),
        ("qwen3-forced-aligner-0.6b-4bit", "Qwen3 ForcedAligner 0.6B · 4-bit", "mlx", "aligner", "mlx-community/Qwen3-ForcedAligner-0.6B-4bit", "", [], ALIGNMENT_LANGUAGES, QWEN_LICENSE),
    ]
    models = []
    # Cache shared Whisper tokenizer hashes: both models use the same tokenizer.
    tokenizer_artifacts = None
    for model_id, name, engine, role, repository, prefix, recognition, timing, license_info in specs:
        records = metadata[repository]["siblings"]
        selected = []
        for record in records:
            path = record["rfilename"]
            if engine == "whisperKit":
                if not path.startswith(prefix):
                    continue
                local_path = path[len(prefix):]
            elif engine == "fluidAudio":
                if path.split("/")[0] not in FLUID_DIRECTORIES and path not in {"parakeet_vocab.json", "config.json"}:
                    continue
                local_path = path
            else:
                if path not in MLX_FILES:
                    continue
                local_path = path
            selected.append((repository, record, local_path, repository))
        with ThreadPoolExecutor(max_workers=8) as pool:
            artifacts = list(pool.map(lambda args: artifact_for(*args), selected))
        if engine == "whisperKit":
            if tokenizer_artifacts is None:
                token_records = [record for record in metadata["openai/whisper-large-v3"]["siblings"] if record["rfilename"] in TOKENIZER_FILES]
                tokenizer_artifacts = [artifact_for("openai/whisper-large-v3", record, "tokenizer/" + record["rfilename"], repository) for record in token_records]
            artifacts += tokenizer_artifacts
        if not artifacts:
            raise ValueError(f"No artifacts selected for {model_id}")
        models.append({"id": model_id, "displayName": name, "engine": engine, "role": role, "repository": repository, "revision": SOURCES[repository], "modelSubdirectory": ".", "recognitionLanguages": sorted(recognition), "timingLanguages": sorted(timing), "license": license_info, "artifacts": sorted(artifacts, key=lambda artifact: artifact["path"])})
    catalog = {"schemaVersion": 1, "defaultModelID": "whisper-large-v3", "models": models}
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: dict) -> None:
    if catalog.get("schemaVersion") != 1 or catalog.get("defaultModelID") != "whisper-large-v3":
        raise ValueError("Unexpected catalog schema or default model")
    ids = set()
    models = catalog.get("models", [])
    expected = {"whisper-large-v3", "whisper-large-v3-turbo", "parakeet-tdt-v3", "qwen3-asr-1.7b-4bit", "qwen3-forced-aligner-0.6b-4bit"}
    for model in models:
        model_id = model["id"]
        if model_id in ids:
            raise ValueError(f"Duplicate model: {model_id}")
        ids.add(model_id)
        repository, revision = model["repository"], model["revision"]
        if SOURCES.get(repository) != revision or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError(f"Unpinned/unknown repository for {model_id}")
        if model["engine"] not in {"whisperKit", "fluidAudio", "mlx"} or model["role"] not in {"recognizer", "aligner"}:
            raise ValueError(f"Invalid engine/role for {model_id}")
        if model.get("modelSubdirectory") != "." or not all(model["license"].get(key) for key in ("identifier", "notice", "url")):
            raise ValueError(f"Missing layout or license for {model_id}")
        for key in ("recognitionLanguages", "timingLanguages"):
            codes = model[key]
            if len(codes) != len(set(codes)) or any(not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", code) for code in codes):
                raise ValueError(f"Invalid language list for {model_id}")
        paths = set()
        for artifact in model["artifacts"]:
            local_path = artifact["path"]
            if local_path in paths or not safe_relative_path(local_path) or not safe_relative_path(artifact["repositoryPath"]):
                raise ValueError(f"Duplicate/unsafe artifact path for {model_id}: {local_path}")
            paths.add(local_path)
            source = artifact.get("repository", repository)
            pin = artifact.get("revision", revision)
            if ("repository" in artifact) != ("revision" in artifact) or SOURCES.get(source) != pin:
                raise ValueError(f"Unpinned auxiliary source for {model_id}: {local_path}")
            if not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
                raise ValueError(f"Invalid SHA256 for {model_id}: {local_path}")
            if not isinstance(artifact["sizeBytes"], int) or isinstance(artifact["sizeBytes"], bool) or artifact["sizeBytes"] < 0:
                raise ValueError(f"Invalid size for {model_id}: {local_path}")
        if model["engine"] == "whisperKit":
            required = {"AudioEncoder.mlmodelc/weights/weight.bin", "TextDecoder.mlmodelc/weights/weight.bin", "MelSpectrogram.mlmodelc/weights/weight.bin"} | {"tokenizer/" + file for file in TOKENIZER_FILES}
        elif model["engine"] == "fluidAudio":
            required = {directory + "/weights/weight.bin" for directory in FLUID_DIRECTORIES} | {"parakeet_vocab.json"}
        else:
            required = MLX_FILES
        if not required.issubset(paths):
            raise ValueError(f"Missing required runtime artifacts for {model_id}: {sorted(required - paths)}")
    if ids != expected:
        raise ValueError(f"Unexpected model set: {sorted(ids)}")
    if next(model for model in models if model["id"] == "qwen3-asr-1.7b-4bit")["timingLanguages"]:
        raise ValueError("Qwen recognition must not claim native word timing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate the bundled catalog without network access or changes")
    mode.add_argument("--verify-upstream", action="store_true", help="Recompute from pinned upstream metadata and compare without writing")
    args = parser.parse_args()
    if args.check:
        catalog = json.loads(args.output.read_text())
        validate_catalog(catalog)
    else:
        catalog = build_catalog()
        if args.verify_upstream:
            existing = json.loads(args.output.read_text())
            if existing != catalog:
                raise ValueError("Bundled catalog does not match immutable upstream artifacts")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    for model in catalog["models"]:
        print(f'{model["id"]}: {len(model["artifacts"])} files, {sum(artifact["sizeBytes"] for artifact in model["artifacts"]):,} bytes, {model["repository"]}@{model["revision"]}')
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        print(f"Catalog error: {error}", file=sys.stderr)
        sys.exit(1)
