#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
# Check distribution prerequisites before provisioning, building or replacing bundles.
if [[ "$MODE" == --package || "$MODE" == package ]]; then
  : "${ENCAP_SIGN_IDENTITY:?Set ENCAP_SIGN_IDENTITY to a Developer ID Application identity}"
  : "${ENCAP_NOTARY_PROFILE:?Set ENCAP_NOTARY_PROFILE to an existing notarytool Keychain profile (or use --package-development explicitly)}"
  [[ "$ENCAP_SIGN_IDENTITY" != "-" ]] || { echo "Developer ID signing is required for distributable packages." >&2; exit 2; }
  if ! security find-identity -v -p codesigning | grep 'Developer ID Application:' | grep -F -- "$ENCAP_SIGN_IDENTITY" >/dev/null; then
    echo "A valid Developer ID Application identity is required." >&2; exit 2
  fi
  # Validate the saved profile without uploading an app or changing credentials.
  xcrun notarytool history --keychain-profile "$ENCAP_NOTARY_PROFILE" --output-format json >/dev/null
fi
APP_NAME="EnCap"
BUNDLE_ID="com.tlolabs.encap"
SPARKLE_VERSION="2.9.6"
SPARKLE_SHA256="52bf9e88cdd972fc0c81501377a880e90d47031bd8ca5462488f843e2609e192"

HOST_ARCH="$(uname -m)"
NATIVE_ARCH="${ENCAP_BUILD_ARCH:-$HOST_ARCH}"
case "$NATIVE_ARCH" in
  arm64) ARCH_LABEL="arm64" ;;
  x86_64) ARCH_LABEL="intel" ;;
  *)
    echo "Unsupported macOS architecture: $NATIVE_ARCH" >&2
    exit 1
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$MODE" == "--qt-reference" ]]; then
  exec python3 "$ROOT_DIR/script/build_qt.py" --rid osx-arm64 --tools "$ROOT_DIR/dist/EnCap.app/Contents/MacOS" --run
fi
"$ROOT_DIR/script/check_no_python.sh"
CARGO="${CARGO:-$HOME/.cargo/bin/cargo}"
APP_BUNDLE="${ENCAP_BUILD_BUNDLE:-$ROOT_DIR/dist/EnCap.app}"
if [[ "$NATIVE_ARCH" != "$HOST_ARCH" && -z "${ENCAP_BUILD_BUNDLE:-}" ]]; then
  APP_BUNDLE="$ROOT_DIR/dist/$ARCH_LABEL/EnCap.app"
fi
python3 - "$APP_BUNDLE" "$ROOT_DIR" <<'PY_BUNDLE'
from pathlib import Path
import sys
bundle, root = map(Path, sys.argv[1:])
if not bundle.is_absolute() or bundle.name != 'EnCap.app' or bundle.is_symlink() or not bundle.parent.resolve().is_relative_to((root / 'dist').resolve()):
    raise SystemExit('Development bundle must be an owned EnCap.app below this checkout dist directory.')
PY_BUNDLE
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_FRAMEWORKS="$APP_CONTENTS/Frameworks"
APP_BINARY="$APP_MACOS/EnCap"
APP_LIBRARY="$APP_FRAMEWORKS/libencap_app.dylib"
LINKED_RECEIPT="$ROOT_DIR/build/linked-$NATIVE_ARCH.json"
INFO_PLIST="$APP_CONTENTS/Info.plist"
XCODE_PROJECT="$ROOT_DIR/macos/EnCap.xcodeproj"
XCODE_BUILD_DIR="$ROOT_DIR/build/xcode-$NATIVE_ARCH"
XCODE_APP="$XCODE_BUILD_DIR/Build/Products/Release/EnCap.app"
SPARKLE_DIR="$ROOT_DIR/.sparkle"
SPARKLE_VERSION_DIR="$SPARKLE_DIR/$SPARKLE_VERSION"
SPARKLE_ARCHIVE="$SPARKLE_DIR/Sparkle-$SPARKLE_VERSION.tar.xz"
SPARKLE_FRAMEWORK="$SPARKLE_VERSION_DIR/Sparkle.framework"
PUBLIC_KEY_FILE="$ROOT_DIR/.encap-update-public-key"
APPLE_AAC_INFO="$ROOT_DIR/.build-tools/$NATIVE_ARCH/apple-aac-info"
AVID_RUNTIME="$ROOT_DIR/.build-tools/avid-transcription-linked-runtime/EnCAPTranscription.framework"
XCODE_DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ICON_DOCUMENT="$ROOT_DIR/assets/icons/liquid-glass/AppIcon.icon"
LEGACY_ICON="$ROOT_DIR/assets/icons/EnCap.icns"
ICON_REPORT="$ROOT_DIR/build/icon-assets.json"

