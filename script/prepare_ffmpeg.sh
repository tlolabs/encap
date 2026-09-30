#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?platform}-${2:?architecture}"
case "${3:-build}" in
  key) exec python3 "$ROOT/script/ffmpeg_runtime.py" key "$TARGET";;
  build|clean) exec python3 "$ROOT/script/ffmpeg_runtime.py" provision "$TARGET";;
  *) echo 'Expected build, key, or clean (Core artifact acquisition)' >&2; exit 2;;
esac
