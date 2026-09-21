#!/usr/bin/env bash
# Stage the identical source-built payload in a normal app or a relocated test copy.
set -euo pipefail
PREFIX="${1:?source build prefix}"; BIN="${2:?package executable directory}"; META="${3:-$BIN/ffmpeg-runtime}"
(cd "$PREFIX" && shasum -a 256 -c files.sha256 >&2)
mkdir -p "$BIN" "$META"
SUFFIX=; [[ "$(jq -r .target "$PREFIX/runtime.json")" != windows-* ]] || SUFFIX=.exe
for tool in ffmpeg ffprobe; do
  cp "$PREFIX/bin/$tool$SUFFIX" "$BIN/$tool$SUFFIX"
  chmod +x "$BIN/$tool$SUFFIX"
  # Ad-hoc signatures only, no identity/notarization prerequisite.
  if [[ "$(uname -s)" == Darwin ]]; then codesign --force --sign - "$BIN/$tool" >&2; fi
done
cp "$PREFIX"/*.txt "$PREFIX/dependencies.json" "$META/"
cp -R "$PREFIX/licenses" "$PREFIX/sources" "$PREFIX/recipe" "$META/"
jq --arg ffmpeg "$(shasum -a 256 "$BIN/ffmpeg$SUFFIX" | awk '{print $1}')" --arg ffprobe "$(shasum -a 256 "$BIN/ffprobe$SUFFIX" | awk '{print $1}')" \
  '.source_binaries = .binaries | .binaries = {ffmpeg:$ffmpeg,ffprobe:$ffprobe}' "$PREFIX/runtime.json" > "$META/runtime.json"
