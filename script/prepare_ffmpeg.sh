#!/usr/bin/env bash
# Host packaging only: the same pinned distribution inputs as ATIV's fetch recipe.
# No runtime fallback, second media pair, or FFmpeg implementation lives here.
set -euo pipefail
PLATFORM="${1:?platform}"
ARCH="${2:?architecture}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="$ROOT_DIR/.build-tools/ffmpeg-9.0.1-install-$ARCH"
RECIPE_HASH="$(shasum -a 256 "$ROOT_DIR/script/fetch_ffmpeg.sh" | awk '{print $1}')"
if [[ -f "$INSTALL_DIR/artifact-recipe" && "$(cat "$INSTALL_DIR/artifact-recipe")" == "$RECIPE_HASH" ]] && \
   (cd "$INSTALL_DIR" && shasum -a 256 --check binaries.sha256 >&2); then
  printf '%s\n' "$INSTALL_DIR"
  exit 0
fi
mkdir -p "$ROOT_DIR/.build-tools"
STAGE="$(mktemp -d "$ROOT_DIR/.build-tools/ffmpeg-artifact.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
"$ROOT_DIR/script/fetch_ffmpeg.sh" "$PLATFORM" "$ARCH" "$STAGE/bin" >&2
printf '%s\n' "$RECIPE_HASH" > "$STAGE/artifact-recipe"
(cd "$STAGE" && shasum -a 256 bin/ffmpeg bin/ffprobe > binaries.sha256)
# Replace the previous build in its existing location; never retain a Video pair.
rm -rf "$INSTALL_DIR"
mv "$STAGE" "$INSTALL_DIR"
printf '%s\n' "$INSTALL_DIR"
