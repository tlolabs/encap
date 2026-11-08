#!/usr/bin/env bash
# Build/stage the isolated Apple-silicon shared transcription runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINATION="${1:?destination directory for avid-transcriber and its resources}"
PACKAGE="$ROOT/helpers/avid_transcriber"
SCRATCH="${ENCAP_AVID_BUILD_DIR:-$ROOT/.build-tools/avid-transcriber-build}"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "AVID transcription builds require an Apple-silicon Mac; base EnCap builds remain independent." >&2
  exit 2
fi
ruby "$ROOT/script/verify_avid_snapshot.rb" >&2
# Swift's build engine compiles MLX Metal resources. The deprecated native build
# system may produce an executable without a usable metallib.
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-$SCRATCH/clang-cache}"
export SWIFTPM_MODULECACHE_OVERRIDE="${SWIFTPM_MODULECACHE_OVERRIDE:-$SCRATCH/module-cache}"
export MACOSX_DEPLOYMENT_TARGET=14.0
swift build --disable-sandbox --build-system swiftbuild --package-path "$PACKAGE" \
  --scratch-path "$SCRATCH" --configuration release --force-resolved-versions \
  --product avid-transcriber >&2
BIN="$(swift build --disable-sandbox --build-system swiftbuild --package-path "$PACKAGE" \
  --scratch-path "$SCRATCH" --configuration release --show-bin-path)"
python3 "$ROOT/script/stage_avid_transcriber.py" --binary-directory "$BIN" --destination "$DESTINATION" \
  --checkouts "$SCRATCH/checkouts" --resolved "$PACKAGE/Package.resolved"
