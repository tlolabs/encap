#!/usr/bin/env bash
# Compatibility entrypoint: package the approved common artifact for every mode.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/script/prepare_ffmpeg.sh" linux "$(uname -m)"