has_linker_signature() {
  codesign -dvv "$1" 2>&1 | grep 'linker-signed' >/dev/null
}

if [[ ! -x "$CARGO" ]]; then
  echo "Missing Rust toolchain: $CARGO" >&2
  echo "Install Rust with rustup before building EnCap." >&2
  exit 1
fi
if [[ ! -s "$PUBLIC_KEY_FILE" ]]; then
  echo "Missing update public key: $PUBLIC_KEY_FILE" >&2
  echo "Set ENCAP_UPDATE_PUBLIC_KEY in GitHub and place the same public key at this path." >&2
  exit 1
fi
if [[ ! -x "$XCODE_DEVELOPER_DIR/usr/bin/xcodebuild" ]]; then
  echo "Missing Xcode build tool: $XCODE_DEVELOPER_DIR/usr/bin/xcodebuild" >&2
  exit 1
fi
if [[ ! -d "$ICON_DOCUMENT" ]]; then
  echo "Missing Icon Composer document: $ICON_DOCUMENT" >&2
  exit 1
fi

if pgrep -f "^$APP_BINARY( |$)" >/dev/null; then
  echo "Close the running app after saving your work before replacing its development bundle." >&2
  exit 1
fi

APP_VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -n 1)"
UPDATE_PUBLIC_KEY="$(tr -d '\r\n' < "$PUBLIC_KEY_FILE")"
ENCAP_PLATFORM_NAME="macos-$ARCH_LABEL"
# Audio export remains an unfinished compatibility path. Retain its authenticated
# executable runtime until the upstream chaptered-audio contract is implemented.
FFMPEG_INSTALL_DIR="$("$ROOT_DIR/script/prepare_ffmpeg.sh" macos "$NATIVE_ARCH" | tail -n 1)"
LINKED_TARGET="macos-$NATIVE_ARCH"
LINKED_PROFILE="${ENCAP_LINKED_PROFILE:-apple-gpl}"
LINKED_ARGS=(--target "$LINKED_TARGET" --profile "$LINKED_PROFILE")
if [[ -n "${ENCAP_LINKED_SDK:-}" ]]; then
  LINKED_ARGS+=(--prefix "$ENCAP_LINKED_SDK")
else
  LINKED_WORK="${ENCAP_LINKED_WORK:-/private/tmp/encap-linked-sdk-$LINKED_TARGET-$LINKED_PROFILE}"
  if [[ -f "$LINKED_WORK/prefix/linked-ffmpeg.json" ]]; then
    LINKED_ARGS+=(--prefix "$LINKED_WORK/prefix")
  else
    LINKED_ARGS+=(--work "$LINKED_WORK")
  fi
fi
mkdir -p "$ROOT_DIR/build"
python3 "$ROOT_DIR/script/linked_runtime.py" provision "${LINKED_ARGS[@]}" --fetch > "$ROOT_DIR/build/linked-sdk-$NATIVE_ARCH.json"
LINKED_PREFIX="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["prefix"])' "$ROOT_DIR/build/linked-sdk-$NATIVE_ARCH.json")"
export AVID_FFMPEG_PREFIX="$LINKED_PREFIX" AVID_FFMPEG_STATIC=1
python3 "$ROOT_DIR/script/linked_runtime.py" build --target "$LINKED_TARGET" --profile "$LINKED_PROFILE" \
  --prefix "$LINKED_PREFIX" --target-dir "$ROOT_DIR/target" --receipt "$LINKED_RECEIPT" > "$ROOT_DIR/build/linked-build-$NATIVE_ARCH.json"
