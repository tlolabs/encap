#!/usr/bin/env bash
# Isolated qualification app; normal release packaging remains gated on qualification.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${1:?validated Core runtime}"
TEMPLATE="${2:-$ROOT/dist/EnCap.app}"
ARCH="$(uname -m)"
TARGET="macos-$ARCH"
CORE="$(bash "$ROOT/script/check_core_runtime.sh")"
PYTHON="${PYTHON:-python3}"
$PYTHON "$CORE/scripts/ffmpeg/host.py" verify "$TARGET" "$RUNTIME" --candidate
[[ -d "$TEMPLATE/Contents/MacOS" ]] || { echo 'Existing app template required for bundled transcription helpers.' >&2; exit 1; }
WORK="$ROOT/build/runtime-qualification"
mkdir -p "$WORK"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
export MACOSX_DEPLOYMENT_TARGET=13.0
cargo build --manifest-path "$ROOT/Cargo.toml" --locked --release -p encap-engine --features managed-runtime --target-dir "$WORK/rust"
xcodebuild -project "$ROOT/macos/EnCap.xcodeproj" -scheme EnCap -configuration Release -derivedDataPath "$WORK/xcode" CODE_SIGNING_ALLOWED=NO ARCHS="$ARCH" ONLY_ACTIVE_ARCH=YES build
STAGE="$(mktemp -d "$WORK/package.XXXXXX")"
APP="$STAGE/EnCap Runtime Qualification.app"
ditto "$TEMPLATE" "$APP"
MACOS="$APP/Contents/MacOS"
RESOURCES="$APP/Contents/Resources"
rm "$MACOS/ffmpeg" "$MACOS/ffprobe"
rm -f "$RESOURCES/FFMPEG_LICENSE.txt" "$RESOURCES/FFMPEG_BUILD_CONFIGURATION.txt"
cp "$WORK/rust/release/encap-engine" "$MACOS/encap-engine"
cp "$WORK/xcode/Build/Products/Release/EnCap.app/Contents/MacOS/EnCap" "$MACOS/EnCap"
$PYTHON "$CORE/scripts/ffmpeg/host.py" stage "$TARGET" "$RUNTIME" --destination "$MACOS" --candidate
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier com.tlolabs.encap.runtimequalification' "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName EnCap Runtime Qualification' "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :SUEnableAutomaticChecks false' "$APP/Contents/Info.plist"
printf '%s\n' '{"distribution":"local qualification candidate","runtime_notices":"FFmpeg/licenses/","original_runtime_layout":{"executables":"Contents/MacOS/","metadata_and_notices":"Contents/Resources/FFmpeg/"},"source_information":"FFmpeg/SOURCE.json"}' > "$RESOURCES/RUNTIME_QUALIFICATION_ONLY.json"
$PYTHON "$CORE/scripts/ffmpeg/host.py" verify "$TARGET" "$MACOS" --candidate
# Sign executable helpers before relocating verified data to the resource directory.
for NAME in ffmpeg ffprobe encap-engine; do codesign --force --sign - "$MACOS/$NAME"; done
$PYTHON "$CORE/scripts/ffmpeg/host.py" record-signed "$TARGET" "$MACOS"
mkdir -p "$RESOURCES/FFmpeg"
for SOURCE in "$RUNTIME"/*; do
  NAME="${SOURCE##*/}"
  case "$NAME" in
    ffmpeg|ffprobe) ;;
    *) mv "$MACOS/$NAME" "$RESOURCES/FFmpeg/$NAME" ;;
  esac
done
mv "$MACOS/signed-payload.json" "$RESOURCES/FFmpeg/signed-payload.json"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
env -u ENCAP_FFMPEG -u ENCAP_FFPROBE PATH='' "$MACOS/encap-engine" validate-tools
ENCAP_TEST_MANAGED=1 ENCAP_TEST_ENGINE="$MACOS/encap-engine" ENCAP_FFMPEG="$MACOS/ffmpeg" ENCAP_FFPROBE="$MACOS/ffprobe"   cargo test --manifest-path "$ROOT/Cargo.toml" --locked -p encap-engine --features managed-runtime --test media_contract -- --ignored --test-threads=1
ENCAP_TEST_ENGINE="$MACOS/encap-engine" ENCAP_REQUIRE_CLONING=1 \
  cargo test --manifest-path "$ROOT/Cargo.toml" --locked -p encap-engine --features managed-runtime --test save_protocol --test audio_edit_protocol
swift test --package-path "$ROOT/macos" --scratch-path "$ROOT/build/native-swift"
printf '%s\n' "$APP"
