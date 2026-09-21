#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/script/ffmpeg/build.sh" "${1:?platform}" "${2:?architecture}" "${3:-build}"
