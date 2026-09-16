#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="$ROOT/../AVID Core"
REVISION="$(tr -d '\r\n' < "$ROOT/runtime/core-revision")"
# Cargo compiles the immutable Git dependency. Helpers must use those same sources.
grep -F "avid-core = { git = \"https://github.com/tlolabs/avid-core.git\", rev = \"$REVISION\"" "$ROOT/Cargo.toml" >/dev/null || {
  echo 'Core helper revision differs from the pinned Cargo dependency.' >&2; exit 1;
}
[[ "$(git -C "$CORE" rev-parse HEAD)" == "$REVISION" ]] || {
  echo 'Core checkout differs from the pinned host mapping. Check out the revision in runtime/core-revision.' >&2; exit 1;
}
CORE_STATUS="$(git -C "$CORE" status --porcelain)"
[[ -z "$CORE_STATUS" ]] || {
  echo 'Core checkout has local changes; packaging helpers require the clean pinned source.' >&2; exit 1;
}
printf '%s\n' "$CORE"
