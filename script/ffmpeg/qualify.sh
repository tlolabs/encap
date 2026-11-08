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
# Transcription has a distinct shared runtime/model qualification. Generic
# FFmpeg contracts run on every target, including targets awaiting an AVID port.
cargo test --manifest-path "$ROOT/Cargo.toml" --locked -p encap-engine --test media_contract -- --ignored --skip transcript_mode_uses_packaged_avid_core
# Production discovery must also ignore poisoned explicit environment inputs.
ENCAP_FFMPEG=/missing ENCAP_FFPROBE=/missing "$ENGINE" validate-tools
META="$BIN/ffmpeg-runtime"; [[ -d "$META" ]] || META="$BIN/../Resources/FFmpeg"
TARGET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target"])' "$META/build.json")"
python3 "$ROOT/script/ffmpeg_runtime.py" validate "$TARGET" --binary "$BIN" --metadata "$META"
# Use the original source payload to test relocated packages and damage rejection.
RUNTIME="${ENCAP_FFMPEG_RUNTIME:-$(python3 "$ROOT/script/ffmpeg_runtime.py" provision "$TARGET")}"
python3 "$ROOT/script/test_ffmpeg_runtime.py" --engine "$ENGINE" --runtime "$RUNTIME" --target "$TARGET"
printf 'Packaged discovery, media contracts, and no-fallback rejection passed.\n'
