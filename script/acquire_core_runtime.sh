#!/usr/bin/env bash
# Host passes target and destination; Core owns versions, recipes and artifact trust.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="$(bash "$ROOT/script/check_core_runtime.sh")"
exec "${PYTHON:-python3}" "$CORE/scripts/ffmpeg/acquire.py" "${1:?canonical target}" "${2:?destination}"
