#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="$ROOT/../AVID Core"
[[ "$(git -C "$CORE" rev-parse HEAD)" == "$(cat "$ROOT/runtime/core-revision")" ]] || { echo 'Core revision differs from the tested host mapping.' >&2; exit 1; }
printf '%s\n' "$CORE"
