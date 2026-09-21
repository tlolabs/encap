#!/usr/bin/env bash
# Historical entrypoint: now always compiles verified official source.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="$(bash "$ROOT/script/prepare_ffmpeg.sh" "${1:?platform}" "${2:?architecture}")"
exec bash "$ROOT/script/ffmpeg/stage.sh" "$PREFIX" "${3:?destination}"
