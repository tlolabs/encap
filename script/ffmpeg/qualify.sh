#!/usr/bin/env bash
# Exercise the normal release engine and deliberately damaged relocated packages.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="${1:?packaged release engine}"
BIN="$(cd "$(dirname "$ENGINE")" && pwd)"
ENGINE="$BIN/$(basename "$ENGINE")"
SUFFIX=; [[ "$ENGINE" != *.exe ]] || SUFFIX=.exe
export ENCAP_TEST_ENGINE="$ENGINE" ENCAP_TEST_PACKAGED=1
export ENCAP_FFMPEG="$BIN/ffmpeg$SUFFIX" ENCAP_FFPROBE="$BIN/ffprobe$SUFFIX"
export ENCAP_MODEL_DIR="$ROOT/.build-tools/qualification-models"
export ENCAP_TEST_SPEECH="$ROOT/.whisper-cpp/samples/jfk.wav"
mkdir -p "$ENCAP_MODEL_DIR"
MODEL="$ENCAP_MODEL_DIR/ggml-base.en.bin"
MODEL_SHA=a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002
sha() {
  if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | awk '{print $1}'
}
if [[ ! -f "$MODEL" ]] || [[ "$(sha "$MODEL")" != "$MODEL_SHA" ]]; then
  curl --fail --location --retry 3 'https://huggingface.co/ggerganov/whisper.cpp/resolve/c521a4b02f422512d734391fdf08bb08c0862f68/ggml-base.en.bin?download=true' -o "$MODEL.part"
  [[ "$(sha "$MODEL.part")" == "$MODEL_SHA" ]] || { echo "Test model checksum mismatch" >&2; exit 1; }
  mv "$MODEL.part" "$MODEL"
fi
cargo test --manifest-path "$ROOT/Cargo.toml" --locked -p encap-engine --test media_contract -- --ignored
# Production discovery must also ignore poisoned explicit environment inputs.
ENCAP_FFMPEG=/missing ENCAP_FFPROBE=/missing "$ENGINE" validate-tools
META="$BIN/ffmpeg-runtime"; [[ -d "$META" ]] || META="$BIN/../Resources/FFmpeg"
TARGET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target"])' "$META/build.json")"
python3 "$ROOT/script/ffmpeg_runtime.py" validate "$TARGET" --binary "$BIN" --metadata "$META"
# Use the original source payload to test relocated packages and damage rejection.
RUNTIME="${ENCAP_FFMPEG_RUNTIME:-$ROOT/build/ffmpeg/$TARGET}"
python3 "$ROOT/script/test_ffmpeg_runtime.py" --engine "$ENGINE" --runtime "$RUNTIME" --target "$TARGET"
printf 'Packaged discovery, all-mode contracts, and no-fallback rejection passed.\n'
