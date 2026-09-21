#!/usr/bin/env bash
# Native source-build entrypoint shared by all media modes.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/script/prepare_ffmpeg.sh" macos "$(uname -m)"