RUST_LIBRARY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["library"])' "$ROOT_DIR/build/linked-build-$NATIVE_ARCH.json")"
LOCK_HASH="$(shasum -a 256 "$ROOT_DIR/Cargo.lock" | cut -d ' ' -f 1)"
LINKED_SOURCES="${ENCAP_LINKED_SOURCE_BUNDLE:-$ROOT_DIR/build/linked-cargo-sources-$LOCK_HASH.tar.gz}"
if [[ ! -f "$LINKED_SOURCES" ]]; then
  python3 "$ROOT_DIR/script/linked_runtime.py" bundle-sources --output "$LINKED_SOURCES" --fetch
fi

mkdir -p "$SPARKLE_DIR"
if [[ ! -f "$SPARKLE_ARCHIVE" ]]; then
  curl --fail --location --silent --show-error \
    "https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/Sparkle-${SPARKLE_VERSION}.tar.xz" \
    --output "$SPARKLE_ARCHIVE"
fi
echo "$SPARKLE_SHA256  $SPARKLE_ARCHIVE" | shasum -a 256 --check
if [[ ! -d "$SPARKLE_FRAMEWORK" ]]; then
  mkdir -p "$SPARKLE_VERSION_DIR"
  tar -xJf "$SPARKLE_ARCHIVE" -C "$SPARKLE_VERSION_DIR"
fi

# Building the application through its Xcode target is required for Icon
# Composer. Xcode links the layered icon stack and generates the compatibility
# renditions as one atomic asset-catalog operation.
DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" xcodebuild \
  -project "$XCODE_PROJECT" \
  -scheme EnCap \
  -configuration Release \
  -derivedDataPath "$XCODE_BUILD_DIR" \
  CODE_SIGNING_ALLOWED=NO \
  ARCHS="$NATIVE_ARCH" \
  ONLY_ACTIVE_ARCH=YES \
  MARKETING_VERSION="$APP_VERSION" \
  CURRENT_PROJECT_VERSION="$APP_VERSION" \
  PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
  build
test -x "$XCODE_APP/Contents/MacOS/EnCap"

cd "$ROOT_DIR"

# The base app/library remain macOS 13 / Intel compatible. Optional Apple
# inference is an isolated dynamically loaded macOS 14 ARM64 library.
mkdir -p "$(dirname "$APPLE_AAC_INFO")"
DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swiftc -swift-version 5 -O -target "$NATIVE_ARCH-apple-macosx13.0" \
  "$ROOT_DIR/helpers/apple_aac_info.swift" -Xlinker -adhoc_codesign \
  -o "$APPLE_AAC_INFO"
has_linker_signature "$APPLE_AAC_INFO"
if [[ "$NATIVE_ARCH" == "arm64" ]]; then
  DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" bash "$ROOT_DIR/script/build_avid_transcriber.sh" "$AVID_RUNTIME"
fi

rm -rf "$APP_BUNDLE"
mkdir -p "$(dirname "$APP_BUNDLE")"
ditto "$XCODE_APP" "$APP_BUNDLE"
mkdir -p "$APP_MACOS" "$APP_RESOURCES" "$APP_FRAMEWORKS"
if [[ ! -s "$APP_RESOURCES/AppIcon.icns" ]]; then
  cp "$LEGACY_ICON" "$APP_RESOURCES/AppIcon.icns"
fi
python3 "$ROOT_DIR/script/linked_runtime.py" stage --target "$LINKED_TARGET" --profile "$LINKED_PROFILE" \
  --prefix "$LINKED_PREFIX" --library "$RUST_LIBRARY" --receipt "$LINKED_RECEIPT" --source-bundle "$LINKED_SOURCES" --destination "$APP_FRAMEWORKS"
