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
if [[ ! -f "$MODEL" ]] || [[ "$(shasum -a 256 "$MODEL" | awk '{print $1}')" != "$MODEL_SHA" ]]; then
  curl --fail --location --retry 3 'https://huggingface.co/ggerganov/whisper.cpp/resolve/c521a4b02f422512d734391fdf08bb08c0862f68/ggml-base.en.bin?download=true' -o "$MODEL.part"
  echo "$MODEL_SHA  $MODEL.part" | shasum -a 256 -c -
  mv "$MODEL.part" "$MODEL"
fi
cargo test --manifest-path "$ROOT/Cargo.toml" --locked -p encap-engine --test media_contract -- --ignored
# Production discovery must also ignore poisoned explicit environment inputs.
ENCAP_FFMPEG=/missing ENCAP_FFPROBE=/missing "$ENGINE" validate-tools
TEMP="$(mktemp -d)"; trap 'rm -rf "$TEMP"' EXIT
mkdir -p "$TEMP/FFmpeg"
cp "$ENGINE" "$TEMP/encap-engine$SUFFIX"
META="$BIN/FFmpeg"; [[ -d "$META" ]] || META="$BIN/../Resources/FFmpeg"
cp "$META/runtime.json" "$TEMP/FFmpeg/"
cp "$BIN/ffmpeg$SUFFIX" "$BIN/ffprobe$SUFFIX" "$TEMP/"
# Release engine relocation uses the same ordinary portable layout as Windows/Linux.
for damaged in ffmpeg ffprobe manifest; do
  case "$damaged" in
    manifest) victim="$TEMP/FFmpeg/runtime.json";;
    *) victim="$TEMP/$damaged$SUFFIX";;
  esac
  mv "$victim" "$victim.saved"
  if PATH="$BIN:$PATH" "$TEMP/encap-engine$SUFFIX" validate-tools; then echo "Accepted missing $damaged" >&2; exit 1; fi
  printf 'damaged' > "$victim"
  if PATH="$BIN:$PATH" "$TEMP/encap-engine$SUFFIX" validate-tools; then echo "Accepted corrupt $damaged" >&2; exit 1; fi
  mv "$victim.saved" "$victim"
done
"$TEMP/encap-engine$SUFFIX" validate-tools
printf 'Packaged discovery, all-mode contracts, and no-fallback rejection passed.\n'
