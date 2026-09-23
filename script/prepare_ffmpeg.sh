#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?platform}-${2:?architecture}"
case "${3:-build}" in
  key) exec python3 "$ROOT/script/ffmpeg_build.py" fingerprint "$TARGET";;
  clean) exec python3 "$ROOT/script/ffmpeg_build.py" build "$TARGET" --clean;;
  build) exec python3 "$ROOT/script/ffmpeg_runtime.py" provision "$TARGET";;
  *) echo 'Expected build, key, or clean' >&2; exit 2;;
esac