cp "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$APP_RESOURCES/THIRD_PARTY_NOTICES.md"
cp "$ROOT_DIR/runtime/AVID_CORE_LICENSE.txt" "$APP_RESOURCES/AVID_CORE_LICENSE.txt"
ditto "$ROOT_DIR/runtime/AVIDCoreImageLicenses" "$APP_RESOURCES/AVIDCoreImageLicenses"
"$FFMPEG_INSTALL_DIR/ffmpeg" -buildconf > "$APP_RESOURCES/FFMPEG_BUILD_CONFIGURATION.txt" 2>&1
ditto "$SPARKLE_FRAMEWORK" "$APP_FRAMEWORKS/Sparkle.framework"
chmod +x "$APP_BINARY"
/usr/libexec/PlistBuddy -c "Add :SUFeedURL string https://github.com/tlolabs/encap/releases/latest/download/appcast-$ENCAP_PLATFORM_NAME.xml" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :SUPublicEDKey string $UPDATE_PUBLIC_KEY" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUEnableAutomaticChecks bool true' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUAutomaticallyUpdate bool false' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUScheduledCheckInterval real 86400' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUVerifyUpdateBeforeExtraction bool true' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SURequireSignedFeed bool true' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUEnableSystemProfiling bool false' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUSendProfileInfo bool false' "$INFO_PLIST"
ENCAP_UPDATE_PUBLIC_KEY="$UPDATE_PUBLIC_KEY" python3 "$ROOT_DIR/script/update_config.py" "$APP_RESOURCES" "$ENCAP_PLATFORM_NAME"

bash "$ROOT_DIR/script/ffmpeg/stage.sh" "$FFMPEG_INSTALL_DIR" "$APP_MACOS" "$APP_RESOURCES/FFmpeg"
cp "$APPLE_AAC_INFO" "$APP_MACOS/apple-aac-info"
chmod +x "$APP_MACOS/apple-aac-info"
if [[ "$NATIVE_ARCH" == "arm64" ]]; then
  ditto "$AVID_RUNTIME" "$APP_FRAMEWORKS/EnCAPTranscription.framework"
  ditto "$(dirname "$AVID_RUNTIME")/EnCAPTranscription-metadata" "$APP_RESOURCES/EnCAPTranscription"
fi
# Notices distinguish the shared SDKs from separately downloaded model weights.
cp "$ROOT_DIR/vendor/avid-core-transcription/apple/AVIDTranscription/MODEL_NOTICES.md" "$APP_RESOURCES/AVID_MODEL_NOTICES.md"
cp "$ROOT_DIR/vendor/avid-core-transcription/apple/AVIDTranscriptionEngines/THIRD_PARTY_NOTICES.md" "$APP_RESOURCES/AVID_TRANSCRIPTION_SDK_NOTICES.md"

# Sign optional SwiftPM bundles and native modules before the enclosing app.
while IFS= read -r -d '' RESOURCE_BUNDLE; do
  codesign --force --sign - "$RESOURCE_BUNDLE"
done < <(find "$APP_FRAMEWORKS/EnCAPTranscription.framework" -type d -name '*.bundle' -print0 2>/dev/null || true)
while IFS= read -r -d '' LIBRARY; do
  codesign --force --sign - "$LIBRARY"
done < <(find "$APP_FRAMEWORKS" -type f -name '*.dylib' -print0)
if [[ -d "$APP_FRAMEWORKS/EnCAPTranscription.framework" ]]; then
  codesign --force --sign - "$APP_FRAMEWORKS/EnCAPTranscription.framework/Versions/A/EnCAPTranscription"
fi
if [[ -d "$APP_FRAMEWORKS/EnCAPTranscription.framework" ]]; then
  codesign --force --sign - "$APP_FRAMEWORKS/EnCAPTranscription.framework"
  python3 "$ROOT_DIR/script/stage_avid_transcriber.py" --bind-signature "$APP_FRAMEWORKS/EnCAPTranscription.framework" --metadata-directory "$APP_RESOURCES/EnCAPTranscription"
fi
python3 "$ROOT_DIR/script/linked_runtime.py" verify-stage --directory "$APP_FRAMEWORKS" --bind-signature

