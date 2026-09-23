#!/usr/bin/env bash
# The same normal package assembly is used for portable and macOS builds.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="${1:?source payload}"; BIN="${2:?executable directory}"; META="${3:-$BIN/ffmpeg-runtime}"
TARGET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target"])' "$RUNTIME/build.json")"
python3 "$ROOT/script/ffmpeg_runtime.py" stage "$TARGET" --runtime "$RUNTIME" --binary "$BIN"
if [[ "$TARGET" == macos-* ]]; then
  codesign --force --sign - "$BIN/ffmpeg"
  codesign --force --sign - "$BIN/ffprobe"
fi
python3 "$ROOT/script/ffmpeg_runtime.py" finish "$TARGET" --binary "$BIN" --metadata "$META"
python3 "$ROOT/script/ffmpeg_runtime.py" validate "$TARGET" --runtime "$RUNTIME" --binary "$BIN" --metadata "$META"
