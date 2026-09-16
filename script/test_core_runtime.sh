#!/usr/bin/env bash
# Validate a candidate bundle through every media mode, without PATH fallback.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="${1:?engine}"
RUNTIME="${2:?validated runtime}"
TARGET="${3:?target}"
CORE="$(bash "$ROOT/script/check_core_runtime.sh")"
PYTHON="${PYTHON:-python3}"
SUFFIX=''
[[ "$TARGET" != windows-* ]] || SUFFIX='.exe'
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$ENGINE" "$WORK/encap-engine$SUFFIX"
$PYTHON "$CORE/scripts/ffmpeg/host.py" stage "$TARGET" "$RUNTIME" --destination "$WORK" --candidate
ENCAP_TEST_MANAGED=1 ENCAP_TEST_ENGINE="$WORK/encap-engine$SUFFIX" ENCAP_FFMPEG="$WORK/ffmpeg$SUFFIX" ENCAP_FFPROBE="$WORK/ffprobe$SUFFIX"   cargo test --manifest-path "$ROOT/Cargo.toml" --locked -p encap-engine --features managed-runtime --test media_contract -- --ignored --test-threads=1
for NAME in spec.json build.json "ffmpeg$SUFFIX" "ffprobe$SUFFIX"; do
  mv "$WORK/$NAME" "$WORK/$NAME.original"
  for STATE in missing damaged; do
    if [[ "$STATE" == damaged ]]; then printf damaged > "$WORK/$NAME"; chmod +x "$WORK/$NAME"; fi
    for COMMAND in validate-tools video-capabilities; do
      if env -u ENCAP_FFMPEG -u ENCAP_FFPROBE PATH="$RUNTIME:$PATH" "$WORK/encap-engine$SUFFIX" "$COMMAND" > "$WORK/negative.json" 2>&1; then
        echo "$NAME ($STATE): $COMMAND silently accepted a broken managed bundle" >&2; exit 1
      fi
    done
  done
  rm "$WORK/$NAME"
  mv "$WORK/$NAME.original" "$WORK/$NAME"
done
printf '%s\n' 'All-mode managed media contracts and missing/damaged bundle rejection passed.'