for SIGNABLE in "$APP_MACOS"/*; do
  [[ -f "$SIGNABLE" ]] || continue
  case "$(basename "$SIGNABLE")" in ffmpeg|ffprobe) continue;; esac
  file -b "$SIGNABLE" | grep -q 'Mach-O' || continue
  codesign --force --sign - "$SIGNABLE"
done
# Missing models/failing diagnostics remain visible without preventing ordinary
# app development. The per-artifact publisher requires a passed report.
if ! python3 "$ROOT_DIR/script/qualify_transcription.py" --application "$APP_BINARY" --output "$APP_RESOURCES/transcription-qualification.json" ${ENCAP_QUALIFICATION_INSTALL_MODELS:+--install-model}; then
  echo "Transcription qualification failed; see $APP_RESOURCES/transcription-qualification.json. This artifact is ineligible for publication." >&2
fi
codesign --force --sign - "$APP_FRAMEWORKS/Sparkle.framework"
codesign --force --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"
plutil -lint "$INFO_PLIST"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")" = "$BUNDLE_ID"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$INFO_PLIST")" = "$APP_VERSION"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconName' "$INFO_PLIST")" = "AppIcon"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconFile' "$INFO_PLIST")" = "AppIcon"
test -s "$APP_RESOURCES/AppIcon.icns"
if [[ -s "$APP_RESOURCES/Assets.car" ]]; then
  assetutil --info "$APP_RESOURCES/Assets.car" > "$ICON_REPORT"
  grep '"AssetType" : "IconImageStack"' "$ICON_REPORT" >/dev/null
fi
file "$APP_BINARY" | grep "$NATIVE_ARCH" >/dev/null

# Exercise the actual packaged facade. No engine/media child is needed for
# project, image, Video and supported transcription operations. Audio remains
# an explicitly documented compatibility exception and is not qualified here.
"$APP_BINARY" --linked-operation build-info
"$APP_BINARY" --linked-operation validate-tools
python3 "$ROOT_DIR/script/linked_runtime.py" verify-stage --directory "$APP_FRAMEWORKS"
export ENCAP_APP_LIBRARY="$APP_LIBRARY"
if [[ "$NATIVE_ARCH" != "$HOST_ARCH" ]]; then
  # SwiftPM's test helper launches as the host architecture. Run the compiled
  # Intel XCTest bundle under Rosetta instead when cross-building locally.
  DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swift build --build-tests --arch "$NATIVE_ARCH" --package-path "$ROOT_DIR/macos" --scratch-path "$ROOT_DIR/build/native-swift-$NATIVE_ARCH"
  TEST_BIN_DIR="$(DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swift build --show-bin-path --arch "$NATIVE_ARCH" --package-path "$ROOT_DIR/macos" --scratch-path "$ROOT_DIR/build/native-swift-$NATIVE_ARCH")"
  test -d "$TEST_BIN_DIR/EnCapTests.xctest"
  arch -"$NATIVE_ARCH" "$XCODE_DEVELOPER_DIR/usr/bin/xctest" "$TEST_BIN_DIR/EnCapTests.xctest"
else
  DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swift test --disable-sandbox --package-path "$ROOT_DIR/macos" --scratch-path "$ROOT_DIR/build/native-swift-$NATIVE_ARCH"
fi
if otool -L "$APP_MACOS/ffmpeg" "$APP_MACOS/ffprobe" | grep -E '/(opt|usr/local)/homebrew|/Cellar/'; then
  echo "Packaged FFmpeg must not link Homebrew libraries." >&2
  exit 1
fi

open_app() {
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APP_BUNDLE" >/dev/null
  /usr/bin/open -n "$APP_BUNDLE"
}

package_zip() {
  local zip_path="$ROOT_DIR/dist/EnCap-${APP_VERSION}-macos-${ARCH_LABEL}-development-unnotarized.zip"
  [[ ! -e "$zip_path" ]] || { echo "Development package already exists; refusing replacement." >&2; return 1; }
  ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$zip_path"
  echo "$zip_path"
}

case "$MODE" in
  run) open_app ;;
  --debug|debug) lldb -- "$APP_BINARY" ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 2
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  --package|package) ENCAP_APP_BUNDLE="$APP_BUNDLE" "$ROOT_DIR/script/sign_macos_release.sh" ;;
  --package-development) package_zip ;;
  --build-development) echo "Built unnotarized, unqualified development bundle: $APP_BUNDLE" ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package|--package-development|--build-development]" >&2
    exit 2
    ;;
esac
